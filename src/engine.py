"""
Discrete Event Simulation Engine

This module implements the core simulation runtime for the Electric Bus
Scheduling Engine. The engine processes discrete events (DEPART, ARRIVE,
CHARGE_START, CHARGE_END) in strict chronological order using a priority queue.

Key Features:
- State isolation: Changes occur only at event boundaries
- Deterministic: Identical inputs produce identical outputs
- Scalable: O(E log E) complexity where E = number of events
- Queue-aware: Natural FIFO handling for charger contention

See ADR/0003_discrete_event_simulation_engine.md for architectural decisions.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.models import BusInput, RouteConfig, ScenarioInput, StationConfig
from src.navigation import RouteManager
from src.rules import evaluate_queue


# =============================================================================
# Constants
# =============================================================================

CHARGE_TIME_MINS: float = 25.0
SPEED_KM_PER_MIN: float = 1.0  # 60 km/h = 1 km/min
MAX_RANGE_KM: float = 240.0


# =============================================================================
# Event Types and Structure
# =============================================================================


class EventType(Enum):
    """
    Discrete event types for the simulation.

    Processing priority (for tie-breaking when times are equal):
    1. CHARGE_END - Free chargers first to allow waiting buses to start
    2. ARRIVE - Process arrivals before departures at same time
    3. CHARGE_START - Start charging after arrival processing
    4. DEPART - Departures processed last
    """

    CHARGE_END = 1      # Highest priority (free resources first)
    ARRIVE = 2          # Process arrivals
    CHARGE_START = 3    # Start charging
    DEPART = 4          # Lowest priority


@dataclass
class Event:
    """
    A discrete event in the simulation.

    Events are ordered by:
    1. time_mins (primary) - chronological order
    2. event_type.value (secondary) - priority for simultaneous events
    3. sequence (tertiary) - insertion order for determinism

    Attributes:
        time_mins: When the event occurs (minutes from midnight).
        event_type: Type of event (DEPART, ARRIVE, CHARGE_START, CHARGE_END).
        sequence: Unique sequence number for deterministic tie-breaking.
        bus_id: Identifier of the bus involved.
        location: Where the event occurs (station ID, origin, or destination).
    """

    time_mins: float
    event_type: EventType
    sequence: int
    bus_id: str
    location: str

    def __lt__(self, other: 'Event') -> bool:
        """Compare events for priority queue ordering."""
        if not isinstance(other, Event):
            return NotImplemented
        # Compare by (time, event_type.value, sequence)
        return (self.time_mins, self.event_type.value, self.sequence) < \
               (other.time_mins, other.event_type.value, other.sequence)

    def __le__(self, other: 'Event') -> bool:
        """Compare events for priority queue ordering."""
        if not isinstance(other, Event):
            return NotImplemented
        return (self.time_mins, self.event_type.value, self.sequence) <= \
               (other.time_mins, other.event_type.value, other.sequence)

    def __gt__(self, other: 'Event') -> bool:
        """Compare events for priority queue ordering."""
        if not isinstance(other, Event):
            return NotImplemented
        return (self.time_mins, self.event_type.value, self.sequence) > \
               (other.time_mins, other.event_type.value, other.sequence)

    def __ge__(self, other: 'Event') -> bool:
        """Compare events for priority queue ordering."""
        if not isinstance(other, Event):
            return NotImplemented
        return (self.time_mins, self.event_type.value, self.sequence) >= \
               (other.time_mins, other.event_type.value, other.sequence)


# =============================================================================
# State Tracking
# =============================================================================


@dataclass
class BusState:
    """
    Runtime state for a single bus during simulation.

    Attributes:
        bus_id: Unique identifier for the bus.
        operator: Operator name.
        direction: Travel direction.
        departure_time_mins: Scheduled departure time from origin.
        current_time_mins: Current simulation time for this bus.
        remaining_range_km: Battery range remaining.
        current_location: Current position (station ID, origin, or destination).
        planned_stops: List of station IDs where charging is planned.
        next_stop_index: Index into planned_stops for next charging station.
        itinerary: Detailed log of all events for this bus.
        total_travel_time: Accumulated travel time (in transit).
        total_charge_time: Accumulated charging time.
        total_wait_time: Accumulated waiting time in queues.
        completed: Whether the bus has reached its destination.
        queue_arrival_time: Time when bus joined the current queue (for priority scoring).
    """

    bus_id: str
    operator: str
    direction: str
    departure_time_mins: int
    current_time_mins: float = 0.0
    remaining_range_km: float = MAX_RANGE_KM
    current_location: str = ""
    planned_stops: List[str] = field(default_factory=list)
    next_stop_index: int = 0
    itinerary: List[Dict[str, Any]] = field(default_factory=list)
    total_travel_time: float = 0.0
    total_charge_time: float = 0.0
    total_wait_time: float = 0.0
    completed: bool = False
    queue_arrival_time: Optional[float] = None

    def log_event(
        self,
        time_mins: float,
        event_type: str,
        location: str,
        **extra: Any
    ) -> None:
        """
        Add an event to the bus's itinerary log.

        Args:
            time_mins: When the event occurred.
            event_type: Type of event (string representation).
            location: Where the event occurred.
            **extra: Additional data to include in the log entry.
        """
        entry = {
            "time_mins": time_mins,
            "event": event_type,
            "location": location,
            **extra
        }
        self.itinerary.append(entry)


@dataclass
class StationState:
    """
    Runtime state for a charging station during simulation.

    Attributes:
        station_id: Unique identifier for the station.
        name: Human-readable station name.
        total_chargers: Total number of chargers available.
        busy_chargers: Number of chargers currently in use.
        queue: FIFO queue of bus IDs waiting for a charger.
        total_charges: Total number of charging sessions completed.
        total_queue_time: Total time buses spent waiting in queue.
        max_queue_length: Maximum queue length observed.
        charge_log: Detailed log of charging sessions.
    """

    station_id: str
    name: str
    total_chargers: int
    busy_chargers: int = 0
    queue: deque = field(default_factory=deque)
    total_charges: int = 0
    total_queue_time: float = 0.0
    max_queue_length: int = 0
    charge_log: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def available_chargers(self) -> int:
        """Number of chargers currently available."""
        return self.total_chargers - self.busy_chargers

    def is_charger_available(self) -> bool:
        """Check if at least one charger is available."""
        return self.available_chargers > 0

    def occupy_charger(self) -> None:
        """Mark one charger as busy."""
        if self.busy_chargers >= self.total_chargers:
            raise RuntimeError(
                f"Station {self.station_id}: Cannot occupy charger, all busy"
            )
        self.busy_chargers += 1

    def release_charger(self) -> None:
        """Mark one charger as available."""
        if self.busy_chargers <= 0:
            raise RuntimeError(
                f"Station {self.station_id}: Cannot release charger, none busy"
            )
        self.busy_chargers -= 1

    def enqueue(self, bus_id: str) -> None:
        """Add a bus to the waiting queue."""
        self.queue.append(bus_id)
        self.max_queue_length = max(self.max_queue_length, len(self.queue))

    def dequeue(self) -> Optional[str]:
        """Remove and return the next bus from the queue, or None if empty."""
        if self.queue:
            return self.queue.popleft()
        return None

    def log_charge(
        self,
        bus_id: str,
        start_time: float,
        end_time: float,
        wait_time: float
    ) -> None:
        """Log a completed charging session."""
        self.charge_log.append({
            "bus_id": bus_id,
            "start_time": start_time,
            "end_time": end_time,
            "wait_time": wait_time,
            "duration": end_time - start_time
        })
        self.total_charges += 1
        self.total_queue_time += wait_time


# =============================================================================
# Simulation Engine
# =============================================================================


class SimulationEngine:
    """
    Discrete Event Simulation engine for bus charging scheduling.

    The engine maintains a priority queue of events and processes them
    in chronological order. Events include bus departures, arrivals,
    charging starts, and charging completions.

    Attributes:
        scenario: The scenario being simulated.
        route_manager: RouteManager for distance calculations.
        bus_states: Mapping of bus_id to BusState.
        station_states: Mapping of station_id to StationState.
        event_queue: Priority queue (min-heap) of pending events.
        sequence_counter: Counter for event sequence numbers.
        current_time: Current simulation time.

    Example:
        >>> from src.models import ScenarioInput
        >>> scenario = ScenarioInput(...)
        >>> engine = SimulationEngine(scenario)
        >>> results = engine.run()
    """

    def __init__(self, scenario: ScenarioInput) -> None:
        """
        Initialize the simulation engine with a scenario.

        Args:
            scenario: Validated scenario input containing route, buses, and weights.
        """
        self.scenario = scenario
        self.route_manager = RouteManager(scenario.route)

        # State trackers
        self.bus_states: Dict[str, BusState] = {}
        self.station_states: Dict[str, StationState] = {}

        # Event queue (min-heap)
        self._event_queue: List[Event] = []
        self._sequence_counter: int = 0

        # Simulation time
        self.current_time: float = 0.0

        # Initialize states
        self._initialize_states()

    def _initialize_states(self) -> None:
        """Initialize bus and station state trackers."""
        # Initialize station states
        for station in self.scenario.route.stations:
            self.station_states[station.id] = StationState(
                station_id=station.id,
                name=station.name,
                total_chargers=station.charger_count
            )

        # Initialize bus states
        for bus in self.scenario.buses:
            # Determine start location based on direction
            if self._is_forward_direction(bus.direction):
                start_location = self.scenario.route.origin
            else:
                start_location = self.scenario.route.destination

            self.bus_states[bus.id] = BusState(
                bus_id=bus.id,
                operator=bus.operator,
                direction=bus.direction,
                departure_time_mins=bus.departure_time_mins,
                current_time_mins=float(bus.departure_time_mins),
                current_location=start_location,
                remaining_range_km=MAX_RANGE_KM,
                # Default: charge at all stations (can be customized)
                planned_stops=self._get_default_charge_plan(bus)
            )

    def _is_forward_direction(self, direction: str) -> bool:
        """Check if direction is forward (origin → destination)."""
        forward = f"{self.scenario.route.origin}→{self.scenario.route.destination}"
        return direction == forward

    def _get_default_charge_plan(self, bus: BusInput) -> List[str]:
        """
        Get a default charge plan for a bus.

        Uses the RouteManager's greedy algorithm to determine minimum
        required charging stops.

        Args:
            bus: The bus input configuration.

        Returns:
            List of station IDs where the bus should charge.
        """
        return self.route_manager.get_required_stations(
            direction=bus.direction,
            departure_time_mins=bus.departure_time_mins
        )

    def _next_sequence(self) -> int:
        """Get the next sequence number for event ordering."""
        seq = self._sequence_counter
        self._sequence_counter += 1
        return seq

    def _schedule_event(
        self,
        time_mins: float,
        event_type: EventType,
        bus_id: str,
        location: str
    ) -> None:
        """
        Schedule a new event.

        Args:
            time_mins: When the event should occur.
            event_type: Type of event.
            bus_id: ID of the bus involved.
            location: Where the event occurs.
        """
        event = Event(
            time_mins=time_mins,
            event_type=event_type,
            sequence=self._next_sequence(),
            bus_id=bus_id,
            location=location
        )
        heapq.heappush(self._event_queue, event)

    def _get_next_node(self, bus_state: BusState) -> Optional[str]:
        """
        Determine the next node (station or destination) for a bus.

        Args:
            bus_state: Current state of the bus.

        Returns:
            Next node ID, or None if the bus has reached its destination.
        """
        direction = bus_state.direction
        current = bus_state.current_location

        # Get destination based on direction
        if self._is_forward_direction(direction):
            destination = self.scenario.route.destination
        else:
            destination = self.scenario.route.origin

        # If already at destination, we're done
        if current == destination:
            return None

        # Get ordered stations for this direction
        ordered_stations = self.route_manager.get_ordered_stations(direction)
        station_ids = [s.id for s in ordered_stations]

        # Find current position in the route
        if current == self.route_manager.origin if self._is_forward_direction(direction) else self.route_manager.destination:
            # Starting from origin/destination - next is first station or destination
            if station_ids:
                return station_ids[0]
            return destination

        # Currently at a station - find next station or destination
        if current in station_ids:
            current_idx = station_ids.index(current)
            if current_idx + 1 < len(station_ids):
                return station_ids[current_idx + 1]
            return destination

        # Shouldn't reach here
        return destination

    def _should_charge_at(self, bus_state: BusState, station_id: str) -> bool:
        """
        Check if a bus should charge at a given station.

        Args:
            bus_state: Current state of the bus.
            station_id: Station to check.

        Returns:
            True if the bus's plan includes charging at this station.
        """
        return station_id in bus_state.planned_stops

    # =========================================================================
    # Event Handlers
    # =========================================================================

    def _handle_depart(self, event: Event) -> None:
        """
        Handle a DEPART event.

        Bus leaves its current location and travels to the next node.
        Calculates travel time based on distance and speed, then schedules
        an ARRIVE event.
        """
        bus_state = self.bus_states[event.bus_id]

        # Log departure
        bus_state.log_event(
            time_mins=event.time_mins,
            event_type="DEPART",
            location=event.location,
            remaining_range_km=bus_state.remaining_range_km
        )

        # Determine next node
        next_node = self._get_next_node(bus_state)
        if next_node is None:
            # Bus has reached final destination
            bus_state.completed = True
            bus_state.log_event(
                time_mins=event.time_mins,
                event_type="JOURNEY_COMPLETE",
                location=event.location
            )
            return

        # Calculate travel time
        distance = self.route_manager.get_segment_distance(
            event.location, next_node
        )
        travel_time = distance / SPEED_KM_PER_MIN

        # Update bus state
        bus_state.remaining_range_km -= distance
        bus_state.total_travel_time += travel_time
        bus_state.current_location = next_node

        # Schedule arrival
        arrival_time = event.time_mins + travel_time
        self._schedule_event(
            time_mins=arrival_time,
            event_type=EventType.ARRIVE,
            bus_id=event.bus_id,
            location=next_node
        )

    def _handle_arrive(self, event: Event) -> None:
        """
        Handle an ARRIVE event.

        Bus arrives at a station or destination. If the bus needs to charge:
        - If a charger is available, schedule CHARGE_START immediately
        - If all chargers are busy, add to the station's queue

        If the bus doesn't need to charge (or it's the destination),
        schedule immediate DEPART.
        """
        bus_state = self.bus_states[event.bus_id]
        bus_state.current_time_mins = event.time_mins

        # Log arrival
        bus_state.log_event(
            time_mins=event.time_mins,
            event_type="ARRIVE",
            location=event.location,
            remaining_range_km=bus_state.remaining_range_km
        )

        # Check if this is the final destination
        if self._is_forward_direction(bus_state.direction):
            destination = self.scenario.route.destination
        else:
            destination = self.scenario.route.origin

        if event.location == destination:
            # Journey complete
            bus_state.completed = True
            bus_state.log_event(
                time_mins=event.time_mins,
                event_type="JOURNEY_COMPLETE",
                location=event.location
            )
            return

        # Check if bus should charge at this station
        if self._should_charge_at(bus_state, event.location):
            station_state = self.station_states[event.location]

            if station_state.is_charger_available():
                # Charger available - start charging immediately
                station_state.occupy_charger()
                self._schedule_event(
                    time_mins=event.time_mins,
                    event_type=EventType.CHARGE_START,
                    bus_id=event.bus_id,
                    location=event.location
                )
            else:
                # All chargers busy - join queue
                station_state.enqueue(event.bus_id)
                bus_state.queue_arrival_time = event.time_mins  # Track for priority scoring
                bus_state.log_event(
                    time_mins=event.time_mins,
                    event_type="QUEUE_JOIN",
                    location=event.location,
                    queue_position=len(station_state.queue)
                )
        else:
            # No charging needed - depart immediately
            self._schedule_event(
                time_mins=event.time_mins,
                event_type=EventType.DEPART,
                bus_id=event.bus_id,
                location=event.location
            )

    def _handle_charge_start(self, event: Event) -> None:
        """
        Handle a CHARGE_START event.

        Resets bus battery to full range (240 km) and schedules CHARGE_END
        after the charging duration (25 minutes).
        """
        bus_state = self.bus_states[event.bus_id]
        station_state = self.station_states[event.location]

        # Calculate wait time (time since arrival)
        arrival_entry = None
        for entry in reversed(bus_state.itinerary):
            if entry["event"] == "ARRIVE" and entry["location"] == event.location:
                arrival_entry = entry
                break

        wait_time = 0.0
        if arrival_entry:
            wait_time = event.time_mins - arrival_entry["time_mins"]
            bus_state.total_wait_time += wait_time

        # Log charge start
        bus_state.log_event(
            time_mins=event.time_mins,
            event_type="CHARGE_START",
            location=event.location,
            wait_time=wait_time,
            range_before=bus_state.remaining_range_km
        )

        # Reset battery to full
        bus_state.remaining_range_km = MAX_RANGE_KM

        # Schedule charge end
        charge_end_time = event.time_mins + CHARGE_TIME_MINS
        bus_state.total_charge_time += CHARGE_TIME_MINS

        self._schedule_event(
            time_mins=charge_end_time,
            event_type=EventType.CHARGE_END,
            bus_id=event.bus_id,
            location=event.location
        )

        # Store charge start info for logging
        bus_state._charge_start_time = event.time_mins
        bus_state._charge_wait_time = wait_time

    def _handle_charge_end(self, event: Event) -> None:
        """
        Handle a CHARGE_END event.

        Frees the charger. If buses are waiting in the queue, the next bus
        starts charging. The current bus departs toward its next destination.
        """
        bus_state = self.bus_states[event.bus_id]
        station_state = self.station_states[event.location]

        # Get charge info before clearing
        charge_start_time = getattr(bus_state, '_charge_start_time', event.time_mins - CHARGE_TIME_MINS)
        wait_time = getattr(bus_state, '_charge_wait_time', 0.0)

        # Log charge end
        bus_state.log_event(
            time_mins=event.time_mins,
            event_type="CHARGE_END",
            location=event.location,
            range_after=bus_state.remaining_range_km
        )

        # Log to station
        station_state.log_charge(
            bus_id=event.bus_id,
            start_time=charge_start_time,
            end_time=event.time_mins,
            wait_time=wait_time
        )

        # Release charger
        station_state.release_charger()

        # Check if any bus is waiting in the queue
        # Use weighted priority scoring instead of FIFO
        if station_state.queue:
            # Build list of BusState objects from queue
            queue_bus_states = [
                self.bus_states[bus_id]
                for bus_id in station_state.queue
                if bus_id in self.bus_states
            ]

            if queue_bus_states:
                # Use evaluate_queue to select highest priority bus
                next_bus = evaluate_queue(
                    queue=queue_bus_states,
                    current_time=event.time_mins,
                    stations_state=self.station_states,
                    scenario_weights=self.scenario.weights,
                    route_manager=self.route_manager,
                    bus_states=self.bus_states
                )

                if next_bus:
                    # Remove selected bus from queue
                    station_state.queue.remove(next_bus.bus_id)
                    next_bus.queue_arrival_time = None  # Clear queue arrival time

                    # Start charging for the selected bus
                    station_state.occupy_charger()
                    self._schedule_event(
                        time_mins=event.time_mins,
                        event_type=EventType.CHARGE_START,
                        bus_id=next_bus.bus_id,
                        location=event.location
                    )

        # Schedule departure for the current bus
        self._schedule_event(
            time_mins=event.time_mins,
            event_type=EventType.DEPART,
            bus_id=event.bus_id,
            location=event.location
        )

        bus_state.current_time_mins = event.time_mins

    # =========================================================================
    # Main Simulation Loop
    # =========================================================================

    def run(self) -> Dict[str, Any]:
        """
        Execute the simulation and return comprehensive results.

        Returns:
            Dictionary containing:
            - scenario_id: ID of the simulated scenario
            - total_simulation_time_mins: Total time to complete all journeys
            - buses: Per-bus results including itineraries
            - stations: Per-station statistics
            - events_processed: Total number of events processed
        """
        # Schedule initial DEPART events for all buses
        for bus_id, bus_state in self.bus_states.items():
            self._schedule_event(
                time_mins=float(bus_state.departure_time_mins),
                event_type=EventType.DEPART,
                bus_id=bus_id,
                location=bus_state.current_location
            )

        # Process events
        events_processed = 0
        while self._event_queue:
            event = heapq.heappop(self._event_queue)
            self.current_time = event.time_mins

            # Dispatch to appropriate handler
            if event.event_type == EventType.DEPART:
                self._handle_depart(event)
            elif event.event_type == EventType.ARRIVE:
                self._handle_arrive(event)
            elif event.event_type == EventType.CHARGE_START:
                self._handle_charge_start(event)
            elif event.event_type == EventType.CHARGE_END:
                self._handle_charge_end(event)

            events_processed += 1

        # Compile results
        return self._compile_results(events_processed)

    def _compile_results(self, events_processed: int) -> Dict[str, Any]:
        """
        Compile simulation results into a comprehensive output structure.

        Args:
            events_processed: Total number of events processed.

        Returns:
            Dictionary with detailed simulation results.
        """
        # Calculate total simulation time
        max_completion_time = 0.0
        for bus_state in self.bus_states.values():
            if bus_state.itinerary:
                last_event_time = bus_state.itinerary[-1]["time_mins"]
                max_completion_time = max(max_completion_time, last_event_time)

        # Compile bus results
        buses_result = {}
        for bus_id, bus_state in self.bus_states.items():
            # Find departure and arrival times
            departure_time = bus_state.departure_time_mins
            arrival_time = departure_time  # Default if not completed

            if bus_state.itinerary:
                for entry in reversed(bus_state.itinerary):
                    if entry["event"] in ("JOURNEY_COMPLETE", "ARRIVE"):
                        arrival_time = entry["time_mins"]
                        break

            buses_result[bus_id] = {
                "bus_id": bus_id,
                "operator": bus_state.operator,
                "direction": bus_state.direction,
                "departure_time_mins": departure_time,
                "arrival_time_mins": arrival_time,
                "total_journey_time_mins": arrival_time - departure_time,
                "total_travel_time_mins": bus_state.total_travel_time,
                "total_charge_time_mins": bus_state.total_charge_time,
                "total_wait_time_mins": bus_state.total_wait_time,
                "planned_stops": bus_state.planned_stops,
                "completed": bus_state.completed,
                "itinerary": bus_state.itinerary
            }

        # Compile station results
        stations_result = {}
        for station_id, station_state in self.station_states.items():
            stations_result[station_id] = {
                "station_id": station_id,
                "name": station_state.name,
                "total_chargers": station_state.total_chargers,
                "total_charges": station_state.total_charges,
                "total_queue_time_mins": station_state.total_queue_time,
                "max_queue_length": station_state.max_queue_length,
                "charge_log": station_state.charge_log
            }

        return {
            "scenario_id": self.scenario.id,
            "description": self.scenario.description,
            "total_simulation_time_mins": max_completion_time,
            "events_processed": events_processed,
            "buses": buses_result,
            "stations": stations_result,
            "summary": {
                "total_buses": len(self.bus_states),
                "completed_buses": sum(
                    1 for b in self.bus_states.values() if b.completed
                ),
                "total_stations": len(self.station_states),
                "total_charges": sum(
                    s.total_charges for s in self.station_states.values()
                ),
                "total_queue_time_mins": sum(
                    s.total_queue_time for s in self.station_states.values()
                )
            }
        }


# =============================================================================
# Public API
# =============================================================================


def compute_travel_timeline(scenario: ScenarioInput) -> Dict[str, Any]:
    """
    Compute the travel timeline for a scenario using discrete event simulation.

    This is the primary entry point for running a simulation. It initializes
    the simulation engine, processes all events, and returns comprehensive
    results including per-bus itineraries and per-station statistics.

    Args:
        scenario: Validated ScenarioInput containing route, buses, and weights.

    Returns:
        Dictionary containing:
        - scenario_id: ID of the simulated scenario
        - total_simulation_time_mins: Total time to complete all journeys
        - buses: Dict mapping bus_id to detailed results including:
            - departure_time_mins, arrival_time_mins
            - total_travel_time_mins, total_charge_time_mins, total_wait_time_mins
            - itinerary: List of events with timestamps
        - stations: Dict mapping station_id to statistics:
            - total_charges, total_queue_time_mins, max_queue_length
        - summary: Aggregate statistics

    Example:
        >>> from src.models import ScenarioInput, RouteConfig, BusInput
        >>> scenario = ScenarioInput(
        ...     id="test",
        ...     description="Test scenario",
        ...     route=RouteConfig(origin="A", destination="B", ...),
        ...     buses=[BusInput(id="B1", ...)]
        ... )
        >>> results = compute_travel_timeline(scenario)
        >>> print(results["buses"]["B1"]["total_journey_time_mins"])
    """
    engine = SimulationEngine(scenario)
    return engine.run()

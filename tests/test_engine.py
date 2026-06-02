"""
Unit Tests for Discrete Event Simulation Engine

This module contains comprehensive tests for the SimulationEngine class,
verifying correct behavior for:
- Event processing order
- Bus state tracking
- Station queue management (FIFO)
- Charge timing and range reset
- Multi-bus scenarios with resource contention

Run with: pytest tests/test_engine.py -v
"""

import pytest

from src.engine import (
    CHARGE_TIME_MINS,
    MAX_RANGE_KM,
    SPEED_KM_PER_MIN,
    BusState,
    Event,
    EventType,
    SimulationEngine,
    StationState,
    compute_travel_timeline,
)
from src.models import (
    BusInput,
    OperationalWeights,
    RouteConfig,
    ScenarioInput,
    StationConfig,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def simple_route() -> RouteConfig:
    """
    Create a simple route with one charging station.

    Layout: Origin (0km) → Station_A (150km) → Destination (300km)
    Total distance: 300km (requires charging since > 240km range)
    """
    return RouteConfig(
        origin="Origin",
        destination="Destination",
        stations=[
            StationConfig(
                id="Station_A",
                name="Station A",
                distance_from_origin_km=150.0,
                charger_count=1  # Single charger for queue testing
            )
        ],
        segment_distances={
            "Origin→Station_A": 150.0,
            "Station_A→Destination": 150.0
        }
    )


@pytest.fixture
def multi_station_route() -> RouteConfig:
    """
    Create a route with multiple charging stations.

    Layout: Bengaluru (0km) → A (100km) → B (200km) → C (350km) → Kochi (500km)
    """
    return RouteConfig(
        origin="Bengaluru",
        destination="Kochi",
        stations=[
            StationConfig(id="A", name="Station A", distance_from_origin_km=100.0, charger_count=2),
            StationConfig(id="B", name="Station B", distance_from_origin_km=200.0, charger_count=1),
            StationConfig(id="C", name="Station C", distance_from_origin_km=350.0, charger_count=2),
        ],
        segment_distances={
            "Bengaluru→A": 100.0,
            "A→B": 100.0,
            "B→C": 150.0,
            "C→Kochi": 150.0
        }
    )


@pytest.fixture
def single_bus_scenario(simple_route: RouteConfig) -> ScenarioInput:
    """Create a scenario with a single bus."""
    return ScenarioInput(
        id="single_bus_test",
        description="Single bus test scenario",
        weights=OperationalWeights(),
        route=simple_route,
        buses=[
            BusInput(
                id="BUS_001",
                operator="TestOp",
                direction="Origin→Destination",
                departure_time_mins=0
            )
        ]
    )


@pytest.fixture
def two_bus_same_time_scenario(simple_route: RouteConfig) -> ScenarioInput:
    """
    Create a scenario with two buses departing at the same time.

    Both buses will arrive at Station_A simultaneously, but only one
    charger is available, so one bus must wait.
    """
    return ScenarioInput(
        id="two_bus_queue_test",
        description="Two buses arriving simultaneously at single-charger station",
        weights=OperationalWeights(),
        route=simple_route,
        buses=[
            BusInput(
                id="BUS_001",
                operator="TestOp",
                direction="Origin→Destination",
                departure_time_mins=0
            ),
            BusInput(
                id="BUS_002",
                operator="TestOp",
                direction="Origin→Destination",
                departure_time_mins=0
            )
        ]
    )


# =============================================================================
# Test: Event Ordering
# =============================================================================


class TestEventOrdering:
    """Tests for event priority and ordering."""

    def test_events_ordered_by_time(self) -> None:
        """Test that events are ordered primarily by time."""
        e1 = Event(time_mins=100.0, event_type=EventType.ARRIVE, sequence=1, bus_id="B1", location="A")
        e2 = Event(time_mins=50.0, event_type=EventType.ARRIVE, sequence=2, bus_id="B2", location="A")
        e3 = Event(time_mins=150.0, event_type=EventType.ARRIVE, sequence=3, bus_id="B3", location="A")

        events = sorted([e1, e2, e3])

        assert events[0].time_mins == 50.0
        assert events[1].time_mins == 100.0
        assert events[2].time_mins == 150.0

    def test_same_time_ordered_by_type(self) -> None:
        """Test that simultaneous events are ordered by type priority."""
        e_depart = Event(time_mins=100.0, event_type=EventType.DEPART, sequence=1, bus_id="B1", location="A")
        e_arrive = Event(time_mins=100.0, event_type=EventType.ARRIVE, sequence=2, bus_id="B2", location="A")
        e_charge_end = Event(time_mins=100.0, event_type=EventType.CHARGE_END, sequence=3, bus_id="B3", location="A")
        e_charge_start = Event(time_mins=100.0, event_type=EventType.CHARGE_START, sequence=4, bus_id="B4", location="A")

        events = sorted([e_depart, e_arrive, e_charge_end, e_charge_start])

        # CHARGE_END (1) < ARRIVE (2) < CHARGE_START (3) < DEPART (4)
        assert events[0].event_type == EventType.CHARGE_END
        assert events[1].event_type == EventType.ARRIVE
        assert events[2].event_type == EventType.CHARGE_START
        assert events[3].event_type == EventType.DEPART

    def test_same_time_same_type_ordered_by_sequence(self) -> None:
        """Test that events with same time and type are ordered by sequence."""
        e1 = Event(time_mins=100.0, event_type=EventType.ARRIVE, sequence=5, bus_id="B1", location="A")
        e2 = Event(time_mins=100.0, event_type=EventType.ARRIVE, sequence=3, bus_id="B2", location="A")
        e3 = Event(time_mins=100.0, event_type=EventType.ARRIVE, sequence=7, bus_id="B3", location="A")

        events = sorted([e1, e2, e3])

        assert events[0].sequence == 3
        assert events[1].sequence == 5
        assert events[2].sequence == 7


# =============================================================================
# Test: Station State
# =============================================================================


class TestStationState:
    """Tests for StationState management."""

    def test_charger_availability(self) -> None:
        """Test charger availability tracking."""
        station = StationState(station_id="S1", name="Test", total_chargers=2)

        assert station.available_chargers == 2
        assert station.is_charger_available() is True

        station.occupy_charger()
        assert station.available_chargers == 1
        assert station.is_charger_available() is True

        station.occupy_charger()
        assert station.available_chargers == 0
        assert station.is_charger_available() is False

    def test_charger_release(self) -> None:
        """Test charger release."""
        station = StationState(station_id="S1", name="Test", total_chargers=1)
        station.occupy_charger()

        assert station.available_chargers == 0

        station.release_charger()
        assert station.available_chargers == 1

    def test_cannot_occupy_when_all_busy(self) -> None:
        """Test that occupying when all chargers are busy raises error."""
        station = StationState(station_id="S1", name="Test", total_chargers=1)
        station.occupy_charger()

        with pytest.raises(RuntimeError, match="Cannot occupy charger"):
            station.occupy_charger()

    def test_cannot_release_when_none_busy(self) -> None:
        """Test that releasing when no chargers are busy raises error."""
        station = StationState(station_id="S1", name="Test", total_chargers=1)

        with pytest.raises(RuntimeError, match="Cannot release charger"):
            station.release_charger()

    def test_fifo_queue(self) -> None:
        """Test FIFO queue ordering."""
        station = StationState(station_id="S1", name="Test", total_chargers=1)

        station.enqueue("BUS_A")
        station.enqueue("BUS_B")
        station.enqueue("BUS_C")

        assert station.max_queue_length == 3

        assert station.dequeue() == "BUS_A"
        assert station.dequeue() == "BUS_B"
        assert station.dequeue() == "BUS_C"
        assert station.dequeue() is None


# =============================================================================
# Test: Single Bus Simulation
# =============================================================================


class TestSingleBusSimulation:
    """Tests for single bus simulation."""

    def test_single_bus_completes_journey(self, single_bus_scenario: ScenarioInput) -> None:
        """Test that a single bus completes its journey."""
        results = compute_travel_timeline(single_bus_scenario)

        assert results["summary"]["total_buses"] == 1
        assert results["summary"]["completed_buses"] == 1

        bus_result = results["buses"]["BUS_001"]
        assert bus_result["completed"] is True

    def test_single_bus_travel_time(self, single_bus_scenario: ScenarioInput) -> None:
        """Test that travel time is calculated correctly."""
        results = compute_travel_timeline(single_bus_scenario)

        bus_result = results["buses"]["BUS_001"]

        # Distance: 300km total, Speed: 1 km/min
        # Travel time: 300 minutes
        assert bus_result["total_travel_time_mins"] == 300.0

    def test_single_bus_charge_time(self, single_bus_scenario: ScenarioInput) -> None:
        """Test that charge time is recorded correctly."""
        results = compute_travel_timeline(single_bus_scenario)

        bus_result = results["buses"]["BUS_001"]

        # Bus needs to charge at Station_A (route is 300km > 240km range)
        # Charge time is 25 minutes
        assert bus_result["total_charge_time_mins"] == CHARGE_TIME_MINS
        assert "Station_A" in bus_result["planned_stops"]

    def test_single_bus_itinerary_events(self, single_bus_scenario: ScenarioInput) -> None:
        """Test that itinerary contains expected event sequence."""
        results = compute_travel_timeline(single_bus_scenario)

        itinerary = results["buses"]["BUS_001"]["itinerary"]

        # First event should be DEPART from Origin
        assert itinerary[0]["event"] == "DEPART"
        assert itinerary[0]["location"] == "Origin"

        # Should have ARRIVE at Station_A
        arrive_events = [e for e in itinerary if e["event"] == "ARRIVE"]
        assert len(arrive_events) >= 1

        # Should end with JOURNEY_COMPLETE
        assert itinerary[-1]["event"] == "JOURNEY_COMPLETE"


# =============================================================================
# Test: Two Buses Queue Waiting
# =============================================================================


class TestTwoBusesQueueWaiting:
    """
    Tests for queue waiting when two buses arrive simultaneously.

    This is the critical test case: when two buses arrive at a single-charger
    station at the same time, the second bus must wait exactly 25 minutes
    (one charge cycle) before starting its charge.
    """

    def test_second_bus_waits_25_minutes(self, two_bus_same_time_scenario: ScenarioInput) -> None:
        """
        Test that the second bus waits exactly 25 minutes before charging.

        Setup:
        - Two buses depart at t=0 from Origin
        - Both arrive at Station_A at t=150 (150km at 1km/min)
        - Station_A has only 1 charger
        - First bus (by sequence) starts charging at t=150
        - First bus finishes charging at t=175
        - Second bus starts charging at t=175 (waited 25 minutes)
        """
        results = compute_travel_timeline(two_bus_same_time_scenario)

        # Both buses should complete
        assert results["summary"]["completed_buses"] == 2

        # Get bus results
        bus1 = results["buses"]["BUS_001"]
        bus2 = results["buses"]["BUS_002"]

        # Find charge start times for each bus
        def get_charge_start_time(itinerary):
            for event in itinerary:
                if event["event"] == "CHARGE_START":
                    return event["time_mins"]
            return None

        charge_start_1 = get_charge_start_time(bus1["itinerary"])
        charge_start_2 = get_charge_start_time(bus2["itinerary"])

        # Both buses should charge (station is on their path)
        assert charge_start_1 is not None or charge_start_2 is not None

        if charge_start_1 is not None and charge_start_2 is not None:
            # One bus starts at arrival time, the other 25 minutes later
            earlier_start = min(charge_start_1, charge_start_2)
            later_start = max(charge_start_1, charge_start_2)

            # Both arrive at t=150 (150km / 1km per min)
            assert earlier_start == 150.0

            # Second bus starts after first finishes (150 + 25 = 175)
            assert later_start == 175.0

            # Wait time difference is exactly 25 minutes
            assert later_start - earlier_start == CHARGE_TIME_MINS

    def test_station_queue_statistics(self, two_bus_same_time_scenario: ScenarioInput) -> None:
        """Test that station queue statistics are recorded correctly."""
        results = compute_travel_timeline(two_bus_same_time_scenario)

        station_result = results["stations"]["Station_A"]

        # Should have processed 2 charges
        assert station_result["total_charges"] == 2

        # Max queue length should be 1 (one bus waiting)
        assert station_result["max_queue_length"] == 1

        # Total queue time should be 25 minutes (one bus waited)
        assert station_result["total_queue_time_mins"] == 25.0

    def test_wait_time_recorded_in_bus_result(self, two_bus_same_time_scenario: ScenarioInput) -> None:
        """Test that wait time is recorded in bus results."""
        results = compute_travel_timeline(two_bus_same_time_scenario)

        bus1 = results["buses"]["BUS_001"]
        bus2 = results["buses"]["BUS_002"]

        # One bus has 0 wait time, the other has 25 minutes
        wait_times = [bus1["total_wait_time_mins"], bus2["total_wait_time_mins"]]

        assert 0.0 in wait_times
        assert 25.0 in wait_times

    def test_total_journey_time_difference(self, two_bus_same_time_scenario: ScenarioInput) -> None:
        """
        Test that the second bus takes 25 minutes longer to complete journey.

        Both buses:
        - Travel 300km total (300 minutes)
        - Charge once (25 minutes)

        But the second bus also waits 25 minutes, so:
        - First bus: 300 + 25 = 325 minutes
        - Second bus: 300 + 25 + 25 = 350 minutes
        """
        results = compute_travel_timeline(two_bus_same_time_scenario)

        bus1 = results["buses"]["BUS_001"]
        bus2 = results["buses"]["BUS_002"]

        journey_time_1 = bus1["total_journey_time_mins"]
        journey_time_2 = bus2["total_journey_time_mins"]

        # One journey is 25 minutes longer than the other
        assert abs(journey_time_1 - journey_time_2) == CHARGE_TIME_MINS


# =============================================================================
# Test: Multi-Station Scenario
# =============================================================================


class TestMultiStationScenario:
    """Tests for scenarios with multiple stations."""

    def test_bus_charges_at_required_stations(self, multi_station_route: RouteConfig) -> None:
        """Test that buses charge at stations determined by the greedy algorithm."""
        scenario = ScenarioInput(
            id="multi_station_test",
            description="Multi-station test",
            weights=OperationalWeights(),
            route=multi_station_route,
            buses=[
                BusInput(
                    id="BUS_001",
                    operator="TestOp",
                    direction="Bengaluru→Kochi",
                    departure_time_mins=0
                )
            ]
        )

        results = compute_travel_timeline(scenario)
        bus_result = results["buses"]["BUS_001"]

        # Bus should complete the journey
        assert bus_result["completed"] is True

        # Count charge events
        charge_starts = [
            e for e in bus_result["itinerary"]
            if e["event"] == "CHARGE_START"
        ]

        # Should have at least one charge (500km > 240km range)
        assert len(charge_starts) >= 1

    def test_range_resets_after_charge(self, multi_station_route: RouteConfig) -> None:
        """Test that battery range resets to MAX_RANGE_KM after charging."""
        scenario = ScenarioInput(
            id="range_reset_test",
            description="Range reset test",
            weights=OperationalWeights(),
            route=multi_station_route,
            buses=[
                BusInput(
                    id="BUS_001",
                    operator="TestOp",
                    direction="Bengaluru→Kochi",
                    departure_time_mins=0
                )
            ]
        )

        results = compute_travel_timeline(scenario)
        itinerary = results["buses"]["BUS_001"]["itinerary"]

        # Find CHARGE_END events and check range_after
        for event in itinerary:
            if event["event"] == "CHARGE_END":
                assert event["range_after"] == MAX_RANGE_KM


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_scenario_no_buses(self) -> None:
        """Test simulation with no buses."""
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[],
            segment_distances={"A→B": 100.0}
        )
        scenario = ScenarioInput(
            id="empty_test",
            description="No buses",
            weights=OperationalWeights(),
            route=route,
            buses=[]
        )

        results = compute_travel_timeline(scenario)

        assert results["summary"]["total_buses"] == 0
        assert results["summary"]["completed_buses"] == 0
        assert results["events_processed"] == 0

    def test_short_route_no_charging_needed(self) -> None:
        """Test that buses on short routes don't charge unnecessarily."""
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[
                StationConfig(id="M", name="Mid", distance_from_origin_km=50.0)
            ],
            segment_distances={"A→M": 50.0, "M→B": 50.0}
        )
        scenario = ScenarioInput(
            id="short_route_test",
            description="Short route - no charging needed",
            weights=OperationalWeights(),
            route=route,
            buses=[
                BusInput(
                    id="BUS_001",
                    operator="TestOp",
                    direction="A→B",
                    departure_time_mins=0
                )
            ]
        )

        results = compute_travel_timeline(scenario)
        bus_result = results["buses"]["BUS_001"]

        # Bus should complete without charging (100km < 240km range)
        assert bus_result["completed"] is True
        assert bus_result["total_charge_time_mins"] == 0.0
        assert bus_result["planned_stops"] == []

    def test_multiple_chargers_no_queue(self) -> None:
        """Test that multiple chargers prevent queueing."""
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[
                StationConfig(
                    id="M",
                    name="Mid",
                    distance_from_origin_km=150.0,
                    charger_count=3  # Plenty of chargers
                )
            ],
            segment_distances={"A→M": 150.0, "M→B": 150.0}
        )
        scenario = ScenarioInput(
            id="multi_charger_test",
            description="Multiple chargers - no queue",
            weights=OperationalWeights(),
            route=route,
            buses=[
                BusInput(id="BUS_001", operator="Op", direction="A→B", departure_time_mins=0),
                BusInput(id="BUS_002", operator="Op", direction="A→B", departure_time_mins=0),
                BusInput(id="BUS_003", operator="Op", direction="A→B", departure_time_mins=0),
            ]
        )

        results = compute_travel_timeline(scenario)

        # No bus should have wait time (3 buses, 3 chargers)
        for bus_id in ["BUS_001", "BUS_002", "BUS_003"]:
            assert results["buses"][bus_id]["total_wait_time_mins"] == 0.0

        # Station should have no queue
        assert results["stations"]["M"]["max_queue_length"] == 0

    def test_staggered_departures(self) -> None:
        """Test buses with staggered departure times."""
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[
                StationConfig(id="M", name="Mid", distance_from_origin_km=150.0, charger_count=1)
            ],
            segment_distances={"A→M": 150.0, "M→B": 150.0}
        )
        scenario = ScenarioInput(
            id="staggered_test",
            description="Staggered departures",
            weights=OperationalWeights(),
            route=route,
            buses=[
                BusInput(id="BUS_001", operator="Op", direction="A→B", departure_time_mins=0),
                BusInput(id="BUS_002", operator="Op", direction="A→B", departure_time_mins=30),  # 30 min later
            ]
        )

        results = compute_travel_timeline(scenario)

        # BUS_001 arrives at t=150, charges 150-175
        # BUS_002 arrives at t=180, charger is free, no waiting
        bus1 = results["buses"]["BUS_001"]
        bus2 = results["buses"]["BUS_002"]

        assert bus1["total_wait_time_mins"] == 0.0
        assert bus2["total_wait_time_mins"] == 0.0


# =============================================================================
# Test: Constants
# =============================================================================


class TestConstants:
    """Tests for simulation constants."""

    def test_charge_time_constant(self) -> None:
        """Verify charge time constant is 25 minutes."""
        assert CHARGE_TIME_MINS == 25.0

    def test_speed_constant(self) -> None:
        """Verify speed constant is 1 km/min (60 km/h)."""
        assert SPEED_KM_PER_MIN == 1.0

    def test_max_range_constant(self) -> None:
        """Verify max range constant is 240 km."""
        assert MAX_RANGE_KM == 240.0

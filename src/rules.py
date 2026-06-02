"""
Pluggable Priority Rules for Queue Resolution

This module implements scoring functions for determining which bus should
be selected from a charging station queue. The scoring system uses a
weighted sum of three components:

1. Individual Score: Penalizes making any single bus wait too long
2. Operator Score: Groups buses from the same operator
3. Overall Score: Prioritizes buses with long remaining journeys

The scoring function is called by the simulation engine during CHARGE_END
events, replacing the simple FIFO queue behavior.

See ADR/0004_pluggable_priority_rules.md for architectural decisions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from src.engine import BusState, StationState
    from src.models import OperationalWeights
    from src.navigation import RouteManager


@dataclass
class BusScore:
    """
    Detailed score breakdown for a bus in the queue.

    Attributes:
        bus_id: Identifier of the bus.
        individual_score: Score based on wait time.
        operator_score: Score based on operator fleet grouping.
        overall_score: Score based on remaining journey distance.
        total_score: Sum of all component scores.
    """

    bus_id: str
    individual_score: float
    operator_score: float
    overall_score: float
    total_score: float

    @classmethod
    def compute(
        cls,
        bus_id: str,
        individual: float,
        operator: float,
        overall: float
    ) -> 'BusScore':
        """Create a BusScore with computed total."""
        return cls(
            bus_id=bus_id,
            individual_score=individual,
            operator_score=operator,
            overall_score=overall,
            total_score=individual + operator + overall
        )


class PriorityRule(ABC):
    """
    Abstract base class for queue priority rules.

    Subclasses implement specific strategies for selecting which bus
    should be charged next from a waiting queue.
    """

    @abstractmethod
    def select_next(
        self,
        queue: List['BusState'],
        current_time: float,
        stations_state: Dict[str, 'StationState'],
        weights: 'OperationalWeights',
        route_manager: 'RouteManager',
        bus_states: Dict[str, 'BusState']
    ) -> Optional['BusState']:
        """
        Select the next bus to charge from the queue.

        Args:
            queue: List of BusState objects waiting at this station.
            current_time: Current simulation time in minutes.
            stations_state: All station states (for cross-network calculations).
            weights: Operational weights for score components.
            route_manager: RouteManager for distance calculations.
            bus_states: All bus states (for operator counting).

        Returns:
            The BusState that should charge next, or None if queue is empty.
        """
        pass


class FIFORule(PriorityRule):
    """
    First-In-First-Out priority rule.

    The simplest strategy: buses are selected in arrival order.
    """

    def select_next(
        self,
        queue: List['BusState'],
        current_time: float,
        stations_state: Dict[str, 'StationState'],
        weights: 'OperationalWeights',
        route_manager: 'RouteManager',
        bus_states: Dict[str, 'BusState']
    ) -> Optional['BusState']:
        """Return the first bus in the queue."""
        if not queue:
            return None
        return queue[0]


class WeightedScoreRule(PriorityRule):
    """
    Weighted score priority rule using operational weights.

    Calculates a score for each bus in the queue based on:
    - Individual: Wait time penalty
    - Operator: Same-operator grouping bonus
    - Overall: Remaining distance priority

    The bus with the highest total score is selected.
    """

    def select_next(
        self,
        queue: List['BusState'],
        current_time: float,
        stations_state: Dict[str, 'StationState'],
        weights: 'OperationalWeights',
        route_manager: 'RouteManager',
        bus_states: Dict[str, 'BusState']
    ) -> Optional['BusState']:
        """Select the bus with the highest weighted score."""
        if not queue:
            return None

        if len(queue) == 1:
            return queue[0]

        # Calculate scores for all buses
        scores: List[Tuple['BusState', BusScore]] = []
        for bus in queue:
            score = self._calculate_score(
                bus, current_time, stations_state, weights,
                route_manager, bus_states
            )
            scores.append((bus, score))

        # Return bus with highest score (tie-breaker: queue order via enumerate)
        best_bus, _ = max(scores, key=lambda x: x[1].total_score)
        return best_bus

    def _calculate_score(
        self,
        bus: 'BusState',
        current_time: float,
        stations_state: Dict[str, 'StationState'],
        weights: 'OperationalWeights',
        route_manager: 'RouteManager',
        bus_states: Dict[str, 'BusState']
    ) -> BusScore:
        """
        Calculate the priority score for a bus.

        Args:
            bus: The bus to score.
            current_time: Current simulation time.
            stations_state: All station states.
            weights: Operational weights.
            route_manager: For distance calculations.
            bus_states: All bus states.

        Returns:
            BusScore with detailed breakdown.
        """
        # Individual Score: (current_time - arrival_time) * weights.individual
        # Penalizes making a single bus wait too long
        arrival_time = getattr(bus, 'queue_arrival_time', None)
        if arrival_time is None:
            arrival_time = current_time  # No wait if arrival time not set
        wait_time = max(0.0, current_time - arrival_time)
        individual_score = wait_time * weights.individual

        # Operator Score: (same_operator_count) * weights.operator
        # Helps group operator fleets
        same_operator_count = self._count_same_operator_waiting(
            bus.operator, stations_state, bus_states
        )
        operator_score = same_operator_count * weights.operator

        # Overall Score: (remaining_distance) * weights.overall
        # Prioritizes buses that still have a long way to go
        remaining_distance = self._calculate_remaining_distance(
            bus, route_manager
        )
        # Scale distance to make it comparable with time-based scores
        # Using remaining_distance directly (in km) as the score component
        # This means 100km remaining = 100 points * weights.overall
        overall_score = remaining_distance * weights.overall

        return BusScore.compute(
            bus_id=bus.bus_id,
            individual=individual_score,
            operator=operator_score,
            overall=overall_score
        )

    def _count_same_operator_waiting(
        self,
        operator: str,
        stations_state: Dict[str, 'StationState'],
        bus_states: Dict[str, 'BusState']
    ) -> int:
        """
        Count buses from the same operator waiting across all stations.

        Args:
            operator: Operator name to match.
            stations_state: All station states with queues.
            bus_states: All bus states for operator lookup.

        Returns:
            Number of same-operator buses in queues network-wide.
        """
        count = 0
        for station in stations_state.values():
            for bus_id in station.queue:
                if bus_id in bus_states:
                    if bus_states[bus_id].operator == operator:
                        count += 1
        return count

    def _calculate_remaining_distance(
        self,
        bus: 'BusState',
        route_manager: 'RouteManager'
    ) -> float:
        """
        Calculate remaining distance to destination for a bus.

        Args:
            bus: The bus to calculate for.
            route_manager: For distance calculations.

        Returns:
            Remaining distance in kilometers.
        """
        # Determine destination based on direction
        direction = bus.direction
        parts = direction.split('→')
        if len(parts) == 2:
            destination = parts[1].strip()
        else:
            destination = route_manager.destination

        current_location = bus.current_location

        try:
            return route_manager.get_segment_distance(
                current_location, destination
            )
        except ValueError:
            # If location not found, return 0
            return 0.0


def evaluate_queue(
    queue: List['BusState'],
    current_time: float,
    stations_state: Dict[str, 'StationState'],
    scenario_weights: 'OperationalWeights',
    route_manager: 'RouteManager',
    bus_states: Dict[str, 'BusState']
) -> Optional['BusState']:
    """
    Evaluate all buses in a queue and return the one with highest priority.

    This is the main entry point for queue resolution, called by the
    simulation engine during CHARGE_END events.

    The score is a weighted sum of three components:
    - Individual: (current_time - arrival_time) × weights.individual
      Heavily penalizes making a single bus wait too long.
    - Operator: (same_operator_waiting_count) × weights.operator
      Helps group operator fleets for coordination.
    - Overall: (remaining_distance_to_destination) × weights.overall
      Prioritizes buses that still have a long way to go.

    Args:
        queue: List of BusState objects waiting at the station.
        current_time: Current simulation time in minutes from midnight.
        stations_state: Dictionary mapping station IDs to StationState.
        scenario_weights: OperationalWeights from the scenario configuration.
        route_manager: RouteManager for distance calculations.
        bus_states: Dictionary mapping bus IDs to BusState.

    Returns:
        The BusState with the highest priority score, or None if queue is empty.

    Example:
        >>> # During CHARGE_END handling
        >>> next_bus = evaluate_queue(
        ...     queue=list(station_state.queue),
        ...     current_time=125.0,
        ...     stations_state=engine.station_states,
        ...     scenario_weights=scenario.weights,
        ...     route_manager=engine.route_manager,
        ...     bus_states=engine.bus_states
        ... )
        >>> if next_bus:
        ...     station_state.queue.remove(next_bus.bus_id)
        ...     # Schedule CHARGE_START for next_bus
    """
    rule = WeightedScoreRule()
    return rule.select_next(
        queue=queue,
        current_time=current_time,
        stations_state=stations_state,
        weights=scenario_weights,
        route_manager=route_manager,
        bus_states=bus_states
    )


def evaluate_queue_with_scores(
    queue: List['BusState'],
    current_time: float,
    stations_state: Dict[str, 'StationState'],
    scenario_weights: 'OperationalWeights',
    route_manager: 'RouteManager',
    bus_states: Dict[str, 'BusState']
) -> List[Tuple['BusState', BusScore]]:
    """
    Evaluate all buses and return full score breakdowns.

    Useful for debugging and understanding why a particular bus was selected.

    Args:
        queue: List of BusState objects waiting at the station.
        current_time: Current simulation time.
        stations_state: All station states.
        scenario_weights: Operational weights.
        route_manager: For distance calculations.
        bus_states: All bus states.

    Returns:
        List of (BusState, BusScore) tuples, sorted by descending score.
    """
    if not queue:
        return []

    rule = WeightedScoreRule()
    scores: List[Tuple['BusState', BusScore]] = []

    for bus in queue:
        score = rule._calculate_score(
            bus, current_time, stations_state, scenario_weights,
            route_manager, bus_states
        )
        scores.append((bus, score))

    # Sort by total score descending
    scores.sort(key=lambda x: x[1].total_score, reverse=True)
    return scores

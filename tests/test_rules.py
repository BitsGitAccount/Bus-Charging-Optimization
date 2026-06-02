"""
Unit Tests for Pluggable Priority Rules

This module contains comprehensive tests for the scoring functions
in src/rules.py, verifying that:
- Weight changes affect bus selection
- Individual, operator, and overall scores compute correctly
- Edge cases (queue of 1, empty queue) are handled gracefully

Run with: pytest tests/test_rules.py -v
"""

import pytest
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from src.models import OperationalWeights, RouteConfig, StationConfig
from src.navigation import RouteManager
from src.rules import (
    BusScore,
    WeightedScoreRule,
    evaluate_queue,
    evaluate_queue_with_scores,
)


# =============================================================================
# Mock Classes for Testing
# =============================================================================


@dataclass
class MockBusState:
    """Mock BusState for testing without full engine dependency."""

    bus_id: str
    operator: str
    direction: str
    current_location: str
    queue_arrival_time: Optional[float] = None
    departure_time_mins: int = 0
    remaining_range_km: float = 240.0
    itinerary: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MockStationState:
    """Mock StationState for testing."""

    station_id: str
    queue: deque = field(default_factory=deque)
    total_chargers: int = 2
    busy_chargers: int = 0


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def route_config() -> RouteConfig:
    """Create a route configuration for testing."""
    return RouteConfig(
        origin="Bengaluru",
        destination="Kochi",
        stations=[
            StationConfig(id="A", name="Station A", distance_from_origin_km=100.0),
            StationConfig(id="B", name="Station B", distance_from_origin_km=220.0),
            StationConfig(id="C", name="Station C", distance_from_origin_km=320.0),
            StationConfig(id="D", name="Station D", distance_from_origin_km=440.0),
        ],
        segment_distances={
            "Bengaluru→A": 100.0,
            "A→B": 120.0,
            "B→C": 100.0,
            "C→D": 120.0,
            "D→Kochi": 100.0
        }
    )


@pytest.fixture
def route_manager(route_config: RouteConfig) -> RouteManager:
    """Create a RouteManager for testing."""
    return RouteManager(route_config)


@pytest.fixture
def three_bus_queue() -> List[MockBusState]:
    """
    Create a queue of 3 buses with different characteristics.

    Bus 1: Long wait time, KSRTC operator, close to destination
    Bus 2: Short wait time, KPN operator, far from destination
    Bus 3: Medium wait time, KSRTC operator, medium distance
    """
    return [
        MockBusState(
            bus_id="BUS_1",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="D",  # 100km from Kochi
            queue_arrival_time=100.0,  # Arrived early, long wait
        ),
        MockBusState(
            bus_id="BUS_2",
            operator="KPN",
            direction="Bengaluru→Kochi",
            current_location="A",  # 440km from Kochi
            queue_arrival_time=140.0,  # Arrived recently
        ),
        MockBusState(
            bus_id="BUS_3",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",  # 320km from Kochi
            queue_arrival_time=120.0,  # Medium wait
        ),
    ]


@pytest.fixture
def stations_state(three_bus_queue: List[MockBusState]) -> Dict[str, MockStationState]:
    """Create station states with buses in queue."""
    # Put all 3 buses in Station B's queue
    station_b = MockStationState(station_id="B")
    for bus in three_bus_queue:
        station_b.queue.append(bus.bus_id)

    return {
        "A": MockStationState(station_id="A"),
        "B": station_b,
        "C": MockStationState(station_id="C"),
        "D": MockStationState(station_id="D"),
    }


@pytest.fixture
def bus_states(three_bus_queue: List[MockBusState]) -> Dict[str, MockBusState]:
    """Create bus states dict from queue."""
    return {bus.bus_id: bus for bus in three_bus_queue}


# =============================================================================
# Test: BusScore
# =============================================================================


class TestBusScore:
    """Tests for BusScore dataclass."""

    def test_compute_total_score(self) -> None:
        """Test that total_score is sum of components."""
        score = BusScore.compute(
            bus_id="TEST",
            individual=10.0,
            operator=5.0,
            overall=15.0
        )

        assert score.individual_score == 10.0
        assert score.operator_score == 5.0
        assert score.overall_score == 15.0
        assert score.total_score == 30.0

    def test_zero_components(self) -> None:
        """Test score with zero components."""
        score = BusScore.compute(
            bus_id="TEST",
            individual=0.0,
            operator=0.0,
            overall=0.0
        )

        assert score.total_score == 0.0


# =============================================================================
# Test: Weight Changes Affect Selection
# =============================================================================


class TestWeightChangesAffectSelection:
    """
    Tests verifying that altering weights changes which bus is selected.

    This is the critical test: different weight configurations should
    favor different buses from the same queue.
    """

    def test_high_individual_weight_favors_long_waiter(
        self,
        three_bus_queue: List[MockBusState],
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """
        High individual weight should favor the bus that has waited longest.

        BUS_1 arrived at t=100, BUS_2 at t=140, BUS_3 at t=120.
        With high individual weight, BUS_1 (longest wait) should be selected.
        """
        weights = OperationalWeights(
            individual=10.0,  # High - favor long waiters
            operator=0.1,
            overall=0.1
        )

        selected = evaluate_queue(
            queue=three_bus_queue,
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        assert selected is not None
        assert selected.bus_id == "BUS_1"  # Longest wait (50 mins)

    def test_high_overall_weight_favors_far_traveler(
        self,
        three_bus_queue: List[MockBusState],
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """
        High overall weight should favor the bus with longest remaining journey.

        BUS_1 at D (100km to go), BUS_2 at A (440km to go), BUS_3 at B (320km to go).
        With high overall weight, BUS_2 (farthest from destination) should be selected.
        """
        weights = OperationalWeights(
            individual=0.1,
            operator=0.1,
            overall=10.0  # High - favor long remaining distance
        )

        selected = evaluate_queue(
            queue=three_bus_queue,
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        assert selected is not None
        assert selected.bus_id == "BUS_2"  # Farthest to go (440km)

    def test_high_operator_weight_favors_grouped_fleet(
        self,
        three_bus_queue: List[MockBusState],
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """
        High operator weight should favor buses with more same-operator peers.

        BUS_1 and BUS_3 are KSRTC (2 in queue), BUS_2 is KPN (1 in queue).
        With high operator weight, KSRTC buses should be selected.
        """
        weights = OperationalWeights(
            individual=0.1,
            operator=100.0,  # Very high - favor operator grouping
            overall=0.1
        )

        selected = evaluate_queue(
            queue=three_bus_queue,
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        assert selected is not None
        # Should be a KSRTC bus (BUS_1 or BUS_3)
        assert selected.operator == "KSRTC"

    def test_balanced_weights_consider_all_factors(
        self,
        three_bus_queue: List[MockBusState],
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """
        Balanced weights should produce a weighted combination.
        """
        weights = OperationalWeights(
            individual=1.0,
            operator=1.0,
            overall=1.0
        )

        # Get all scores for analysis
        scores = evaluate_queue_with_scores(
            queue=three_bus_queue,
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        assert len(scores) == 3

        # All three components should contribute
        for _, score in scores:
            # With non-zero weights and valid data, all components should be >= 0
            assert score.individual_score >= 0
            assert score.operator_score >= 0
            assert score.overall_score >= 0


# =============================================================================
# Test: Score Calculation Details
# =============================================================================


class TestScoreCalculation:
    """Tests for individual score component calculations."""

    def test_individual_score_based_on_wait_time(
        self,
        route_manager: RouteManager
    ) -> None:
        """Individual score should be wait_time * weight."""
        bus = MockBusState(
            bus_id="TEST",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",
            queue_arrival_time=100.0
        )

        weights = OperationalWeights(individual=2.0, operator=0.0, overall=0.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,  # 50 minutes wait
            stations_state={},
            weights=weights,
            route_manager=route_manager,
            bus_states={}
        )

        # Wait time = 150 - 100 = 50 mins
        # Individual score = 50 * 2.0 = 100.0
        assert score.individual_score == 100.0

    def test_overall_score_based_on_remaining_distance(
        self,
        route_manager: RouteManager
    ) -> None:
        """Overall score should be remaining_distance * weight."""
        bus = MockBusState(
            bus_id="TEST",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",  # 320km from Kochi
            queue_arrival_time=100.0
        )

        weights = OperationalWeights(individual=0.0, operator=0.0, overall=1.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,
            stations_state={},
            weights=weights,
            route_manager=route_manager,
            bus_states={}
        )

        # B is at 220km, Kochi is at 540km
        # Remaining = 540 - 220 = 320km
        # Overall score = 320 * 1.0 = 320.0
        assert score.overall_score == 320.0

    def test_operator_score_counts_same_operator(
        self,
        route_manager: RouteManager
    ) -> None:
        """Operator score should count same-operator buses in all queues."""
        bus = MockBusState(
            bus_id="TEST",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",
            queue_arrival_time=100.0
        )

        # Create station with 3 KSRTC buses and 1 KPN bus in queues
        bus_states = {
            "BUS_A": MockBusState(bus_id="BUS_A", operator="KSRTC", direction="Bengaluru→Kochi", current_location="A"),
            "BUS_B": MockBusState(bus_id="BUS_B", operator="KSRTC", direction="Bengaluru→Kochi", current_location="A"),
            "BUS_C": MockBusState(bus_id="BUS_C", operator="KSRTC", direction="Bengaluru→Kochi", current_location="B"),
            "BUS_D": MockBusState(bus_id="BUS_D", operator="KPN", direction="Bengaluru→Kochi", current_location="B"),
        }

        station_a = MockStationState(station_id="A")
        station_a.queue.extend(["BUS_A", "BUS_B"])

        station_b = MockStationState(station_id="B")
        station_b.queue.extend(["BUS_C", "BUS_D"])

        stations_state = {"A": station_a, "B": station_b}

        weights = OperationalWeights(individual=0.0, operator=5.0, overall=0.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,
            stations_state=stations_state,
            weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        # 3 KSRTC buses in queues (BUS_A, BUS_B, BUS_C)
        # Operator score = 3 * 5.0 = 15.0
        assert score.operator_score == 15.0


# =============================================================================
# Test: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_queue_returns_none(
        self,
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """Empty queue should return None."""
        weights = OperationalWeights()

        selected = evaluate_queue(
            queue=[],
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        assert selected is None

    def test_queue_of_one_returns_that_bus(
        self,
        stations_state: Dict[str, MockStationState],
        route_manager: RouteManager
    ) -> None:
        """Queue with single bus should return that bus."""
        single_bus = MockBusState(
            bus_id="ONLY_BUS",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",
            queue_arrival_time=100.0
        )

        weights = OperationalWeights()

        selected = evaluate_queue(
            queue=[single_bus],
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states={"ONLY_BUS": single_bus}
        )

        assert selected is not None
        assert selected.bus_id == "ONLY_BUS"

    def test_zero_weights_produce_zero_scores(
        self,
        three_bus_queue: List[MockBusState],
        stations_state: Dict[str, MockStationState],
        bus_states: Dict[str, MockBusState],
        route_manager: RouteManager
    ) -> None:
        """Zero weights should produce zero scores (FIFO-like behavior)."""
        weights = OperationalWeights(
            individual=0.0,
            operator=0.0,
            overall=0.0
        )

        scores = evaluate_queue_with_scores(
            queue=three_bus_queue,
            current_time=150.0,
            stations_state=stations_state,
            scenario_weights=weights,
            route_manager=route_manager,
            bus_states=bus_states
        )

        # All scores should be 0
        for _, score in scores:
            assert score.total_score == 0.0

    def test_missing_queue_arrival_time_uses_current_time(
        self,
        stations_state: Dict[str, MockStationState],
        route_manager: RouteManager
    ) -> None:
        """Bus without queue_arrival_time should use current_time (0 wait)."""
        bus = MockBusState(
            bus_id="NO_ARRIVAL_TIME",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="B",
            queue_arrival_time=None  # Not set
        )

        weights = OperationalWeights(individual=1.0, operator=0.0, overall=0.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,
            stations_state={},
            weights=weights,
            route_manager=route_manager,
            bus_states={}
        )

        # With no queue_arrival_time, wait_time = 0
        assert score.individual_score == 0.0

    def test_unknown_location_returns_zero_distance(
        self,
        route_manager: RouteManager
    ) -> None:
        """Bus at unknown location should get 0 remaining distance."""
        bus = MockBusState(
            bus_id="LOST_BUS",
            operator="KSRTC",
            direction="Bengaluru→Kochi",
            current_location="UNKNOWN",  # Invalid location
            queue_arrival_time=100.0
        )

        weights = OperationalWeights(individual=0.0, operator=0.0, overall=1.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,
            stations_state={},
            weights=weights,
            route_manager=route_manager,
            bus_states={}
        )

        # Unknown location → 0 remaining distance → 0 overall score
        assert score.overall_score == 0.0


# =============================================================================
# Test: Reverse Direction
# =============================================================================


class TestReverseDirection:
    """Tests for buses traveling in the reverse direction."""

    def test_reverse_direction_remaining_distance(
        self,
        route_manager: RouteManager
    ) -> None:
        """Bus going Kochi→Bengaluru should calculate distance to Bengaluru."""
        bus = MockBusState(
            bus_id="REVERSE_BUS",
            operator="KSRTC",
            direction="Kochi→Bengaluru",
            current_location="C",  # 320km from Bengaluru
            queue_arrival_time=100.0
        )

        weights = OperationalWeights(individual=0.0, operator=0.0, overall=1.0)

        rule = WeightedScoreRule()
        score = rule._calculate_score(
            bus=bus,
            current_time=150.0,
            stations_state={},
            weights=weights,
            route_manager=route_manager,
            bus_states={}
        )

        # C is at 320km from Bengaluru (origin)
        # Remaining to Bengaluru = 320km
        assert score.overall_score == 320.0

"""
Unit Tests for Route Navigation Module

This module contains comprehensive tests for the RouteManager class,
verifying correct behavior for:
- Direction-based station ordering
- Segment distance calculations
- Charge plan validation against range constraints
- Edge cases and error handling

Run with: pytest tests/test_navigation.py -v
"""

import pytest

from src.models import RouteConfig, StationConfig
from src.navigation import (
    DISTANCE_EPSILON,
    MAX_RANGE_KM,
    RouteManager,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_route() -> RouteConfig:
    """
    Create a sample route configuration for testing.

    Route layout (Bengaluru → Kochi):
        Bengaluru (0km) → A (100km) → B (200km) → C (350km) → D (450km) → Kochi (500km)

    Segment distances:
        Bengaluru→A: 100km
        A→B: 100km
        B→C: 150km
        C→D: 100km
        D→Kochi: 50km
    """
    return RouteConfig(
        origin="Bengaluru",
        destination="Kochi",
        stations=[
            StationConfig(id="A", name="Station A", distance_from_origin_km=100.0, charger_count=2),
            StationConfig(id="B", name="Station B", distance_from_origin_km=200.0, charger_count=3),
            StationConfig(id="C", name="Station C", distance_from_origin_km=350.0, charger_count=2),
            StationConfig(id="D", name="Station D", distance_from_origin_km=450.0, charger_count=1),
        ],
        segment_distances={
            "Bengaluru→A": 100.0,
            "A→B": 100.0,
            "B→C": 150.0,
            "C→D": 100.0,
            "D→Kochi": 50.0,
        }
    )


@pytest.fixture
def manager(sample_route: RouteConfig) -> RouteManager:
    """Create a RouteManager with the sample route."""
    return RouteManager(sample_route)


@pytest.fixture
def short_range_manager(sample_route: RouteConfig) -> RouteManager:
    """Create a RouteManager with a reduced range (150km) for testing edge cases."""
    return RouteManager(sample_route, max_range_km=150.0)


@pytest.fixture
def empty_route() -> RouteConfig:
    """Create a route with no intermediate stations."""
    return RouteConfig(
        origin="CityX",
        destination="CityY",
        stations=[],
        segment_distances={"CityX→CityY": 200.0}
    )


# =============================================================================
# Test: RouteManager Initialization
# =============================================================================


class TestRouteManagerInit:
    """Tests for RouteManager initialization."""

    def test_init_with_valid_route(self, sample_route: RouteConfig) -> None:
        """Test that RouteManager initializes correctly with a valid route."""
        manager = RouteManager(sample_route)

        assert manager.origin == "Bengaluru"
        assert manager.destination == "Kochi"
        assert manager.max_range_km == MAX_RANGE_KM

    def test_init_with_custom_range(self, sample_route: RouteConfig) -> None:
        """Test that custom max_range_km is applied."""
        manager = RouteManager(sample_route, max_range_km=300.0)

        assert manager.max_range_km == 300.0

    def test_init_with_invalid_range_raises_error(self, sample_route: RouteConfig) -> None:
        """Test that non-positive max_range_km raises ValueError."""
        with pytest.raises(ValueError, match="must be positive"):
            RouteManager(sample_route, max_range_km=0.0)

        with pytest.raises(ValueError, match="must be positive"):
            RouteManager(sample_route, max_range_km=-100.0)

    def test_total_distance(self, manager: RouteManager) -> None:
        """Test that total_distance is computed correctly."""
        assert manager.total_distance == 500.0

    def test_repr(self, manager: RouteManager) -> None:
        """Test the string representation."""
        repr_str = repr(manager)

        assert "Bengaluru" in repr_str
        assert "Kochi" in repr_str
        assert "stations=4" in repr_str


# =============================================================================
# Test: get_ordered_stations
# =============================================================================


class TestGetOrderedStations:
    """Tests for direction-based station ordering."""

    def test_forward_direction_returns_ascending_order(self, manager: RouteManager) -> None:
        """Test that forward direction returns stations A→B→C→D."""
        stations = manager.get_ordered_stations("Bengaluru→Kochi")
        station_ids = [s.id for s in stations]

        assert station_ids == ["A", "B", "C", "D"]

    def test_reverse_direction_returns_descending_order(self, manager: RouteManager) -> None:
        """Test that reverse direction returns stations D→C→B→A."""
        stations = manager.get_ordered_stations("Kochi→Bengaluru")
        station_ids = [s.id for s in stations]

        assert station_ids == ["D", "C", "B", "A"]

    def test_forward_preserves_station_data(self, manager: RouteManager) -> None:
        """Test that station objects retain their full data."""
        stations = manager.get_ordered_stations("Bengaluru→Kochi")

        assert stations[0].name == "Station A"
        assert stations[0].distance_from_origin_km == 100.0
        assert stations[0].charger_count == 2

    def test_reverse_preserves_station_data(self, manager: RouteManager) -> None:
        """Test that reversed stations retain their full data."""
        stations = manager.get_ordered_stations("Kochi→Bengaluru")

        # First station in reverse is D
        assert stations[0].id == "D"
        assert stations[0].distance_from_origin_km == 450.0

    def test_invalid_direction_raises_error(self, manager: RouteManager) -> None:
        """Test that invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            manager.get_ordered_stations("Mumbai→Delhi")

    def test_empty_stations_returns_empty_list(self, empty_route: RouteConfig) -> None:
        """Test that a route with no stations returns an empty list."""
        manager = RouteManager(empty_route)

        assert manager.get_ordered_stations("CityX→CityY") == []
        assert manager.get_ordered_stations("CityY→CityX") == []

    def test_unsorted_input_is_sorted_correctly(self) -> None:
        """Test that stations are sorted even if input is unordered."""
        route = RouteConfig(
            origin="Start",
            destination="End",
            stations=[
                StationConfig(id="C", name="C", distance_from_origin_km=300.0),
                StationConfig(id="A", name="A", distance_from_origin_km=100.0),
                StationConfig(id="B", name="B", distance_from_origin_km=200.0),
            ],
            segment_distances={"Start→End": 400.0}
        )
        manager = RouteManager(route)

        forward = [s.id for s in manager.get_ordered_stations("Start→End")]
        reverse = [s.id for s in manager.get_ordered_stations("End→Start")]

        assert forward == ["A", "B", "C"]
        assert reverse == ["C", "B", "A"]


# =============================================================================
# Test: get_segment_distance
# =============================================================================


class TestGetSegmentDistance:
    """Tests for segment distance calculations."""

    def test_origin_to_first_station(self, manager: RouteManager) -> None:
        """Test distance from origin to first station."""
        distance = manager.get_segment_distance("Bengaluru", "A")
        assert distance == 100.0

    def test_adjacent_stations(self, manager: RouteManager) -> None:
        """Test distance between adjacent stations."""
        assert manager.get_segment_distance("A", "B") == 100.0
        assert manager.get_segment_distance("B", "C") == 150.0
        assert manager.get_segment_distance("C", "D") == 100.0

    def test_last_station_to_destination(self, manager: RouteManager) -> None:
        """Test distance from last station to destination."""
        distance = manager.get_segment_distance("D", "Kochi")
        assert distance == 50.0

    def test_origin_to_destination(self, manager: RouteManager) -> None:
        """Test total distance from origin to destination."""
        distance = manager.get_segment_distance("Bengaluru", "Kochi")
        assert distance == 500.0

    def test_non_adjacent_stations(self, manager: RouteManager) -> None:
        """Test distance between non-adjacent stations."""
        # A (100km) to C (350km) = 250km
        distance = manager.get_segment_distance("A", "C")
        assert distance == 250.0

    def test_distance_is_symmetric(self, manager: RouteManager) -> None:
        """Test that distance is the same regardless of order (absolute value)."""
        assert manager.get_segment_distance("A", "B") == manager.get_segment_distance("B", "A")
        assert manager.get_segment_distance("Bengaluru", "C") == manager.get_segment_distance("C", "Bengaluru")

    def test_same_node_returns_zero(self, manager: RouteManager) -> None:
        """Test that distance from a node to itself is zero."""
        assert manager.get_segment_distance("A", "A") == 0.0
        assert manager.get_segment_distance("Bengaluru", "Bengaluru") == 0.0

    def test_unknown_start_node_raises_error(self, manager: RouteManager) -> None:
        """Test that unknown start node raises ValueError."""
        with pytest.raises(ValueError, match="Unknown node 'Unknown'"):
            manager.get_segment_distance("Unknown", "A")

    def test_unknown_end_node_raises_error(self, manager: RouteManager) -> None:
        """Test that unknown end node raises ValueError."""
        with pytest.raises(ValueError, match="Unknown node 'Nowhere'"):
            manager.get_segment_distance("A", "Nowhere")


# =============================================================================
# Test: validate_charge_plan
# =============================================================================


class TestValidateChargePlan:
    """Tests for charge plan validation."""

    def test_valid_plan_with_sufficient_stops(self, manager: RouteManager) -> None:
        """
        Test that a valid plan with well-spaced stops returns True.

        Route: Bengaluru (0) → A (100) → B (200) → C (350) → D (450) → Kochi (500)
        Max range: 240km

        Plan: Stop at B and D
        - Bengaluru→B: 200km ✓
        - B→D: 250km > 240km ✗

        This should actually FAIL. Let's use B and C instead:
        - Bengaluru→B: 200km ✓
        - B→C: 150km ✓
        - C→Kochi: 150km ✓
        """
        # Valid plan: B, C, D covers the route within range
        valid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=["B", "C"]
        )
        assert valid is True

    def test_valid_plan_with_all_stations(self, manager: RouteManager) -> None:
        """Test that stopping at all stations is always valid (if segments are within range)."""
        valid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=["A", "B", "C", "D"]
        )
        assert valid is True

    def test_invalid_plan_skip_too_many_stations(self, manager: RouteManager) -> None:
        """
        Test that skipping stations beyond range returns False.

        Trying to go from Bengaluru directly to D (450km) > 240km range.
        """
        invalid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=["D"]  # Bengaluru→D = 450km > 240km
        )
        assert invalid is False

    def test_invalid_plan_no_stations(self, manager: RouteManager) -> None:
        """
        Test that no charging stations fails if route exceeds range.

        Bengaluru→Kochi = 500km > 240km
        """
        invalid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=[]
        )
        assert invalid is False

    def test_valid_plan_reverse_direction(self, manager: RouteManager) -> None:
        """
        Test charge plan validation for reverse direction.

        Route (reverse): Kochi (0) → D (50) → C (150) → B (300) → A (400) → Bengaluru (500)
        In terms of distance_from_origin:
        - Kochi is at 500km (destination in forward)
        - D is at 450km
        - Distance Kochi→D = |500 - 450| = 50km ✓

        Valid plan: D, B (reverse order in physical terms)
        Physical traversal: Kochi → D → B → Bengaluru
        - Kochi→D: 50km ✓
        - D→B: 250km > 240km ✗

        Better plan: D, C, B
        - Kochi→D: 50km ✓
        - D→C: 100km ✓
        - C→B: 150km ✓
        - B→Bengaluru: 200km ✓
        """
        valid = manager.validate_charge_plan(
            direction="Kochi→Bengaluru",
            departure_time_mins=600,
            scheduled_stations=["D", "C", "B"]
        )
        assert valid is True

    def test_invalid_plan_reverse_direction_skip_stations(self, manager: RouteManager) -> None:
        """Test invalid plan in reverse direction."""
        # Kochi→A directly: 400km > 240km
        invalid = manager.validate_charge_plan(
            direction="Kochi→Bengaluru",
            departure_time_mins=600,
            scheduled_stations=["A"]
        )
        assert invalid is False

    def test_plan_at_exact_range_boundary(self) -> None:
        """
        Test that a plan at exactly the maximum range is valid.

        Create a route where a segment is exactly 240km.
        """
        route = RouteConfig(
            origin="Start",
            destination="End",
            stations=[
                StationConfig(id="Mid", name="Mid", distance_from_origin_km=240.0),
            ],
            segment_distances={"Start→Mid": 240.0, "Mid→End": 100.0}
        )
        manager = RouteManager(route, max_range_km=240.0)

        # Start→Mid is exactly 240km
        valid = manager.validate_charge_plan(
            direction="Start→End",
            departure_time_mins=0,
            scheduled_stations=["Mid"]
        )
        assert valid is True

    def test_plan_just_over_range_boundary(self) -> None:
        """
        Test that a plan just over the range boundary is invalid.

        Create a route where a segment is 240.01km (exceeds 240km + epsilon).
        """
        route = RouteConfig(
            origin="Start",
            destination="End",
            stations=[
                StationConfig(id="Mid", name="Mid", distance_from_origin_km=240.1),
            ],
            segment_distances={"Start→Mid": 240.1, "Mid→End": 100.0}
        )
        manager = RouteManager(route, max_range_km=240.0)

        # Start→Mid is 240.1km > 240km
        invalid = manager.validate_charge_plan(
            direction="Start→End",
            departure_time_mins=0,
            scheduled_stations=["Mid"]
        )
        assert invalid is False

    def test_unknown_station_in_plan_raises_error(self, manager: RouteManager) -> None:
        """Test that unknown station ID raises ValueError."""
        with pytest.raises(ValueError, match="Unknown station 'Z'"):
            manager.validate_charge_plan(
                direction="Bengaluru→Kochi",
                departure_time_mins=600,
                scheduled_stations=["A", "Z", "D"]
            )

    def test_stations_in_wrong_order_are_sorted(self, manager: RouteManager) -> None:
        """
        Test that stations provided in wrong order are correctly sorted.

        Plan: ["D", "B"] should be treated as B→D for forward direction.
        - Bengaluru→B: 200km ✓
        - B→D: 250km > 240km ✗

        This should fail because B→D exceeds range.
        """
        invalid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=["D", "B"]  # Wrong order, will be sorted to [B, D]
        )
        assert invalid is False  # B→D = 250km > 240km

    def test_valid_plan_with_single_station(self, short_range_manager: RouteManager) -> None:
        """
        Test with shorter range (150km).

        Route: Bengaluru (0) → A (100) → B (200) → C (350) → D (450) → Kochi (500)
        Max range: 150km

        Valid single-hop plan from Bengaluru: only A is reachable (100km < 150km)
        B is at 200km > 150km, so can't reach B directly.

        Full valid plan: A, B, C, D
        - Bengaluru→A: 100km ✓
        - A→B: 100km ✓
        - B→C: 150km ✓ (exactly at limit)
        - C→D: 100km ✓
        - D→Kochi: 50km ✓
        """
        valid = short_range_manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=600,
            scheduled_stations=["A", "B", "C", "D"]
        )
        assert valid is True

    def test_empty_route_no_stations_needed(self) -> None:
        """Test that a short route needs no charging stations."""
        route = RouteConfig(
            origin="Near",
            destination="Far",
            stations=[],
            segment_distances={"Near→Far": 100.0}
        )
        manager = RouteManager(route, max_range_km=240.0)

        # Route is 100km, well within 240km range
        valid = manager.validate_charge_plan(
            direction="Near→Far",
            departure_time_mins=0,
            scheduled_stations=[]
        )
        assert valid is True


# =============================================================================
# Test: Floating-Point Precision
# =============================================================================


class TestFloatingPointPrecision:
    """Tests for floating-point precision handling."""

    def test_epsilon_is_configured(self) -> None:
        """Test that DISTANCE_EPSILON is defined and reasonable."""
        assert DISTANCE_EPSILON > 0
        assert DISTANCE_EPSILON < 1e-6  # Should be small

    def test_distance_at_boundary_with_epsilon(self) -> None:
        """
        Test that distances within epsilon of boundary are handled correctly.

        A distance of 240.0 + 1e-10 should still be considered valid
        (within epsilon tolerance).
        """
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[
                # Distance exactly at 240 + tiny amount within epsilon
                StationConfig(id="M", name="M", distance_from_origin_km=240.0 + 1e-12),
            ],
            segment_distances={"A→B": 300.0}
        )
        manager = RouteManager(route, max_range_km=240.0)

        # The station is at 240.0 + 1e-12, which is within epsilon of 240.0
        valid = manager.validate_charge_plan(
            direction="A→B",
            departure_time_mins=0,
            scheduled_stations=["M"]
        )
        # 240.0 + 1e-12 should NOT exceed 240.0 + epsilon (1e-9)
        assert valid is True


# =============================================================================
# Test: Terrain and Weather Modifiers (Future Hooks)
# =============================================================================


class TestModifierHooks:
    """Tests for terrain and weather modifier hooks."""

    def test_set_terrain_modifier(self, manager: RouteManager) -> None:
        """Test that terrain modifiers can be set."""
        manager.set_terrain_modifier("A→B", 1.5)

        # Effective distance should now be 1.5x
        base = manager.get_segment_distance("A", "B")
        effective = manager.get_effective_distance("A", "B")

        assert base == 100.0
        assert effective == 150.0

    def test_terrain_modifier_invalid_factor(self, manager: RouteManager) -> None:
        """Test that non-positive terrain modifier raises error."""
        with pytest.raises(ValueError, match="must be positive"):
            manager.set_terrain_modifier("A→B", 0.0)

        with pytest.raises(ValueError, match="must be positive"):
            manager.set_terrain_modifier("A→B", -1.0)

    def test_set_weather_modifier(self, manager: RouteManager) -> None:
        """Test that weather modifiers can be set."""
        manager.set_weather_modifier(hour=18, factor=1.2)

        # Effective distance at hour 18 should be 1.2x
        effective = manager.get_effective_distance("A", "B", time_mins=18 * 60)

        assert effective == 120.0  # 100 * 1.2

    def test_weather_modifier_invalid_hour(self, manager: RouteManager) -> None:
        """Test that invalid hour raises error."""
        with pytest.raises(ValueError, match="Hour must be 0-23"):
            manager.set_weather_modifier(hour=24, factor=1.1)

    def test_weather_modifier_invalid_factor(self, manager: RouteManager) -> None:
        """Test that non-positive weather modifier raises error."""
        with pytest.raises(ValueError, match="must be positive"):
            manager.set_weather_modifier(hour=12, factor=0.0)

    def test_combined_modifiers(self, manager: RouteManager) -> None:
        """Test terrain and weather modifiers combined."""
        manager.set_terrain_modifier("A→B", 1.5)
        manager.set_weather_modifier(hour=18, factor=1.2)

        # Base: 100km, Terrain: 1.5x, Weather: 1.2x
        # Effective: 100 * 1.5 * 1.2 = 180km
        effective = manager.get_effective_distance("A", "B", time_mins=18 * 60)

        assert effective == pytest.approx(180.0)


# =============================================================================
# Test: get_required_stations
# =============================================================================


class TestGetRequiredStations:
    """Tests for the get_required_stations helper method."""

    def test_no_stations_needed_for_short_route(self) -> None:
        """Test that short routes need no stations."""
        route = RouteConfig(
            origin="A",
            destination="B",
            stations=[
                StationConfig(id="M", name="M", distance_from_origin_km=100.0),
            ],
            segment_distances={"A→B": 200.0}
        )
        manager = RouteManager(route, max_range_km=240.0)

        required = manager.get_required_stations("A→B")
        assert required == []  # 200km < 240km, no charging needed

    def test_greedy_selection_forward(self, manager: RouteManager) -> None:
        """Test that greedy algorithm selects furthest reachable stations."""
        # With 240km range:
        # Start at Bengaluru (0km)
        # Can reach up to 240km: A (100), B (200) reachable, C (350) not
        # Select B (furthest reachable)
        # From B (200km), can reach up to 440km: C (350), D (450) not quite
        # Select C
        # From C (350km), can reach D (450) and Kochi (500) both within 240km
        # Select the furthest that still allows reaching destination

        required = manager.get_required_stations("Bengaluru→Kochi")

        # Validate the plan
        valid = manager.validate_charge_plan(
            direction="Bengaluru→Kochi",
            departure_time_mins=0,
            scheduled_stations=required
        )
        assert valid is True

    def test_greedy_selection_reverse(self, manager: RouteManager) -> None:
        """Test greedy selection in reverse direction."""
        required = manager.get_required_stations("Kochi→Bengaluru")

        valid = manager.validate_charge_plan(
            direction="Kochi→Bengaluru",
            departure_time_mins=0,
            scheduled_stations=required
        )
        assert valid is True

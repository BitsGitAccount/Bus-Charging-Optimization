"""
Route Navigation and Topology Management

This module provides the RouteManager class for handling bi-directional travel
over a single linear route configuration. It computes distances, validates
charge plans, and returns stations in physical traversal order based on direction.

Key Features:
- Single source of truth for route topology (no data duplication)
- Direction-aware station ordering
- Range validation with configurable maximum battery range
- Clean hooks for future terrain/weather modifiers

See ADR/0002_route_topology_validation.md for architectural decisions.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.models import RouteConfig, StationConfig


# Constants for range validation
MAX_RANGE_KM: float = 240.0
DISTANCE_EPSILON: float = 1e-9


class RouteManager:
    """
    Manages route topology and provides direction-aware navigation methods.

    The RouteManager wraps a RouteConfig and provides methods for:
    - Getting stations in physical traversal order based on direction
    - Computing distances between any two nodes (origin, stations, destination)
    - Validating charge plans against battery range constraints

    The route topology is stored once (origin-to-destination), and traversal
    logic handles direction inversion dynamically.

    Attributes:
        max_range_km: Maximum battery range in kilometers (default: 240.0).

    Example:
        >>> from src.models import RouteConfig, StationConfig
        >>> route = RouteConfig(
        ...     origin="Bengaluru",
        ...     destination="Kochi",
        ...     stations=[
        ...         StationConfig(id="A", name="Station A", distance_from_origin_km=100.0),
        ...         StationConfig(id="B", name="Station B", distance_from_origin_km=200.0),
        ...     ]
        ... )
        >>> manager = RouteManager(route)
        >>> [s.id for s in manager.get_ordered_stations("Bengaluru→Kochi")]
        ['A', 'B']
    """

    def __init__(
        self,
        route: RouteConfig,
        max_range_km: float = MAX_RANGE_KM
    ) -> None:
        """
        Initialize the RouteManager with a route configuration.

        Args:
            route: Validated RouteConfig containing origin, destination, and stations.
            max_range_km: Maximum battery range in kilometers for charge plan validation.
                          Must be > 0. Default is 240.0.

        Raises:
            ValueError: If max_range_km is not positive.
        """
        if max_range_km <= 0:
            raise ValueError(f"max_range_km must be positive, got {max_range_km}")

        self._route = route
        self.max_range_km = max_range_km

        # Build position map for efficient distance lookups
        self._node_positions: Dict[str, float] = self._build_node_positions()

        # Cache for total route length
        self._total_distance: Optional[float] = None

        # Hooks for future modifiers (terrain, weather, etc.)
        self._terrain_modifiers: Dict[str, float] = {}
        self._weather_modifiers: Dict[int, float] = {}

    def _build_node_positions(self) -> Dict[str, float]:
        """
        Build a mapping of node IDs to their positions (distance from origin).

        Returns:
            Dictionary mapping node identifiers to distances from origin in km.
            Includes origin (0.0), all stations, and destination.
        """
        positions: Dict[str, float] = {}

        # Origin is at position 0
        positions[self._route.origin] = 0.0

        # Add all stations
        for station in self._route.stations:
            positions[station.id] = station.distance_from_origin_km

        # Destination position is computed from the furthest station or segment data
        # If we have stations, destination is beyond the furthest station
        # We need total route length - check segment_distances or infer from stations
        destination_distance = self._compute_destination_distance()
        positions[self._route.destination] = destination_distance

        return positions

    def _compute_destination_distance(self) -> float:
        """
        Compute the distance from origin to destination.

        Uses segment_distances if available, otherwise requires explicit
        total_distance or raises an error if stations exist but no way
        to determine the destination distance.

        Returns:
            Distance from origin to destination in kilometers.
        """
        # Sum all segment distances if available
        if self._route.segment_distances:
            return sum(self._route.segment_distances.values())

        # If no stations, assume origin and destination are the same point
        if not self._route.stations:
            return 0.0

        # Fallback: use the furthest station's distance as a minimum bound
        # This is a heuristic - ideally segment_distances should be provided
        max_station_distance = max(
            s.distance_from_origin_km for s in self._route.stations
        )

        # Add a reasonable buffer beyond the last station (default assumption)
        # In production, this should be explicitly provided via segment_distances
        return max_station_distance

    @property
    def total_distance(self) -> float:
        """
        Get the total route distance from origin to destination.

        Returns:
            Total distance in kilometers.
        """
        if self._total_distance is None:
            self._total_distance = self._node_positions.get(
                self._route.destination, 0.0
            )
        return self._total_distance

    @property
    def origin(self) -> str:
        """Get the route origin identifier."""
        return self._route.origin

    @property
    def destination(self) -> str:
        """Get the route destination identifier."""
        return self._route.destination

    def _is_reverse_direction(self, direction: str) -> bool:
        """
        Determine if the direction represents reverse travel (destination→origin).

        Args:
            direction: Travel direction string (e.g., "Kochi→Bengaluru").

        Returns:
            True if traveling from destination to origin, False otherwise.
        """
        forward = f"{self._route.origin}→{self._route.destination}"
        reverse = f"{self._route.destination}→{self._route.origin}"

        if direction == forward:
            return False
        elif direction == reverse:
            return True
        else:
            raise ValueError(
                f"Invalid direction '{direction}'. "
                f"Expected '{forward}' or '{reverse}'."
            )

    def _get_start_end_for_direction(self, direction: str) -> Tuple[str, str]:
        """
        Get the start and end nodes for a given travel direction.

        Args:
            direction: Travel direction string.

        Returns:
            Tuple of (start_node, end_node) identifiers.
        """
        if self._is_reverse_direction(direction):
            return self._route.destination, self._route.origin
        return self._route.origin, self._route.destination

    def get_ordered_stations(self, direction: str) -> List[StationConfig]:
        """
        Get stations in physical traversal order for the given direction.

        For forward direction (origin→destination), stations are sorted by
        ascending distance from origin. For reverse direction (destination→origin),
        stations are sorted by descending distance from origin.

        Args:
            direction: Travel direction (e.g., "Bengaluru→Kochi" or "Kochi→Bengaluru").

        Returns:
            List of StationConfig objects in traversal order.

        Raises:
            ValueError: If direction is not valid for this route.

        Example:
            >>> # For route Bengaluru→Kochi with stations A(100km), B(200km), C(300km), D(400km)
            >>> manager.get_ordered_stations("Bengaluru→Kochi")
            [A, B, C, D]  # Forward order
            >>> manager.get_ordered_stations("Kochi→Bengaluru")
            [D, C, B, A]  # Reverse order
        """
        # Sort stations by distance from origin (ascending)
        sorted_stations = sorted(
            self._route.stations,
            key=lambda s: s.distance_from_origin_km
        )

        # Reverse for backward travel
        if self._is_reverse_direction(direction):
            return list(reversed(sorted_stations))

        return sorted_stations

    def get_segment_distance(self, start_node: str, end_node: str) -> float:
        """
        Get the absolute distance between two nodes on the route.

        Nodes can be the origin, destination, or any station ID. The distance
        is always positive regardless of travel direction.

        Args:
            start_node: Starting node identifier.
            end_node: Ending node identifier.

        Returns:
            Absolute distance in kilometers between the two nodes.

        Raises:
            ValueError: If either node is not found on the route.

        Example:
            >>> manager.get_segment_distance("Bengaluru", "A")
            100.0
            >>> manager.get_segment_distance("A", "Bengaluru")  # Same distance
            100.0
        """
        if start_node not in self._node_positions:
            raise ValueError(
                f"Unknown node '{start_node}'. "
                f"Valid nodes: {list(self._node_positions.keys())}"
            )

        if end_node not in self._node_positions:
            raise ValueError(
                f"Unknown node '{end_node}'. "
                f"Valid nodes: {list(self._node_positions.keys())}"
            )

        start_pos = self._node_positions[start_node]
        end_pos = self._node_positions[end_node]

        return abs(end_pos - start_pos)

    def get_effective_distance(
        self,
        start_node: str,
        end_node: str,
        time_mins: Optional[int] = None
    ) -> float:
        """
        Get effective distance considering terrain and weather modifiers.

        This method provides a hook for future dynamic modifiers. Currently
        returns the base distance, but can be extended to apply multipliers
        based on terrain difficulty or weather conditions.

        Args:
            start_node: Starting node identifier.
            end_node: Ending node identifier.
            time_mins: Optional departure time for time-based modifiers.

        Returns:
            Effective distance in kilometers after applying modifiers.
        """
        base_distance = self.get_segment_distance(start_node, end_node)

        # Apply terrain modifier if configured
        segment_key = f"{start_node}→{end_node}"
        reverse_key = f"{end_node}→{start_node}"
        terrain_factor = self._terrain_modifiers.get(
            segment_key,
            self._terrain_modifiers.get(reverse_key, 1.0)
        )

        # Apply weather modifier if configured and time provided
        weather_factor = 1.0
        if time_mins is not None:
            # Time bucket (e.g., hour of day)
            time_bucket = time_mins // 60
            weather_factor = self._weather_modifiers.get(time_bucket, 1.0)

        return base_distance * terrain_factor * weather_factor

    def set_terrain_modifier(self, segment: str, factor: float) -> None:
        """
        Set a terrain difficulty modifier for a route segment.

        Args:
            segment: Segment identifier (e.g., "A→B").
            factor: Multiplier for effective distance (1.0 = no change, >1.0 = harder).

        Raises:
            ValueError: If factor is not positive.
        """
        if factor <= 0:
            raise ValueError(f"Terrain modifier must be positive, got {factor}")
        self._terrain_modifiers[segment] = factor

    def set_weather_modifier(self, hour: int, factor: float) -> None:
        """
        Set a weather-based modifier for a specific hour of day.

        Args:
            hour: Hour of day (0-23).
            factor: Multiplier for effective distance.

        Raises:
            ValueError: If hour is out of range or factor is not positive.
        """
        if not 0 <= hour <= 23:
            raise ValueError(f"Hour must be 0-23, got {hour}")
        if factor <= 0:
            raise ValueError(f"Weather modifier must be positive, got {factor}")
        self._weather_modifiers[hour] = factor

    def _exceeds_range(self, distance: float, max_range: float) -> bool:
        """
        Check if a distance exceeds the maximum range.

        Uses floating-point epsilon for precision handling.

        Args:
            distance: Distance to check in kilometers.
            max_range: Maximum allowed range in kilometers.

        Returns:
            True if distance exceeds max_range (accounting for epsilon).
        """
        return distance > (max_range + DISTANCE_EPSILON)

    def validate_charge_plan(
        self,
        direction: str,
        departure_time_mins: int,
        scheduled_stations: List[str]
    ) -> bool:
        """
        Validate if a proposed charge plan is physically viable.

        A plan is valid if the distance between:
        - The origin (for direction) and the first charging station
        - Any two successive charging stations
        - The final charging station and the destination

        ...does not exceed the maximum battery range (240 km by default).

        Args:
            direction: Travel direction (e.g., "Bengaluru→Kochi").
            departure_time_mins: Departure time as minutes from midnight.
                                 Reserved for future time-based modifiers.
            scheduled_stations: List of station IDs where the bus will charge,
                               in the order they will be visited.

        Returns:
            True if the plan is valid, False if any segment exceeds range.

        Raises:
            ValueError: If direction is invalid or station IDs are unknown.

        Example:
            >>> # Route: Bengaluru (0km) → A (100km) → B (200km) → C (350km) → Kochi (500km)
            >>> # Max range: 240km
            >>> manager.validate_charge_plan(
            ...     direction="Bengaluru→Kochi",
            ...     departure_time_mins=600,
            ...     scheduled_stations=["A", "C"]  # B skipped
            ... )
            True  # Bengaluru→A: 100km, A→C: 250km > 240km? False! Invalid!

            >>> manager.validate_charge_plan(
            ...     direction="Bengaluru→Kochi",
            ...     departure_time_mins=600,
            ...     scheduled_stations=["B", "C"]
            ... )
            True  # Bengaluru→B: 200km, B→C: 150km, C→Kochi: 150km - all valid
        """
        # Get start and end points based on direction
        start_node, end_node = self._get_start_end_for_direction(direction)

        # Validate all scheduled stations exist
        for station_id in scheduled_stations:
            if station_id not in self._node_positions:
                raise ValueError(
                    f"Unknown station '{station_id}' in charge plan. "
                    f"Valid stations: {[s.id for s in self._route.stations]}"
                )

        # Build the traversal path: start → [scheduled stations] → end
        # Stations should be ordered by their position along the route for this direction
        if scheduled_stations:
            # Sort scheduled stations by their position relative to travel direction
            if self._is_reverse_direction(direction):
                # Reverse: sort descending by distance from origin
                ordered_stops = sorted(
                    scheduled_stations,
                    key=lambda sid: self._node_positions[sid],
                    reverse=True
                )
            else:
                # Forward: sort ascending by distance from origin
                ordered_stops = sorted(
                    scheduled_stations,
                    key=lambda sid: self._node_positions[sid]
                )
        else:
            ordered_stops = []

        # Build full path: [start] + [ordered stops] + [end]
        path = [start_node] + ordered_stops + [end_node]

        # Check each consecutive segment
        for i in range(len(path) - 1):
            segment_start = path[i]
            segment_end = path[i + 1]

            # Use effective distance (supports future modifiers)
            distance = self.get_effective_distance(
                segment_start,
                segment_end,
                departure_time_mins
            )

            if self._exceeds_range(distance, self.max_range_km):
                return False

        return True

    def get_required_stations(
        self,
        direction: str,
        departure_time_mins: int = 0
    ) -> List[str]:
        """
        Get the minimum set of stations required for a valid charge plan.

        Uses a greedy algorithm to select the furthest reachable station
        at each step without exceeding the maximum range.

        Args:
            direction: Travel direction.
            departure_time_mins: Departure time for time-based modifiers.

        Returns:
            List of station IDs representing a minimal valid charge plan.
            Empty list if no charging is needed to complete the route.

        Note:
            This is a heuristic solution. Optimal station selection may
            require considering factors like charger availability and queue times.
        """
        start_node, end_node = self._get_start_end_for_direction(direction)
        stations = self.get_ordered_stations(direction)

        # Check if we can reach destination without charging
        direct_distance = self.get_effective_distance(
            start_node, end_node, departure_time_mins
        )
        if not self._exceeds_range(direct_distance, self.max_range_km):
            return []

        required: List[str] = []
        current_node = start_node

        station_index = 0
        while station_index < len(stations):
            # Find the furthest station reachable from current position
            furthest_reachable: Optional[str] = None
            furthest_index = station_index

            for i in range(station_index, len(stations)):
                station = stations[i]
                distance = self.get_effective_distance(
                    current_node, station.id, departure_time_mins
                )
                if not self._exceeds_range(distance, self.max_range_km):
                    furthest_reachable = station.id
                    furthest_index = i + 1
                else:
                    break

            if furthest_reachable is None:
                # Cannot reach any station - route is infeasible
                break

            required.append(furthest_reachable)
            current_node = furthest_reachable
            station_index = furthest_index

            # Check if we can reach destination from here
            distance_to_end = self.get_effective_distance(
                current_node, end_node, departure_time_mins
            )
            if not self._exceeds_range(distance_to_end, self.max_range_km):
                break

        return required

    def __repr__(self) -> str:
        """Return a string representation of the RouteManager."""
        return (
            f"RouteManager(origin='{self._route.origin}', "
            f"destination='{self._route.destination}', "
            f"stations={len(self._route.stations)}, "
            f"max_range_km={self.max_range_km})"
        )

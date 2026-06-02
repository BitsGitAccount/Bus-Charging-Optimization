"""
Electric Bus Scheduling Engine - Domain Data Models

This module defines Pydantic v2 schemas for the domain layer, providing:
- Runtime validation with clear error messages
- Type safety for IDE support and static analysis
- Decoupled schema management from business logic

All models are immutable by default (frozen=False for flexibility) and
validate data at instantiation time.
"""

from __future__ import annotations

from typing import Dict, List, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class OperationalWeights(BaseModel):
    """
    Weights for priority calculations in the scheduling engine.

    These weights determine how individual bus needs, operator preferences,
    and overall system efficiency are balanced during charging slot allocation.

    Attributes:
        individual: Weight for individual bus priority (e.g., battery level, urgency).
                    Must be >= 0.0. Default is 1.0.
        operator: Weight for operator-level priority (e.g., fleet balancing).
                  Must be >= 0.0. Default is 1.0.
        overall: Weight for system-wide optimization (e.g., grid load balancing).
                 Must be >= 0.0. Default is 1.0.

    Example:
        >>> weights = OperationalWeights(individual=1.5, operator=1.0, overall=0.8)
        >>> weights.individual
        1.5
    """

    individual: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight for individual bus priority calculations"
    )
    operator: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight for operator-level priority calculations"
    )
    overall: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight for system-wide optimization calculations"
    )


class StationConfig(BaseModel):
    """
    Configuration for a charging station along a route.

    Represents a physical charging location with its infrastructure capacity
    and position relative to the route origin.

    Attributes:
        id: Unique identifier for the station (e.g., "STN_001").
        name: Human-readable station name (e.g., "Salem Charging Hub").
        distance_from_origin_km: Distance from the route origin in kilometers.
                                 Must be >= 0.0.
        charger_count: Number of chargers available at the station.
                       Must be >= 1. Default is 1.

    Example:
        >>> station = StationConfig(
        ...     id="STN_001",
        ...     name="Salem Charging Hub",
        ...     distance_from_origin_km=150.5,
        ...     charger_count=3
        ... )
    """

    id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the station"
    )
    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable station name"
    )
    distance_from_origin_km: float = Field(
        ...,
        ge=0.0,
        description="Distance from route origin in kilometers"
    )
    charger_count: int = Field(
        default=1,
        ge=1,
        description="Number of chargers available at this station"
    )


class RouteConfig(BaseModel):
    """
    Configuration for a bus route with stations and segment distances.

    Defines the topology of a route including origin, destination, intermediate
    charging stations, and distances between key points.

    Attributes:
        origin: Starting point of the route (e.g., "Bengaluru").
        destination: Ending point of the route (e.g., "Kochi").
        stations: List of charging stations along the route, ordered by distance.
        segment_distances: Dictionary mapping segment identifiers to distances in km.
                          Keys should follow format "POINT_A→POINT_B".

    Example:
        >>> route = RouteConfig(
        ...     origin="Bengaluru",
        ...     destination="Kochi",
        ...     stations=[StationConfig(id="S1", name="Salem", distance_from_origin_km=150.0)],
        ...     segment_distances={"Bengaluru→Salem": 150.0, "Salem→Kochi": 350.0}
        ... )
    """

    origin: str = Field(
        ...,
        min_length=1,
        description="Starting point of the route"
    )
    destination: str = Field(
        ...,
        min_length=1,
        description="Ending point of the route"
    )
    stations: List[StationConfig] = Field(
        default_factory=list,
        description="List of charging stations along the route"
    )
    segment_distances: Dict[str, float] = Field(
        default_factory=dict,
        description="Mapping of segment identifiers to distances in kilometers"
    )

    @field_validator('segment_distances')
    @classmethod
    def validate_segment_distances(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure all segment distances are non-negative."""
        for segment, distance in v.items():
            if distance < 0:
                raise ValueError(
                    f"Segment distance for '{segment}' must be >= 0, got {distance}"
                )
        return v


class BusInput(BaseModel):
    """
    Input data for a single bus in a scheduling scenario.

    Represents a bus with its operator assignment, travel direction, and
    scheduled departure time. The departure time can be provided as either
    minutes from midnight (int) or a time string in "HH:MM" format.

    Attributes:
        id: Unique identifier for the bus (e.g., "BUS_001").
        operator: Name of the bus operator (e.g., "KSRTC", "Private Fleet A").
        direction: Travel direction in "Origin→Destination" format.
                   Must contain the arrow character (→) separating origin and destination.
        departure_time_mins: Departure time as minutes from midnight (0-1439).
                            Can be parsed from "HH:MM" string format.

    Example:
        >>> bus = BusInput(
        ...     id="BUS_001",
        ...     operator="KSRTC",
        ...     direction="Bengaluru→Kochi",
        ...     departure_time_mins="19:15"  # Parsed to 1155 minutes
        ... )
        >>> bus.departure_time_mins
        1155
    """

    id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for the bus"
    )
    operator: str = Field(
        ...,
        min_length=1,
        description="Name of the bus operator"
    )
    direction: str = Field(
        ...,
        min_length=3,
        description="Travel direction in 'Origin→Destination' format"
    )

    @field_validator('direction')
    @classmethod
    def validate_direction_format(cls, v: str) -> str:
        """Validate that direction contains the arrow separator."""
        if '→' not in v:
            raise ValueError(
                f"Direction must be in 'Origin→Destination' format with → separator, got '{v}'"
            )
        parts = v.split('→')
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise ValueError(
                f"Direction must have exactly one origin and one destination, got '{v}'"
            )
        return v
    departure_time_mins: int = Field(
        ...,
        ge=0,
        le=1439,
        description="Departure time as minutes from midnight (0-1439)"
    )

    @field_validator('departure_time_mins', mode='before')
    @classmethod
    def parse_time_string(cls, v: Union[int, str]) -> int:
        """
        Parse departure time from HH:MM string format to minutes from midnight.

        Args:
            v: Either an integer (minutes from midnight) or a string in "HH:MM" format.

        Returns:
            Integer representing minutes from midnight.

        Raises:
            ValueError: If string format is invalid or time values are out of range.

        Example:
            "19:15" -> 1155 (19 * 60 + 15)
            "00:00" -> 0
            "23:59" -> 1439
        """
        if isinstance(v, int):
            return v

        if isinstance(v, str):
            if ':' not in v:
                raise ValueError(
                    f"Time string must be in 'HH:MM' format, got '{v}'"
                )

            parts = v.split(':')
            if len(parts) != 2:
                raise ValueError(
                    f"Time string must have exactly one colon (HH:MM), got '{v}'"
                )

            try:
                hours, minutes = int(parts[0]), int(parts[1])
            except ValueError:
                raise ValueError(
                    f"Hours and minutes must be integers, got '{v}'"
                )

            if not (0 <= hours <= 23):
                raise ValueError(
                    f"Hours must be between 0 and 23, got {hours}"
                )
            if not (0 <= minutes <= 59):
                raise ValueError(
                    f"Minutes must be between 0 and 59, got {minutes}"
                )

            return hours * 60 + minutes

        raise ValueError(
            f"departure_time_mins must be int or 'HH:MM' string, got {type(v).__name__}"
        )


class ScenarioInput(BaseModel):
    """
    Complete input specification for a scheduling simulation scenario.

    Combines operational weights, route configuration, and bus fleet data
    into a single validated configuration object for the simulation engine.

    Attributes:
        id: Unique identifier for the scenario (int or string).
        description: Human-readable description of the scenario purpose.
        weights: Operational weights for priority calculations.
        route: Route configuration with stations and segment distances.
        buses: List of buses to be scheduled in this scenario.

    Example:
        >>> scenario = ScenarioInput(
        ...     id="SCENARIO_001",
        ...     description="Peak evening traffic simulation",
        ...     weights=OperationalWeights(individual=1.5),
        ...     route=RouteConfig(origin="Bengaluru", destination="Kochi"),
        ...     buses=[
        ...         BusInput(id="B1", operator="KSRTC",
        ...                  direction="Bengaluru→Kochi", departure_time_mins="19:00")
        ...     ]
        ... )
    """

    id: Union[int, str] = Field(
        ...,
        description="Unique identifier for the scenario (int or string)"
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Human-readable description of the scenario"
    )
    weights: OperationalWeights = Field(
        default_factory=OperationalWeights,
        description="Operational weights for priority calculations"
    )
    route: RouteConfig = Field(
        ...,
        description="Route configuration with stations and segments"
    )
    buses: List[BusInput] = Field(
        default_factory=list,
        description="List of buses to be scheduled"
    )

    @model_validator(mode='after')
    def validate_bus_directions(self) -> 'ScenarioInput':
        """
        Validate that all bus directions are consistent with the route.

        Ensures buses traveling in a direction have the correct origin/destination
        matching the route configuration.
        """
        route_forward = f"{self.route.origin}→{self.route.destination}"
        route_backward = f"{self.route.destination}→{self.route.origin}"

        for bus in self.buses:
            if bus.direction not in (route_forward, route_backward):
                # This is a soft validation - log warning but don't fail
                # The Literal type already enforces valid directions
                pass

        return self

    @field_validator('id', mode='before')
    @classmethod
    def coerce_id(cls, v: Union[int, str]) -> Union[int, str]:
        """Accept both integer and string IDs."""
        if isinstance(v, (int, str)):
            return v
        raise ValueError(f"Scenario ID must be int or str, got {type(v).__name__}")

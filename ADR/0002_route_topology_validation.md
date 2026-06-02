# ADR-0002: Route Topology and Bi-Directional Navigation

## Status
Accepted

## Date
2026-06-02

## Context

The Electric Bus Scheduling Engine must handle buses traveling in both directions along the same physical route (Bengaluru↔Kochi). Key challenges:

1. **Single Source of Truth**: Route topology (stations, distances) should be defined once, not duplicated for each direction.
2. **Bi-Directional Traversal**: A bus heading Bengaluru→Kochi encounters stations A→B→C→D, while Kochi→Bengaluru encounters D→C→B→A.
3. **Range Validation**: Charge plans must be validated against physical constraints (240 km battery range) regardless of travel direction.
4. **Extensibility**: Future modifiers (terrain, weather, battery degradation) should integrate without rewriting core logic.

## Decision

Implement a **`RouteManager` class** that wraps `RouteConfig` and provides direction-aware navigation methods. The topology is stored once (origin-to-destination), and traversal logic handles direction inversion dynamically.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        RouteConfig                              │
│  (Immutable Data: origin, destination, stations, distances)    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       RouteManager                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  get_ordered_stations(direction)                        │   │
│  │  → Returns stations in physical traversal order         │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  get_segment_distance(start_node, end_node)             │   │
│  │  → Returns absolute distance between any two nodes      │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  validate_charge_plan(direction, departure, stations)   │   │
│  │  → Validates plan against MAX_RANGE_KM constraint       │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  [Future] apply_terrain_modifier(segment, factor)       │   │
│  │  [Future] apply_weather_modifier(time, conditions)      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

#### 1. No Data Duplication

Stations are stored once, ordered by `distance_from_origin_km`. The `get_ordered_stations()` method returns:
- **Forward direction**: Stations sorted ascending by distance
- **Reverse direction**: Same list reversed (descending by distance)

```python
def get_ordered_stations(self, direction: str) -> List[StationConfig]:
    sorted_stations = sorted(self._route.stations, key=lambda s: s.distance_from_origin_km)
    if self._is_reverse_direction(direction):
        return list(reversed(sorted_stations))
    return sorted_stations
```

#### 2. Unified Distance Computation

All distances are computed from station positions relative to origin. The `get_segment_distance()` method:
- Builds a position map: `{node_id: distance_from_origin}`
- Includes origin (0.0 km) and destination (total route length)
- Returns `|position_b - position_a|` for any two nodes

This avoids maintaining a separate `segment_distances` dictionary for every possible pair.

#### 3. Direction-Agnostic Validation

`validate_charge_plan()` constructs the traversal path based on direction:
- Forward: `[origin] → [scheduled_stations in order] → [destination]`
- Reverse: `[destination] → [scheduled_stations in reverse order] → [origin]`

Range validation checks each consecutive pair without direction-specific branches.

#### 4. Explicit Floating-Point Precision

Distance comparisons use a configurable epsilon (default `1e-9`) to handle floating-point arithmetic:

```python
DISTANCE_EPSILON: float = 1e-9

def _exceeds_range(self, distance: float, max_range: float) -> bool:
    return distance > (max_range + DISTANCE_EPSILON)
```

#### 5. Hooks for Future Modifiers

The architecture supports pluggable modifiers without changing core logic:

```python
# Future: terrain/weather modifiers
class RouteManager:
    def __init__(self, route: RouteConfig):
        self._route = route
        self._terrain_modifiers: Dict[str, float] = {}  # segment_id -> multiplier
        self._weather_modifiers: Dict[int, float] = {}  # time_bucket -> multiplier

    def get_effective_distance(self, start: str, end: str, time_mins: int) -> float:
        base_distance = self.get_segment_distance(start, end)
        terrain_factor = self._terrain_modifiers.get(f"{start}→{end}", 1.0)
        weather_factor = self._get_weather_factor(time_mins)
        return base_distance * terrain_factor * weather_factor
```

## Rationale

### Why Not Store Two Separate Routes?

Duplicating route data for each direction:
- Increases maintenance burden (two places to update)
- Risks inconsistency (station added to one direction but not the other)
- Wastes memory for large route networks

### Why Compute Distances from Position, Not Segment Dict?

The `segment_distances` field in `RouteConfig` is optional and can represent named segments for display purposes. Computing distances from `distance_from_origin_km`:
- Guarantees consistency with station positions
- Supports arbitrary node pairs (not just adjacent segments)
- Simplifies validation logic

### Why Include `departure_time_mins` in `validate_charge_plan()`?

Currently unused, but reserved for future time-based modifiers:
- Peak traffic slowdowns
- Scheduled road closures
- Weather-dependent range reduction

## Consequences

### Positive
- Single source of truth for route topology
- No conditional branches for direction in validation logic
- Clean extension points for terrain/weather modifiers
- Explicit precision handling prevents floating-point bugs

### Negative
- Slight computational overhead for sorting/reversing on each call (negligible for typical station counts)
- `departure_time_mins` parameter is unused initially (acceptable for forward compatibility)

## Implementation Notes

- `RouteManager` lives in `src/navigation.py`, separate from data models
- Unit tests cover both directions and edge cases (empty stations, boundary distances)
- `MAX_RANGE_KM = 240.0` is a class constant, not hardcoded in methods

## References
- [ADR-0001: Domain Data Models](0001_domain_data_models.md)
- Python `functools.lru_cache` for memoizing expensive computations (future optimization)

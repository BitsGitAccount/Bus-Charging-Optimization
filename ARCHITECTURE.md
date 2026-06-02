# Architecture Documentation

## Electric Bus Scheduling Engine

**Version:** 0.1.0
**Last Updated:** 2026-06-02

This document provides a comprehensive architectural overview of the Electric Bus Scheduling Engine, a production-grade discrete event simulation system for optimizing electric bus charging schedules across multi-station routes.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Scheduling Strategy Choice](#scheduling-strategy-choice)
3. [Data Architecture & Contract Design](#data-architecture--contract-design)
4. [Foresight Matrix](#foresight-matrix)
5. [Code Sandbox Examples](#code-sandbox-examples)
6. [Operational Assumptions](#operational-assumptions)
7. [Module Reference](#module-reference)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Electric Bus Scheduling Engine                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   models    │    │ navigation  │    │   engine    │    │    rules    │  │
│  │  (Pydantic) │───▶│(RouteManager│───▶│(Simulation) │◀───│ (Scoring)   │  │
│  │   Schemas   │    │  Distance)  │    │     DES     │    │  Priority)  │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                                     │                             │
│         │                                     ▼                             │
│         │                              ┌─────────────┐                      │
│         │                              │    app.py   │                      │
│         └─────────────────────────────▶│ (Streamlit) │                      │
│                                        │     UI      │                      │
│                                        └─────────────┘                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Principles

1. **Separation of Concerns**: Data models, routing logic, simulation engine, priority rules, and UI are completely decoupled
2. **Pluggable Strategies**: Business rules can be modified without engine changes
3. **Deterministic Execution**: Identical inputs always produce identical outputs
4. **Testable Components**: Each module can be unit tested in isolation

---

## Scheduling Strategy Choice

### Why Discrete Event Simulation (DES)?

We chose DES over alternative approaches for the following reasons:

#### Comparison Matrix

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Time-Step Loop** | Simple to implement | O(T×N) complexity, wastes cycles on idle periods | ❌ Rejected |
| **Mathematical Solver** | Optimal solutions | NP-hard for realistic constraints, inflexible to rule changes | ❌ Rejected |
| **Discrete Event Simulation** | O(E log E) complexity, models real-world causality | Requires careful event ordering | ✅ Selected |
| **Agent-Based Model** | Flexible emergent behavior | Harder to reason about, non-deterministic | ❌ Rejected |

#### DES Advantages in Detail

**1. Computational Efficiency**

```
Time-Step (1-min resolution, 10 buses, 500 min simulation):
  Iterations: 500 × 10 = 5,000 updates

DES (same scenario):
  Events: ~80 (DEPART, ARRIVE, CHARGE_START, CHARGE_END per bus)
  Operations: 80 × log(80) ≈ 500 comparisons
```

**2. Natural Queue Modeling**

DES inherently handles resource contention:

```
t=100: ARRIVE Bus_A → Charger free → CHARGE_START
t=100: ARRIVE Bus_B → Charger busy → Queue[Bus_B]
t=125: CHARGE_END Bus_A → Pop queue → CHARGE_START Bus_B
```

No explicit polling or busy-wait loops required.

**3. State Isolation**

State changes occur only at event boundaries, making debugging straightforward:

```python
# State is stable between events
assert bus.location == "Station_A"  # True until next event
process_event(DEPART)
assert bus.location == "Station_B"  # Changed atomically
```

**4. Deterministic Replay**

Event ordering guarantees reproducibility:

```python
# Same input → Same output
results_1 = compute_travel_timeline(scenario)
results_2 = compute_travel_timeline(scenario)
assert results_1 == results_2  # Always True
```

### Pluggable Strategy Scoring Matrix

The engine delegates queue resolution to `rules.py`:

```python
# Engine calls rules, not the other way around
next_bus = evaluate_queue(
    queue=waiting_buses,
    current_time=current_time,
    weights=scenario.weights,
    ...
)
```

**Benefits:**
- Business rules change → Modify `rules.py` only
- A/B testing → Swap scoring functions at runtime
- Debugging → Isolated unit tests for priority logic

---

## Data Architecture & Contract Design

### Pydantic Schema Hierarchy

```
ScenarioInput
├── id: Union[int, str]
├── description: str
├── weights: OperationalWeights
│   ├── individual: float (≥0.0)
│   ├── operator: float (≥0.0)
│   └── overall: float (≥0.0)
├── route: RouteConfig
│   ├── origin: str
│   ├── destination: str
│   ├── stations: List[StationConfig]
│   │   ├── id: str
│   │   ├── name: str
│   │   ├── distance_from_origin_km: float (≥0.0)
│   │   └── charger_count: int (≥1)
│   └── segment_distances: Dict[str, float]
└── buses: List[BusInput]
    ├── id: str
    ├── operator: str
    ├── direction: str (validated format: "Origin→Destination")
    └── departure_time_mins: int (0-1439, parsed from "HH:MM")
```

### Validation Flow

```
JSON Input → Pydantic Validation → Typed Python Objects → Engine
     │              │                      │
     │         [ValidationError]           │
     │         if invalid                  │
     ▼                                     ▼
  Raw dict                          ScenarioInput
  (untrusted)                       (type-safe)
```

### Schema-to-Runtime Mapping

| Schema | Runtime State | Relationship |
|--------|---------------|--------------|
| `StationConfig` | `StationState` | 1:1, station_id as key |
| `BusInput` | `BusState` | 1:1, bus_id as key |
| `RouteConfig` | `RouteManager` | 1:1, wraps config |
| `OperationalWeights` | Passed to `evaluate_queue` | Direct usage |

### Output Contract

```python
{
    "scenario_id": str,
    "total_simulation_time_mins": float,
    "events_processed": int,
    "buses": {
        "<bus_id>": {
            "departure_time_mins": int,
            "arrival_time_mins": float,
            "total_journey_time_mins": float,
            "total_travel_time_mins": float,
            "total_charge_time_mins": float,
            "total_wait_time_mins": float,
            "itinerary": List[{time_mins, event, location, ...}]
        }
    },
    "stations": {
        "<station_id>": {
            "total_charges": int,
            "max_queue_length": int,
            "total_queue_time_mins": float,
            "charge_log": List[{bus_id, start_time, end_time, ...}]
        }
    }
}
```

---

## Foresight Matrix

### Anticipated Modifications

The architecture is designed to handle the following changes **without engine code rewrites**:

#### 1. Adding Extra Chargers to High-Traffic Stations

**Change Required:** Data modification only

```json
// data/scenario_X.json
{
  "stations": [
    {"id": "B", "charger_count": 2},  // Before
    {"id": "B", "charger_count": 5}   // After: More chargers
  ]
}
```

**Why It Works:** The engine reads `charger_count` from `StationConfig` and initializes `StationState.total_chargers` dynamically. No code changes needed.

#### 2. Dynamic Terrain/Weather Battery Drain Modifiers

**Change Required:** Configuration + minimal hook activation

```python
# Already implemented in RouteManager
route_manager.set_terrain_modifier("A→B", 1.3)  # 30% harder
route_manager.set_weather_modifier(hour=18, factor=1.2)  # Rain at 6 PM

# Engine uses get_effective_distance() which applies modifiers
distance = route_manager.get_effective_distance("A", "B", time_mins=1080)
```

**Why It Works:** `RouteManager` already has `_terrain_modifiers` and `_weather_modifiers` dictionaries. The engine calls `get_effective_distance()` which applies multipliers automatically.

#### 3. Time-of-Day Dynamic Electricity Utility Rates

**Change Required:** New scoring component in `rules.py`

```python
# Add to WeightedScoreRule._calculate_score()
def _calculate_electricity_cost_score(
    self, station_id: str, current_time: float
) -> float:
    hour = int(current_time // 60) % 24

    # Peak hours: 17:00-21:00 (expensive)
    if 17 <= hour <= 21:
        return -50.0  # Penalty for charging during peak
    # Off-peak: 23:00-05:00 (cheap)
    elif hour >= 23 or hour <= 5:
        return 50.0   # Bonus for off-peak charging
    return 0.0
```

**Why It Works:** The scoring function receives `current_time` and can factor electricity costs into priority decisions. Engine remains unchanged.

#### 4. Priority Tiers for Emergency/VIP Fleet Vehicles

**Change Required:** Schema extension + scoring rule update

```python
# 1. Extend BusInput schema (models.py)
class BusInput(BaseModel):
    priority_tier: int = Field(default=0, ge=0, le=3)
    # 0=Normal, 1=Priority, 2=VIP, 3=Emergency

# 2. Add to scoring (rules.py)
def _calculate_tier_score(self, bus: BusState) -> float:
    tier = getattr(bus, 'priority_tier', 0)
    return tier * 1000.0  # Emergency buses get massive bonus
```

**Why It Works:** Pydantic schemas are extensible. Adding a field with a default value maintains backward compatibility with existing scenarios.

### Extension Points Summary

| Modification | Affected Files | Engine Changes |
|--------------|----------------|----------------|
| More chargers | `data/*.json` | None |
| Terrain modifiers | `RouteManager` config | None |
| Weather modifiers | `RouteManager` config | None |
| Electricity rates | `rules.py` | None |
| VIP priority | `models.py`, `rules.py` | None |
| New event types | `engine.py` | Add handler |

---

## Code Sandbox Examples

### Example 1: Tweaking Operational Weights

```python
from src.models import ScenarioInput, OperationalWeights
from src.engine import compute_travel_timeline
import json

# Load scenario
with open("data/scenario_1.json") as f:
    data = json.load(f)

# Modify weights to favor long-waiting buses
data["weights"] = {
    "individual": 5.0,   # High: penalize wait time heavily
    "operator": 0.5,     # Low: don't prioritize fleet grouping
    "overall": 1.0       # Normal: balanced distance priority
}

scenario = ScenarioInput(**data)
results = compute_travel_timeline(scenario)

# Analyze wait time distribution
wait_times = [
    results["buses"][bid]["total_wait_time_mins"]
    for bid in results["buses"]
]
print(f"Max wait time: {max(wait_times):.0f} mins")
print(f"Avg wait time: {sum(wait_times)/len(wait_times):.1f} mins")
```

### Example 2: Injecting a Custom Queue Prioritization Rule

```python
# Create a new priority rule in rules.py

from src.rules import PriorityRule, BusScore
from typing import List, Dict, Optional

class BatteryLevelRule(PriorityRule):
    """
    Prioritize buses with lowest remaining battery range.

    Rationale: Buses with depleted batteries are at risk of
    stranding if they don't charge soon.
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
        if not queue:
            return None

        # Select bus with lowest remaining range
        return min(queue, key=lambda b: b.remaining_range_km)


# To use in engine, modify _handle_charge_end:
# next_bus = BatteryLevelRule().select_next(queue, ...)
```

### Example 3: Adding a Terrain Modifier

```python
from src.models import RouteConfig, StationConfig
from src.navigation import RouteManager

route = RouteConfig(
    origin="Bengaluru",
    destination="Kochi",
    stations=[
        StationConfig(id="A", name="Station A", distance_from_origin_km=100.0),
        StationConfig(id="B", name="Station B", distance_from_origin_km=220.0),
    ],
    segment_distances={"Bengaluru→A": 100.0, "A→B": 120.0, "B→Kochi": 220.0}
)

manager = RouteManager(route)

# A→B segment has steep terrain (30% more energy consumption)
manager.set_terrain_modifier("A→B", 1.3)

# Now effective distance for A→B is 156km instead of 120km
effective = manager.get_effective_distance("A", "B")
print(f"Effective distance A→B: {effective:.0f} km")  # Output: 156 km
```

### Example 4: Running Scenarios Programmatically

```python
from pathlib import Path
import json
from src.models import ScenarioInput
from src.engine import compute_travel_timeline

# Run all scenarios and compare results
results_summary = {}

for scenario_file in Path("data").glob("scenario_*.json"):
    with open(scenario_file) as f:
        scenario = ScenarioInput(**json.load(f))

    results = compute_travel_timeline(scenario)

    # Compute key metrics
    total_wait = sum(
        b["total_wait_time_mins"] for b in results["buses"].values()
    )
    max_queue = max(
        s["max_queue_length"] for s in results["stations"].values()
    )

    results_summary[scenario_file.name] = {
        "total_wait_mins": total_wait,
        "max_queue_length": max_queue,
        "sim_time_mins": results["total_simulation_time_mins"]
    }

# Display comparison
for name, metrics in results_summary.items():
    print(f"{name}: Wait={metrics['total_wait_mins']:.0f}min, "
          f"MaxQueue={metrics['max_queue_length']}, "
          f"SimTime={metrics['sim_time_mins']:.0f}min")
```

---

## Operational Assumptions

The simulation is built on the following foundational assumptions:

### Traffic & Speed

| Assumption | Value | Justification |
|------------|-------|---------------|
| Constant speed | 60 km/h (1 km/min) | Simplifies travel time calculation |
| Zero traffic variation | N/A | No congestion modeling |
| Instant acceleration/deceleration | N/A | Negligible at macro scale |

### Battery & Charging

| Assumption | Value | Justification |
|------------|-------|---------------|
| Maximum range | 240 km | Conservative estimate for electric buses |
| Charge time | 25 minutes | Fast DC charging assumption |
| Linear recharge profile | Full charge in fixed time | Simplifies scheduling |
| No battery degradation | N/A | Out of scope for MVP |

### Queue & Scheduling

| Assumption | Value | Justification |
|------------|-------|---------------|
| FIFO fallback | Queue order for ties | Deterministic tie-breaking |
| Immediate departure after charge | No dwell time | Maximizes throughput |
| No charger failures | 100% availability | Reliability modeling deferred |

### Route Topology

| Assumption | Value | Justification |
|------------|-------|---------------|
| Linear route | Single path, no branches | Matches Bengaluru-Kochi corridor |
| Symmetric distances | Same distance both directions | No one-way segments |
| All stations have chargers | N/A | Every station can serve buses |

### Data Integrity

| Assumption | Value | Justification |
|------------|-------|---------------|
| Valid JSON input | Pydantic validates | Fail-fast on bad data |
| Unique bus/station IDs | Enforced by design | Prevents collisions |
| Consistent direction format | "Origin→Destination" | Validated by schema |

---

## Module Reference

### `src/models.py`
Pydantic v2 schemas for domain data validation.

- `OperationalWeights` - Weight factors for priority scoring
- `StationConfig` - Charging station configuration
- `RouteConfig` - Route topology definition
- `BusInput` - Individual bus schedule input
- `ScenarioInput` - Complete simulation scenario

### `src/navigation.py`
Route topology and distance management.

- `RouteManager` - Wraps RouteConfig with direction-aware methods
  - `get_ordered_stations(direction)` - Stations in traversal order
  - `get_segment_distance(a, b)` - Distance between nodes
  - `validate_charge_plan(...)` - Check plan against range limits
  - `get_effective_distance(...)` - Apply terrain/weather modifiers

### `src/engine.py`
Discrete Event Simulation runtime.

- `EventType` - Enum: DEPART, ARRIVE, CHARGE_START, CHARGE_END
- `Event` - Immutable event record with ordering
- `BusState` - Mutable bus state during simulation
- `StationState` - Mutable station state with queue
- `SimulationEngine` - Main DES execution class
- `compute_travel_timeline(scenario)` - Public API entry point

### `src/rules.py`
Pluggable priority scoring functions.

- `BusScore` - Detailed score breakdown
- `PriorityRule` - Abstract base class for rules
- `FIFORule` - Simple first-in-first-out
- `WeightedScoreRule` - Configurable weighted scoring
- `evaluate_queue(...)` - Main scoring entry point

### `src/app.py`
Streamlit web application.

- Scenario selector dropdown
- Hyperparameter sidebar controls
- Raw input schedule viewer
- Per-bus journey results table
- Per-station operations journal

---

## Architecture Decision Records

Detailed rationale for key decisions is documented in:

- [ADR-0001: Domain Data Models](ADR/0001_domain_data_models.md)
- [ADR-0002: Route Topology Validation](ADR/0002_route_topology_validation.md)
- [ADR-0003: Discrete Event Simulation Engine](ADR/0003_discrete_event_simulation_engine.md)
- [ADR-0004: Pluggable Priority Rules](ADR/0004_pluggable_priority_rules.md)
- [ADR-0005: User Interface Design](ADR/0005_user_interface_design.md)

---

## Future Enhancements

1. **Real-time Data Integration**: Connect to live bus GPS feeds
2. **Machine Learning**: Train priority models on historical data
3. **Multi-Route Support**: Extend beyond single linear route
4. **API Layer**: REST/GraphQL for external integrations
5. **Persistent Storage**: Database for scenario management
6. **Alert System**: Notifications for queue congestion

---

*This document is maintained as part of the Electric Bus Scheduling Engine project.*

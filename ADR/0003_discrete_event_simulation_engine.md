# ADR-0003: Discrete Event Simulation Engine

## Status
Accepted

## Date
2026-06-02

## Context

The Electric Bus Scheduling Engine must simulate bus movements, charging sessions, and station queue dynamics across a multi-station route. The simulation must:

1. **Track precise timing**: When does each bus arrive, wait, charge, and depart?
2. **Handle resource contention**: Multiple buses competing for limited chargers at stations.
3. **Support deterministic replay**: Given the same inputs, produce identical outputs.
4. **Scale efficiently**: Handle hundreds of buses without O(n²) complexity.

Two primary simulation paradigms were considered:

### Option A: Time-Step Loop (Rejected)
```python
for t in range(0, max_time, step=1):
    for bus in buses:
        bus.update(t)
    for station in stations:
        station.update(t)
```

### Option B: Discrete Event Simulation (Accepted)
```python
while event_queue:
    event = event_queue.pop_earliest()
    process(event)  # May schedule new events
```

## Decision

Implement a **Discrete Event Simulation (DES)** engine that processes discrete event tokens (DEPART, ARRIVE, CHARGE_START, CHARGE_END) in strict chronological order.

## Rationale

### 1. State Isolation

In DES, state changes occur only when events are processed. Between events, the system is stable:

```
Time: 0      100     125     150     200
      |       |       |       |       |
    DEPART  ARRIVE  CHARGE  CHARGE  DEPART
            (Bus A) _START  _END    (Bus A)
```

Each event handler:
- Reads current state
- Modifies state atomically
- Schedules future events

This isolation prevents race conditions and makes debugging straightforward—you can inspect state at any event boundary.

### 2. Deterministic Tracking

Events are processed in strict chronological order using a priority queue (min-heap by `time_mins`). Ties are broken by:
1. Event sequence number (insertion order)
2. Event type priority (CHARGE_END before CHARGE_START to free chargers first)

This guarantees:
- Identical inputs → identical outputs
- Reproducible test scenarios
- Easy comparison between scheduling algorithms

### 3. Scalability

DES only processes "interesting" moments (events), not every time unit:

| Scenario | Time-Step (1-min steps) | DES |
|----------|------------------------|-----|
| 10 buses, 500 mins | 5,000 iterations | ~80 events |
| 100 buses, 500 mins | 50,000 iterations | ~800 events |
| 1000 buses, 500 mins | 500,000 iterations | ~8,000 events |

DES complexity is O(E log E) where E = number of events, compared to O(T × N) for time-step where T = time range and N = entities.

### 4. Natural Modeling of Queues

Station queues emerge naturally from event ordering:

```
t=100: ARRIVE Bus_A at Station_X → Charger available → CHARGE_START
t=100: ARRIVE Bus_B at Station_X → Charger busy → Queue[Bus_B]
t=125: CHARGE_END Bus_A → Pop queue → CHARGE_START Bus_B
t=125: DEPART Bus_A
```

No explicit queue polling or busy-wait loops required.

## Architecture

### Event Types

```python
class EventType(Enum):
    DEPART = "DEPART"           # Bus leaves origin/station
    ARRIVE = "ARRIVE"           # Bus reaches a station
    CHARGE_START = "CHARGE_START"  # Charging begins
    CHARGE_END = "CHARGE_END"      # Charging completes
```

### Event Structure

```python
@dataclass(order=True)
class Event:
    time_mins: float                    # When the event occurs
    sequence: int                       # Tie-breaker for determinism
    event_type: EventType               # What happens
    bus_id: str                         # Which bus
    location: str                       # Where (station ID or origin/destination)
```

### State Trackers

**Bus State:**
```python
@dataclass
class BusState:
    current_time: float         # Accumulated simulation time
    remaining_range_km: float   # Battery range remaining
    current_location: str       # Current position
    planned_stops: List[str]    # Stations where charging is planned
    itinerary: List[dict]       # Detailed log of all events
```

**Station State:**
```python
@dataclass
class StationState:
    total_chargers: int         # Total capacity
    busy_chargers: int          # Currently occupied
    queue: deque[str]           # FIFO waiting queue of bus IDs
```

### Event Processing Rules

| Event | Action | Schedules |
|-------|--------|-----------|
| DEPART | Calculate travel time to next node | ARRIVE |
| ARRIVE | Check if charging needed; if so, check charger availability | CHARGE_START or queue; else DEPART |
| CHARGE_START | Mark charger busy, reset battery to 240km | CHARGE_END (+25 mins) |
| CHARGE_END | Free charger, pop queue if not empty | CHARGE_START for queued bus; DEPART for current bus |

### Output Structure

```python
{
    "scenario_id": "...",
    "total_simulation_time_mins": 525.0,
    "buses": {
        "BUS_001": {
            "departure_time": 0,
            "arrival_time": 500,
            "total_travel_time": 450,
            "total_charge_time": 50,
            "total_wait_time": 0,
            "itinerary": [
                {"time": 0, "event": "DEPART", "location": "Bengaluru"},
                {"time": 200, "event": "ARRIVE", "location": "B"},
                {"time": 200, "event": "CHARGE_START", "location": "B"},
                {"time": 225, "event": "CHARGE_END", "location": "B"},
                {"time": 225, "event": "DEPART", "location": "B"},
                ...
            ]
        }
    },
    "stations": {
        "B": {
            "total_charges": 5,
            "total_queue_time": 25,
            "max_queue_length": 2
        }
    }
}
```

## Consequences

### Positive
- Clean separation between event generation and event handling
- Deterministic, reproducible simulations
- Efficient for sparse event distributions
- Natural fit for queue-based resource contention
- Easy to add new event types (e.g., BREAKDOWN, DELAY)

### Negative
- Requires careful tie-breaking for simultaneous events
- Debugging requires understanding event causality chains
- Not suitable for continuous physics (not needed here)

## Implementation Notes

- Use Python's `heapq` for the event priority queue
- Events are `@dataclass(order=True)` with `time_mins` as primary sort key
- Sequence numbers ensure FIFO ordering for simultaneous events
- Constants: `CHARGE_TIME_MINS = 25`, `SPEED_KM_PER_MIN = 1.0`, `MAX_RANGE_KM = 240.0`

## References
- [ADR-0001: Domain Data Models](0001_domain_data_models.md)
- [ADR-0002: Route Topology Validation](0002_route_topology_validation.md)
- Banks, J. et al. "Discrete-Event System Simulation" (5th ed.)

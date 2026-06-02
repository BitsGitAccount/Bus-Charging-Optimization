# ADR-0004: Pluggable Priority Rules for Queue Resolution

## Status
Accepted

## Date
2026-06-02

## Context

The Electric Bus Scheduling Engine uses charging station queues when multiple buses compete for limited chargers. The initial implementation used a simple First-In-First-Out (FIFO) policy. However, business stakeholders have identified several scenarios where FIFO is suboptimal:

1. **Fairness concerns**: A bus waiting 45 minutes should be prioritized over one waiting 5 minutes
2. **Operator coordination**: Fleet operators want their buses grouped to simplify crew handoffs
3. **Network efficiency**: Buses with long remaining journeys should be cleared quickly to reduce downstream congestion

These requirements will change over time as:
- New operators join the network with different SLAs
- Peak/off-peak policies are introduced
- Dynamic pricing incentivizes different behaviors

## Decision

Extract queue resolution logic into a **pluggable scoring function** that evaluates all waiting buses and returns the highest-priority candidate. The scoring formula is a weighted sum of three components:

```python
def evaluate_queue(
    queue: List[BusState],
    current_time: float,
    stations_state: Dict[str, StationState],
    scenario_weights: OperationalWeights,
    route_manager: RouteManager
) -> BusState:
    """Return the bus with highest priority score."""
```

### Scoring Components

| Component | Formula | Rationale |
|-----------|---------|-----------|
| **Individual** | `(current_time - arrival_time) × weights.individual` | Penalizes making any single bus wait too long |
| **Operator** | `(same_operator_waiting_count) × weights.operator` | Groups operator fleets for coordination |
| **Overall** | `(remaining_distance_to_destination) × weights.overall` | Clears buses with long remaining journeys |

### Score Calculation

```
total_score = individual_score + operator_score + overall_score
```

The bus with the **highest** total score is selected from the queue.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SimulationEngine                             │
│                                                                 │
│  CHARGE_END event handler:                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  if queue is not empty:                                 │   │
│  │      # OLD: next_bus = queue.popleft()  # FIFO         │   │
│  │      # NEW:                                             │   │
│  │      next_bus = evaluate_queue(                         │   │
│  │          queue, current_time, stations_state,           │   │
│  │          scenario.weights, route_manager                │   │
│  │      )                                                  │   │
│  │      queue.remove(next_bus)                             │   │
│  │      schedule CHARGE_START for next_bus                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    rules.py                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  evaluate_queue(queue, time, stations, weights, route)  │   │
│  │                                                         │   │
│  │  for bus in queue:                                      │   │
│  │      individual = (time - arrival) × w.individual       │   │
│  │      operator = count_same_operator() × w.operator      │   │
│  │      overall = remaining_distance() × w.overall         │   │
│  │      score = individual + operator + overall            │   │
│  │                                                         │   │
│  │  return max(queue, key=lambda b: b.score)               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Future extensions:                                             │
│  - Time-of-day modifiers                                        │
│  - SLA-based priority tiers                                     │
│  - Dynamic surge pricing                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Rationale

### Why Separate the Scoring Function?

1. **Prevents Engine Rewrites**: The DES engine processes events and manages state. It should not contain business logic for "who goes next." When stakeholders change priorities, only `rules.py` needs modification.

2. **Enables A/B Testing**: Different scoring functions can be swapped at runtime to compare outcomes across scenarios.

3. **Supports Configuration-Driven Behavior**: The `OperationalWeights` model allows non-technical users to adjust priorities via JSON configuration without code changes.

4. **Facilitates Testing**: Scoring logic can be unit tested in isolation with mock queues, without running full simulations.

### Why a Weighted Sum?

A weighted sum is:
- **Interpretable**: Stakeholders understand "double the operator weight"
- **Tunable**: Weights can be adjusted incrementally
- **Extensible**: New factors can be added as additional terms

Alternative approaches (ML ranking, constraint satisfaction) were considered but rejected for this phase due to complexity and interpretability concerns.

### Edge Cases

| Case | Handling |
|------|----------|
| Queue of 1 | Return the single bus (no comparison needed) |
| Empty queue | Return None (caller handles) |
| Tie scores | First bus in queue order wins (deterministic) |
| Zero weights | Component is ignored (multiplied by 0) |

## Consequences

### Positive
- Business logic changes don't require engine modifications
- Weights are adjustable per-scenario via JSON configuration
- Clear separation of concerns: engine handles "when", rules handle "who"
- Easy to add new scoring components (e.g., battery level, delay penalties)

### Negative
- Slightly more complex than FIFO
- Requires passing additional context to the scoring function
- Score normalization may be needed if components have vastly different scales

## Implementation Notes

- `evaluate_queue` lives in `src/rules.py`
- Engine imports and calls the function during `CHARGE_END` handling
- Arrival time is stored in `BusState` when bus joins queue
- Remaining distance computed via `RouteManager.get_segment_distance()`
- Same-operator count computed by scanning all station queues

## Scenario Weight Configurations

| Scenario | Individual | Operator | Overall | Behavior |
|----------|------------|----------|---------|----------|
| Baseline | 1.0 | 1.0 | 1.0 | Balanced |
| Fairness | 2.0 | 0.5 | 0.5 | Minimize individual wait |
| Fleet-focused | 0.5 | 2.0 | 0.5 | Group operator buses |
| Throughput | 0.5 | 0.5 | 2.0 | Clear long-haul buses |

## References
- [ADR-0001: Domain Data Models](0001_domain_data_models.md)
- [ADR-0003: Discrete Event Simulation Engine](0003_discrete_event_simulation_engine.md)

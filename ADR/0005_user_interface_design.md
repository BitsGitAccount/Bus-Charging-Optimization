# ADR-0005: User Interface Design

## Status
Accepted

## Date
2026-06-02

## Context

The Electric Bus Scheduling Engine requires an interactive user interface for:

1. **Scenario Selection**: Loading and switching between pre-configured scenarios
2. **Parameter Tuning**: Adjusting operational weights to observe behavioral changes
3. **Results Visualization**: Displaying simulation outputs in scannable formats
4. **Operational Analysis**: Examining per-bus journeys and per-station activities

Key architectural decisions involve:
- How tightly to couple UI state with backend computation
- Where to perform data transformations (backend vs. frontend)
- How to handle user-triggered re-simulations

## Decision

Implement a **pure rendering layer** using Streamlit that:
1. Receives simulation results as immutable data structures
2. Performs zero business logic
3. Delegates all computation to the backend engine
4. Uses in-memory state management via Streamlit's session state

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Streamlit Application                           │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │                      Presentation Layer                           │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │
│  │  │  Scenario   │  │  Parameter  │  │  Results    │               │ │
│  │  │  Selector   │  │  Sidebar    │  │  Display    │               │ │
│  │  └──────┬──────┘  └──────┬──────┘  └──────▲──────┘               │ │
│  │         │                │                │                       │ │
│  └─────────┼────────────────┼────────────────┼───────────────────────┘ │
│            │                │                │                         │
│  ┌─────────▼────────────────▼────────────────┴───────────────────────┐ │
│  │                    Session State Manager                          │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │ │
│  │  │  scenario   │  │  weights    │  │  results    │               │ │
│  │  │  (JSON)     │  │  (modified) │  │  (computed) │               │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Backend Engine                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │
│  │  ScenarioInput  │  │  Simulation     │  │  Results        │         │
│  │  (Pydantic)     │→ │  Engine (DES)   │→ │  (Dict)         │         │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

#### 1. UI as Pure Rendering Layer

The Streamlit app performs **no business logic**:

```python
# GOOD: UI delegates to backend
results = compute_travel_timeline(scenario)
st.dataframe(results["buses"])

# BAD: UI contains business logic
for bus in scenario.buses:
    if bus.departure_time < current_time:
        bus.state = "departed"  # Logic in UI
```

Benefits:
- Backend can be tested independently
- UI can be replaced (e.g., with FastAPI + React) without rewriting logic
- Clear separation of concerns

#### 2. In-Memory State Management

Streamlit's `st.session_state` holds:
- `selected_scenario`: Currently loaded scenario JSON
- `modified_weights`: User-adjusted weight values
- `simulation_results`: Computed results from last run

```python
if "simulation_results" not in st.session_state:
    st.session_state.simulation_results = None

# Re-run simulation when weights change
if weights_changed:
    scenario.weights = modified_weights
    st.session_state.simulation_results = compute_travel_timeline(scenario)
```

#### 3. Decoupled Data Flow

```
User Action → State Update → Backend Computation → Result Storage → UI Render
     │              │                │                    │              │
  [Click]    [session_state]  [compute_timeline]  [session_state]  [st.dataframe]
```

The UI never directly modifies simulation state; it only:
1. Reads user inputs
2. Calls backend functions
3. Displays returned results

#### 4. Component Isolation

Each UI component is independent:

| Component | Input | Output |
|-----------|-------|--------|
| Scenario Selector | `data/*.json` files | `ScenarioInput` object |
| Weight Sliders | Current weights | Modified `OperationalWeights` |
| Bus Timetable | `results["buses"]` | Formatted table |
| Station Journal | `results["stations"]` | Tabbed display |

Components communicate only through `st.session_state`, never directly.

## Rationale

### Why Streamlit?

1. **Rapid Prototyping**: Python-native, no JavaScript required
2. **Built-in State Management**: `session_state` handles reactivity
3. **Data-First Design**: Native support for DataFrames and tables
4. **Single-File Deployment**: Easy to containerize and deploy

### Why Pure Rendering?

1. **Testability**: Backend tested with pytest, UI tested visually
2. **Maintainability**: UI changes don't risk breaking simulation logic
3. **Performance**: Heavy computation happens once, UI re-renders are cheap
4. **Portability**: Backend can serve multiple frontends (CLI, API, web)

### Why In-Memory State?

1. **Simplicity**: No database required for MVP
2. **Speed**: Instant access to cached results
3. **Isolation**: Each user session has independent state
4. **Statelessness**: Refresh clears state, preventing stale data

## UI Component Specifications

### 1. Scenario Selector
- Location: Top of viewport
- Type: `st.selectbox`
- Options: `scenario_1.json` through `scenario_5.json`
- Behavior: Selecting new scenario reloads weights and clears results

### 2. Hyperparameter Sidebar
- Location: Left sidebar
- Components:
  - `st.number_input` for `individual` weight (0.0 - 10.0)
  - `st.number_input` for `operator` weight (0.0 - 10.0)
  - `st.number_input` for `overall` weight (0.0 - 10.0)
  - `st.button` "Run Simulation"
- Behavior: Changing values enables re-run with new weights

### 3. Raw Input Viewer
- Location: Main area, collapsible
- Display: `st.dataframe` showing bus schedule
- Columns: Bus ID, Operator, Direction, Departure Time

### 4. Per-Bus Timetable
- Location: Main area
- Display: `st.dataframe` with sortable columns
- Columns:
  - Bus ID
  - Operator
  - Direction
  - Departure Time
  - Arrival Time
  - Total Travel Time
  - Total Charge Time
  - Total Wait Time
  - Planned Stops
- Expandable: Click row to see full itinerary

### 5. Per-Station Journal
- Location: Main area, tabbed interface
- Tabs: Station A, Station B, Station C, Station D
- Content per tab:
  - Total charges processed
  - Max queue length observed
  - Chronological charge log table

## Consequences

### Positive
- Clear separation between presentation and computation
- Backend remains testable and portable
- UI can be rapidly modified without risk
- State management is explicit and debuggable

### Negative
- Streamlit's rerun model requires careful state management
- No real-time updates (requires full recomputation)
- Limited customization compared to React/Vue

## Implementation Notes

- Use `@st.cache_data` for expensive computations (scenario loading)
- Use `st.session_state` for user-modifiable state
- Use `st.tabs` for station journal organization
- Use `st.expander` for collapsible sections
- Format times as HH:MM for readability

## References
- [ADR-0003: Discrete Event Simulation Engine](0003_discrete_event_simulation_engine.md)
- [ADR-0004: Pluggable Priority Rules](0004_pluggable_priority_rules.md)
- [Streamlit Session State Documentation](https://docs.streamlit.io/library/api-reference/session-state)

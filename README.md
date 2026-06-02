# Electric Bus Scheduling Engine

A production-grade discrete event simulation system for optimizing electric bus charging schedules across multi-station routes.

## Features

- **Discrete Event Simulation**: Efficient O(E log E) event-driven architecture
- **Pluggable Priority Rules**: Configurable weighted scoring for queue management
- **Interactive UI**: Streamlit-based web interface for scenario exploration
- **Validated Data Models**: Pydantic v2 schemas with runtime validation
- **Bi-directional Routes**: Support for buses traveling in both directions
- **Comprehensive Logging**: Detailed per-bus itineraries and per-station journals

## Quick Start

### Prerequisites

- Python 3.11 or higher
- pip (Python package manager)

### Installation

```bash
# Clone or navigate to the project directory
cd "Bus Charging Scheduler"

# Create and activate virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application

```bash
# Launch the Streamlit web interface
streamlit run src/app.py
```

The application will open in your default browser at `http://localhost:8501`.

### Running Tests

```bash
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_engine.py -v

# Run with coverage report
pytest --cov=src tests/
```

## Project Structure

```
.
├── ADR/                           # Architecture Decision Records
│   ├── 0001_domain_data_models.md
│   ├── 0002_route_topology_validation.md
│   ├── 0003_discrete_event_simulation_engine.md
│   ├── 0004_pluggable_priority_rules.md
│   └── 0005_user_interface_design.md
├── data/                          # Pre-configured scenario files
│   ├── scenario_1.json            # Even spacing (15 min intervals)
│   ├── scenario_2.json            # Bunched start (8 min intervals)
│   ├── scenario_3.json            # Asymmetric load
│   ├── scenario_4.json            # Operator-heavy (KPN fleet)
│   └── scenario_5.json            # Worst case convergence
├── src/
│   ├── __init__.py                # Package exports
│   ├── models.py                  # Pydantic data schemas
│   ├── navigation.py              # Route topology management
│   ├── engine.py                  # DES simulation runtime
│   ├── rules.py                   # Pluggable priority heuristics
│   └── app.py                     # Streamlit web interface
├── tests/
│   ├── __init__.py
│   ├── test_navigation.py         # Route manager tests
│   ├── test_engine.py             # Simulation engine tests
│   └── test_rules.py              # Priority scoring tests
├── ARCHITECTURE.md                # Detailed system architecture
├── README.md                      # This file
└── requirements.txt               # Python dependencies
```

## Architecture Overview

The system is designed with strict separation of concerns:

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **Data** | `models.py` | Pydantic v2 schemas for validation |
| **Navigation** | `navigation.py` | Route topology and distance calculations |
| **Engine** | `engine.py` | Discrete event simulation runtime |
| **Rules** | `rules.py` | Pluggable priority scoring |
| **UI** | `app.py` | Streamlit presentation layer |

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed documentation.

## Usage Examples

### Programmatic API

```python
import json
from src.models import ScenarioInput
from src.engine import compute_travel_timeline

# Load scenario
with open("data/scenario_1.json") as f:
    scenario = ScenarioInput(**json.load(f))

# Run simulation
results = compute_travel_timeline(scenario)

# Access results
for bus_id, bus_data in results["buses"].items():
    print(f"{bus_id}: Journey time = {bus_data['total_journey_time_mins']} mins")
```

### Custom Weight Configuration

```python
from src.models import ScenarioInput, OperationalWeights

# Modify weights to favor long-waiting buses
scenario.weights = OperationalWeights(
    individual=5.0,  # High weight on wait time penalty
    operator=0.5,    # Low weight on fleet grouping
    overall=1.0      # Normal weight on remaining distance
)

results = compute_travel_timeline(scenario)
```

### Route Distance Queries

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
    segment_distances={"Bengaluru→A": 100.0, "A→B": 120.0, "B→Kochi": 320.0}
)

manager = RouteManager(route)
print(f"Distance A to B: {manager.get_segment_distance('A', 'B')} km")
```

## Scenarios

The `data/` directory contains 5 pre-configured scenarios:

| Scenario | Description | Buses | Weights |
|----------|-------------|-------|---------|
| 1 | Even spacing (15 min intervals) | 20 | Balanced |
| 2 | Bunched start (8 min intervals) | 20 | Balanced |
| 3 | Asymmetric load (10 BK, 4 KB) | 14 | Balanced |
| 4 | Operator-heavy (KPN fleet) | 16 | operator=2.0 |
| 5 | Worst case (tight 8 min, both directions) | 20 | Balanced |

Route: Bengaluru (0km) → A (100km) → B (220km) → C (320km) → D (440km) → Kochi (540km)

## Configuration

### Operational Weights

The queue priority scoring uses three configurable weights:

| Weight | Effect | Use Case |
|--------|--------|----------|
| `individual` | Penalizes long wait times | Fairness optimization |
| `operator` | Groups same-operator buses | Fleet coordination |
| `overall` | Prioritizes long remaining journeys | Network throughput |

### Simulation Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_RANGE_KM` | 240.0 | Maximum battery range |
| `CHARGE_TIME_MINS` | 25.0 | Time to fully charge |
| `SPEED_KM_PER_MIN` | 1.0 | Travel speed (60 km/h) |

## Testing

The project includes comprehensive unit tests:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test class
pytest tests/test_engine.py::TestTwoBusesQueueWaiting -v
```

Current test coverage: **84 tests passing**

## Dependencies

```
streamlit>=1.30.0
pydantic>=2.0.0
pytest>=7.0.0
pandas  # For DataFrame display in UI
```

## Contributing

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) for system design
2. Review relevant ADR documents in `ADR/`
3. Ensure all tests pass: `pytest`
4. Follow existing code style and patterns

## License

This project is for educational and demonstration purposes.

## Acknowledgments

Built with:
- [Streamlit](https://streamlit.io/) - Web application framework
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [pytest](https://pytest.org/) - Testing framework

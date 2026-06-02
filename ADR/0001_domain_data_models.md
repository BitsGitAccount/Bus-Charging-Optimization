# ADR-0001: Domain Data Models with Pydantic v2

## Status
Accepted

## Date
2026-06-02

## Context

The Electric Bus Scheduling Engine requires robust configuration schemas for:
- Operational weights (individual, operator, overall priorities)
- Station configurations (charging infrastructure topology)
- Route configurations (origin-destination pairs with segment distances)
- Bus inputs (operator assignments, directions, departure schedules)
- Scenario definitions (combining all above for simulation runs)

These schemas must be:
1. **Decoupled** from business logic (rules engine, simulation engine, UI)
2. **Validated at runtime** to catch configuration errors early
3. **Type-safe** for IDE support and static analysis
4. **Extensible** without breaking existing configurations

## Decision

We selected **Pydantic v2** as the schema validation and serialization library for all domain data models.

## Rationale

### 1. Runtime Validation with Clear Error Messages

Pydantic v2 validates data at instantiation time, ensuring malformed configurations fail fast with actionable error messages:

```python
class OperationalWeights(BaseModel):
    individual: float = Field(default=1.0, ge=0.0)
    operator: float = Field(default=1.0, ge=0.0)
    overall: float = Field(default=1.0, ge=0.0)
```

Invalid inputs (e.g., negative weights) raise `ValidationError` with field-level details, preventing silent failures downstream in the scheduling engine.

### 2. Type Safety and IDE Integration

Pydantic v2's tight integration with Python's type system enables:
- Autocompletion in IDEs (VSCode, PyCharm)
- Static type checking with mypy/pyright
- Self-documenting code through type hints

```python
def calculate_priority(weights: OperationalWeights, bus: BusInput) -> float:
    # IDE knows weights.individual is a float
    return weights.individual * some_factor
```

### 3. Field Aliasing and Serialization Control

Pydantic v2 supports:
- `alias` for JSON keys that differ from Python attribute names
- `model_dump()` / `model_dump_json()` for controlled serialization
- `model_validate()` for parsing from dictionaries or JSON

This decouples internal Python naming conventions from external data formats (e.g., JSON scenario files).

### 4. Decoupled Schema Management

Domain models live in `src/models.py`, completely isolated from:
- `src/engine.py` (discrete event simulation runtime)
- `src/rules.py` (pluggable priority heuristics)
- `src/app.py` (Streamlit UI layer)

When business rules change (e.g., new weight factors, additional station attributes), only the schema definitions need modification. The engine consumes validated model instances without knowledge of validation logic.

### 5. Performance Improvements in v2

Pydantic v2 (built on Rust-based `pydantic-core`) offers:
- 5-50x faster validation than v1
- Reduced memory footprint
- Better support for complex nested models

This matters for scenarios with hundreds of buses and stations.

### 6. Validators and Computed Fields

Custom validators handle domain-specific parsing:

```python
@field_validator('departure_time_mins', mode='before')
@classmethod
def parse_time_string(cls, v):
    # Converts "19:15" -> 1155 (minutes from midnight)
    if isinstance(v, str) and ':' in v:
        hours, minutes = map(int, v.split(':'))
        return hours * 60 + minutes
    return v
```

## Consequences

### Positive
- Configuration errors caught at load time, not during simulation
- Clear separation between data definition and business logic
- Future schema changes localized to `models.py`
- Strong typing prevents class of bugs at development time

### Negative
- Additional dependency (`pydantic>=2.0.0`)
- Learning curve for team members unfamiliar with Pydantic
- Slight overhead for very simple use cases (acceptable trade-off)

## References
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/)
- [Pydantic v2 Migration Guide](https://docs.pydantic.dev/latest/migration/)

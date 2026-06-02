"""
Electric Bus Scheduling Engine

A production-grade discrete event simulation system for optimizing
electric bus charging schedules across multi-station routes.
"""

from src.engine import (
    CHARGE_TIME_MINS,
    MAX_RANGE_KM,
    SPEED_KM_PER_MIN,
    Event,
    EventType,
    SimulationEngine,
    compute_travel_timeline,
)
from src.models import (
    BusInput,
    OperationalWeights,
    RouteConfig,
    ScenarioInput,
    StationConfig,
)
from src.navigation import RouteManager
from src.rules import (
    BusScore,
    evaluate_queue,
    evaluate_queue_with_scores,
)

__version__ = "0.1.0"

__all__ = [
    # Models
    "BusInput",
    "OperationalWeights",
    "RouteConfig",
    "ScenarioInput",
    "StationConfig",
    # Navigation
    "RouteManager",
    # Engine
    "Event",
    "EventType",
    "SimulationEngine",
    "compute_travel_timeline",
    # Rules
    "BusScore",
    "evaluate_queue",
    "evaluate_queue_with_scores",
    # Constants
    "CHARGE_TIME_MINS",
    "MAX_RANGE_KM",
    "SPEED_KM_PER_MIN",
]

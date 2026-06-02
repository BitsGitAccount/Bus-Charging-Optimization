"""
Streamlit Application Frontend

This module implements the web-based UI for the Electric Bus Scheduling Engine.
Users can load scenarios, configure parameters, run simulations, and visualize results.

The UI is a pure rendering layer that delegates all computation to the backend engine.
See ADR/0005_user_interface_design.md for architectural decisions.

Launch with: streamlit run src/app.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
import pandas as pd

from src.models import OperationalWeights, ScenarioInput
from src.engine import compute_travel_timeline


# =============================================================================
# Constants
# =============================================================================

DATA_DIR = Path(__file__).parent.parent / "data"
SCENARIO_FILES = sorted(DATA_DIR.glob("scenario_*.json"))


# =============================================================================
# Helper Functions
# =============================================================================


def format_time(minutes: float) -> str:
    """Convert minutes from midnight to HH:MM format."""
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"


def load_scenario(filepath: Path) -> ScenarioInput:
    """Load and validate a scenario from JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    return ScenarioInput(**data)


@st.cache_data
def get_scenario_list() -> List[str]:
    """Get list of available scenario files."""
    return [f.name for f in SCENARIO_FILES]


def create_bus_schedule_df(scenario: ScenarioInput) -> pd.DataFrame:
    """Create a DataFrame from scenario bus inputs."""
    rows = []
    for bus in scenario.buses:
        rows.append({
            "Bus ID": bus.id,
            "Operator": bus.operator,
            "Direction": bus.direction,
            "Departure Time": format_time(bus.departure_time_mins),
            "Departure (mins)": bus.departure_time_mins,
        })
    return pd.DataFrame(rows)


def create_bus_results_df(results: Dict[str, Any]) -> pd.DataFrame:
    """Create a DataFrame from simulation results for buses."""
    rows = []
    for bus_id, bus_data in results["buses"].items():
        rows.append({
            "Bus ID": bus_id,
            "Operator": bus_data["operator"],
            "Direction": bus_data["direction"],
            "Departure": format_time(bus_data["departure_time_mins"]),
            "Arrival": format_time(bus_data["arrival_time_mins"]),
            "Travel (mins)": f"{bus_data['total_travel_time_mins']:.0f}",
            "Charge (mins)": f"{bus_data['total_charge_time_mins']:.0f}",
            "Wait (mins)": f"{bus_data['total_wait_time_mins']:.0f}",
            "Journey (mins)": f"{bus_data['total_journey_time_mins']:.0f}",
            "Stops": ", ".join(bus_data["planned_stops"]) if bus_data["planned_stops"] else "None",
            "Completed": "Yes" if bus_data["completed"] else "No",
        })

    df = pd.DataFrame(rows)
    # Sort by departure time
    df = df.sort_values("Departure")
    return df


def create_station_charge_log_df(charge_log: List[Dict]) -> pd.DataFrame:
    """Create a DataFrame from station charge log."""
    if not charge_log:
        return pd.DataFrame(columns=["Bus ID", "Start Time", "End Time", "Wait (mins)", "Duration (mins)"])

    rows = []
    for entry in charge_log:
        rows.append({
            "Bus ID": entry["bus_id"],
            "Start Time": format_time(entry["start_time"]),
            "End Time": format_time(entry["end_time"]),
            "Wait (mins)": f"{entry['wait_time']:.0f}",
            "Duration (mins)": f"{entry['duration']:.0f}",
        })
    return pd.DataFrame(rows)


def create_itinerary_df(itinerary: List[Dict]) -> pd.DataFrame:
    """Create a DataFrame from bus itinerary."""
    rows = []
    for event in itinerary:
        row = {
            "Time": format_time(event["time_mins"]),
            "Event": event["event"],
            "Location": event["location"],
        }
        # Add optional fields
        if "remaining_range_km" in event:
            row["Range (km)"] = f"{event['remaining_range_km']:.0f}"
        if "wait_time" in event:
            row["Wait (mins)"] = f"{event['wait_time']:.0f}"
        if "queue_position" in event:
            row["Queue Pos"] = event["queue_position"]
        rows.append(row)
    return pd.DataFrame(rows)


# =============================================================================
# UI Components
# =============================================================================


def render_sidebar() -> tuple[Optional[ScenarioInput], OperationalWeights, bool]:
    """
    Render the sidebar with scenario selector and weight controls.

    Returns:
        Tuple of (loaded scenario, modified weights, run_clicked)
    """
    st.sidebar.header("Scenario Configuration")

    # Scenario selector
    scenario_files = get_scenario_list()
    if not scenario_files:
        st.sidebar.error("No scenario files found in data/ directory")
        return None, OperationalWeights(), False

    selected_file = st.sidebar.selectbox(
        "Select Scenario",
        scenario_files,
        key="scenario_selector",
        help="Choose a pre-configured scenario to load"
    )

    # Load scenario
    scenario_path = DATA_DIR / selected_file
    try:
        scenario = load_scenario(scenario_path)
    except Exception as e:
        st.sidebar.error(f"Error loading scenario: {e}")
        return None, OperationalWeights(), False

    st.sidebar.markdown("---")
    st.sidebar.subheader("Operational Weights")
    st.sidebar.caption("Adjust weights to change queue prioritization behavior")

    # Weight controls
    individual = st.sidebar.number_input(
        "Individual Weight",
        min_value=0.0,
        max_value=10.0,
        value=float(scenario.weights.individual),
        step=0.1,
        help="Penalizes making individual buses wait too long"
    )

    operator = st.sidebar.number_input(
        "Operator Weight",
        min_value=0.0,
        max_value=10.0,
        value=float(scenario.weights.operator),
        step=0.1,
        help="Groups buses from the same operator"
    )

    overall = st.sidebar.number_input(
        "Overall Weight",
        min_value=0.0,
        max_value=10.0,
        value=float(scenario.weights.overall),
        step=0.1,
        help="Prioritizes buses with long remaining journeys"
    )

    modified_weights = OperationalWeights(
        individual=individual,
        operator=operator,
        overall=overall
    )

    st.sidebar.markdown("---")

    # Run button
    run_clicked = st.sidebar.button(
        "Run Simulation",
        type="primary",
        use_container_width=True
    )

    # Display scenario info
    st.sidebar.markdown("---")
    st.sidebar.subheader("Scenario Info")
    st.sidebar.text(f"ID: {scenario.id}")
    st.sidebar.text(f"Buses: {len(scenario.buses)}")
    st.sidebar.text(f"Stations: {len(scenario.route.stations)}")
    st.sidebar.text(f"Route: {scenario.route.origin} → {scenario.route.destination}")

    return scenario, modified_weights, run_clicked


def render_input_schedule(scenario: ScenarioInput) -> None:
    """Render the raw input schedule viewer."""
    with st.expander("Raw Input Schedule", expanded=False):
        st.caption(f"**Description:** {scenario.description}")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Buses", len(scenario.buses))
        with col2:
            st.metric("Total Stations", len(scenario.route.stations))

        df = create_bus_schedule_df(scenario)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Departure (mins)": st.column_config.NumberColumn(
                    "Departure (mins)",
                    help="Minutes from midnight"
                )
            }
        )


def render_bus_results(results: Dict[str, Any]) -> None:
    """Render the per-bus timetable results."""
    st.subheader("Per-Bus Journey Results")

    # Summary metrics
    summary = results["summary"]
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Buses", summary["total_buses"])
    with col2:
        st.metric("Completed", summary["completed_buses"])
    with col3:
        st.metric("Total Charges", summary["total_charges"])
    with col4:
        st.metric("Total Queue Time", f"{summary['total_queue_time_mins']:.0f} mins")

    # Bus results table
    df = create_bus_results_df(results)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Completed": st.column_config.TextColumn(
                "Completed",
                help="Whether the bus completed its journey"
            )
        }
    )

    # Detailed itinerary per bus
    st.markdown("---")
    st.subheader("Detailed Bus Itineraries")

    bus_ids = list(results["buses"].keys())
    selected_bus = st.selectbox(
        "Select Bus to View Itinerary",
        bus_ids,
        key="itinerary_bus_selector"
    )

    if selected_bus:
        bus_data = results["buses"][selected_bus]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.text(f"Operator: {bus_data['operator']}")
        with col2:
            st.text(f"Direction: {bus_data['direction']}")
        with col3:
            st.text(f"Planned Stops: {', '.join(bus_data['planned_stops']) if bus_data['planned_stops'] else 'None'}")

        itinerary_df = create_itinerary_df(bus_data["itinerary"])
        st.dataframe(
            itinerary_df,
            use_container_width=True,
            hide_index=True
        )


def render_station_results(results: Dict[str, Any]) -> None:
    """Render the per-station operations journal."""
    st.subheader("Per-Station Operations Journal")

    stations = results["stations"]
    if not stations:
        st.info("No station data available")
        return

    # Create tabs for each station
    station_ids = sorted(stations.keys())
    tabs = st.tabs([f"Station {sid}" for sid in station_ids])

    for tab, station_id in zip(tabs, station_ids):
        with tab:
            station_data = stations[station_id]

            # Station metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Chargers", station_data["total_chargers"])
            with col2:
                st.metric("Total Charges", station_data["total_charges"])
            with col3:
                st.metric("Max Queue", station_data["max_queue_length"])
            with col4:
                st.metric("Queue Time", f"{station_data['total_queue_time_mins']:.0f} mins")

            # Charge log table
            st.markdown("**Charging Log**")
            if station_data["charge_log"]:
                charge_df = create_station_charge_log_df(station_data["charge_log"])
                st.dataframe(
                    charge_df,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No charging sessions at this station")


def render_simulation_summary(results: Dict[str, Any]) -> None:
    """Render overall simulation summary."""
    st.subheader("Simulation Summary")

    col1, col2 = st.columns(2)
    with col1:
        st.metric(
            "Total Simulation Time",
            f"{results['total_simulation_time_mins']:.0f} mins",
            help="Time until last bus completed journey"
        )
    with col2:
        st.metric(
            "Events Processed",
            results["events_processed"],
            help="Total discrete events processed"
        )


# =============================================================================
# Main Application
# =============================================================================


def main() -> None:
    """
    Main entry point for the Streamlit application.

    Implements the complete UI with:
    - Scenario selector
    - Hyperparameter sidebar
    - Raw input viewer
    - Per-bus timetable results
    - Per-station operations journal
    """
    st.set_page_config(
        page_title="Electric Bus Scheduling Engine",
        page_icon="🚌",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Title
    st.title("🚌 Electric Bus Scheduling Engine")
    st.caption("Discrete Event Simulation for Electric Bus Charging Optimization")

    # Initialize session state
    if "simulation_results" not in st.session_state:
        st.session_state.simulation_results = None
    if "last_scenario" not in st.session_state:
        st.session_state.last_scenario = None

    # Render sidebar and get controls
    scenario, weights, run_clicked = render_sidebar()

    if scenario is None:
        st.error("Please select a valid scenario to continue")
        return

    # Check if scenario changed
    scenario_changed = (
        st.session_state.last_scenario != scenario.id
    )

    if scenario_changed:
        st.session_state.simulation_results = None
        st.session_state.last_scenario = scenario.id

    st.markdown("---")

    # Render input schedule
    render_input_schedule(scenario)

    st.markdown("---")

    # Run simulation if requested
    if run_clicked:
        # Update scenario with modified weights
        scenario_dict = scenario.model_dump()
        scenario_dict["weights"] = weights.model_dump()
        modified_scenario = ScenarioInput(**scenario_dict)

        with st.spinner("Running simulation..."):
            try:
                results = compute_travel_timeline(modified_scenario)
                st.session_state.simulation_results = results
                st.success("Simulation completed successfully!")
            except Exception as e:
                st.error(f"Simulation failed: {e}")
                st.session_state.simulation_results = None

    # Display results if available
    if st.session_state.simulation_results is not None:
        results = st.session_state.simulation_results

        # Simulation summary
        render_simulation_summary(results)

        st.markdown("---")

        # Bus results
        render_bus_results(results)

        st.markdown("---")

        # Station results
        render_station_results(results)
    else:
        st.info(
            "Click **Run Simulation** in the sidebar to execute the simulation "
            "with the current scenario and weight configuration."
        )

    # Footer
    st.markdown("---")
    st.caption(
        "Electric Bus Scheduling Engine v0.1.0 | "
        "Built with Streamlit | "
        "[Architecture Documentation](ARCHITECTURE.md)"
    )


if __name__ == "__main__":
    main()

import json
from pathlib import Path

import pytest

from zelvo.config import load_scenario
from zelvo.contracts import NetworkBuild, RunResult, RunStatus
from zelvo.runtime import discover_tools
from zelvo.simulation.smoke import run_smoke

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scenarios/smoke/smoke.json"


@pytest.fixture(scope="module")
def runtime():
    return discover_tools()


def test_real_journey_is_measured_repeatable_and_not_overwritten(tmp_path, runtime):
    first = run_smoke(CONFIG, tmp_path, runtime=runtime)
    second = run_smoke(CONFIG, tmp_path, runtime=runtime)
    assert first.status == second.status == RunStatus.COMPLETED
    assert first.run_id != second.run_id
    assert first.journeys == second.journeys
    journey = first.journeys[0]
    assert journey.completed
    assert journey.journey_time_s > 0
    assert journey.arrival_s == pytest.approx(journey.actual_departure_s + journey.journey_time_s)
    assert first.collision_events == first.teleport_events == 0
    saved = RunResult.model_validate_json(Path(first.artifacts["result"]).read_text())
    assert saved == first
    events = [json.loads(line) for line in Path(first.artifacts["events"]).read_text().splitlines()]
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert any(event["kind"] == "vehicle_arrived" and event["vehicle_id"] == "ambulance-0"
               for event in events)
    assert "signal_safety_audit" in first.unavailable_metrics


def test_horizon_preserves_unfinished_journey_instead_of_zero(tmp_path, runtime):
    scenario = load_scenario(CONFIG).model_copy(update={"horizon_s": 1.0})
    config = tmp_path / "short.json"
    config.write_text(scenario.model_dump_json())
    result = run_smoke(config, tmp_path / "outputs", runtime=runtime)
    assert result.status == RunStatus.INCOMPLETE
    assert result.journeys[0].actual_departure_s is not None
    assert result.journeys[0].arrival_s is None
    assert result.journeys[0].journey_time_s is None
    assert result.simulated_duration_s == pytest.approx(1.0)


def test_timeout_is_explicit_and_evidence_survives(tmp_path, runtime):
    result = run_smoke(CONFIG, tmp_path, runtime=runtime, wall_timeout_s=0.000001)
    assert result.status == RunStatus.TIMED_OUT
    assert result.failure is not None
    assert Path(result.artifacts["result"]).is_file()
    assert Path(result.artifacts["events"]).is_file()


def test_arrived_ambulance_does_not_hide_unfinished_ordinary_traffic(tmp_path, runtime):
    scenario = load_scenario(CONFIG).model_copy(update={"horizon_s": 35.0})
    config = tmp_path / "recovery-cut-short.json"
    config.write_text(scenario.model_dump_json())
    result = run_smoke(config, tmp_path / "outputs", runtime=runtime)
    assert result.journeys[0].completed
    assert result.status == RunStatus.INCOMPLETE


def test_real_network_build_error_is_recorded(tmp_path, runtime):
    invalid_nodes = tmp_path / "invalid.nod.xml"
    invalid_nodes.write_text("<nodes><broken")
    original = load_scenario(CONFIG)
    scenario = original.model_copy(update={"build": NetworkBuild(
        nodes_file=invalid_nodes, edges_file=original.build.edges_file,
    )})
    config = tmp_path / "bad-network.json"
    config.write_text(scenario.model_dump_json())
    result = run_smoke(config, tmp_path / "outputs", runtime=runtime)
    assert result.status == RunStatus.FAILED
    assert result.failure.error_type == "CalledProcessError"
    assert Path(result.artifacts["network_build_log"]).is_file()
    assert Path(result.artifacts["result"]).is_file()

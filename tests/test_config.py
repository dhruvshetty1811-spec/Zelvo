import json
import pytest

from zelvo.config import load_scenario


def test_paths_resolve_against_config_not_working_directory(tmp_path, monkeypatch):
    fixture = tmp_path / "scenario"
    fixture.mkdir()
    (fixture / "network.xml").write_text("<net/>")
    (fixture / "routes.xml").write_text("<routes/>")
    path = fixture / "scenario.json"
    path.write_text(json.dumps({
        "scenario_id": "test", "seed": 1, "controller": "actuated",
        "network_file": "network.xml", "route_files": ["routes.xml"],
        "expected_journeys": [{"vehicle_id": "a", "scheduled_departure_s": 0}],
    }))
    monkeypatch.chdir(tmp_path)
    scenario = load_scenario(path)
    assert scenario.network_file == fixture / "network.xml"
    assert scenario.route_files == (fixture / "routes.xml",)


def test_missing_source_has_actionable_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "scenario_id": "test", "seed": 1, "controller": "actuated",
        "network_file": "absent.xml", "route_files": ["absent-routes.xml"],
        "expected_journeys": [{"vehicle_id": "a", "scheduled_departure_s": 0}],
    }))
    with pytest.raises(ValueError, match="Scenario input does not exist"):
        load_scenario(path)

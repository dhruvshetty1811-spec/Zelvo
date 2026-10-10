import math

import pytest
from pydantic import ValidationError

from zelvo.contracts import JourneyResult, MovementObservation, PriorityRequest, ScenarioConfig


def request(**changes):
    return PriorityRequest.model_validate({
        "request_id": "request-1", "journey_id": "ambulance-0", "intersection_id": "junction-1",
        "movement_id": "straight", "route_version": 0, "requested_at_s": 10,
        "arrival_earliest_s": 15, "arrival_latest_s": 20, "expires_at_s": 25,
        **changes,
    })


@pytest.mark.parametrize("changes", [
    {"arrival_earliest_s": 9}, {"arrival_latest_s": 14}, {"expires_at_s": 19},
    {"requested_at_s": math.nan}, {"arrival_latest_s": math.inf},
    {"request_id": "../escape"}, {"arbitrary_lamp_state": "GGGG"},
])
def test_rejects_invalid_or_unbounded_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_unknown_lane_observations_are_not_empty_queues():
    observation = MovementObservation(intersection_id="j", movement_id="m", incoming_lane="in",
                                      outgoing_lane="out", observed_at_s=5)
    assert observation.queue_count is None
    assert observation.receiving_entry_space_m is None


def test_unfinished_journey_cannot_claim_zero_travel_time():
    with pytest.raises(ValidationError, match="unfinished"):
        JourneyResult(vehicle_id="a", scheduled_departure_s=0, journey_time_s=0)


def test_completed_journey_requires_consistent_measurement():
    with pytest.raises(ValidationError, match="arrival minus departure"):
        JourneyResult(vehicle_id="a", scheduled_departure_s=0, actual_departure_s=3,
                      arrival_s=10, completed=True, journey_time_s=10)


def test_missing_arrival_cannot_be_reported_as_complete():
    with pytest.raises(ValidationError, match="completed"):
        JourneyResult(vehicle_id="a", scheduled_departure_s=0, completed=True)


def test_scenario_rejects_unreachable_departure_horizon():
    with pytest.raises(ValidationError, match="precede horizon"):
        ScenarioConfig.model_validate({
            "scenario_id": "test", "seed": 1, "controller": "actuated",
            "network_file": "network.xml", "route_files": ["routes.xml"], "horizon_s": 10,
            "expected_journeys": [{"vehicle_id": "a", "scheduled_departure_s": 10}],
        })

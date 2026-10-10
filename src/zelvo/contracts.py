"""Versioned boundary models. Timestamps are simulation seconds unless stated."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Seconds = Annotated[float, Field(ge=0)]
PositiveSeconds = Annotated[float, Field(gt=0)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ControllerKind(StrEnum):
    FIXED = "fixed_time"
    ACTUATED = "actuated"
    LOCAL = "local_preemption"
    ANALYTICAL = "zelvo_analytical"
    AI = "zelvo_ai"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INCOMPLETE = "incomplete"


class RequestStatus(StrEnum):
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    ACTIVE = "active"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class NetworkBuild(Contract):
    nodes_file: Path
    edges_file: Path


class ExpectedJourney(Contract):
    vehicle_id: Identifier
    scheduled_departure_s: Seconds


class LaneIncident(Contract):
    lane: str = Field(min_length=1)
    start_s: Seconds
    end_s: PositiveSeconds
    speed_mps: float = Field(default=1,ge=0)

    @model_validator(mode='after')
    def check_duration(self):
        if self.end_s<=self.start_s:
            raise ValueError('Incident end must follow start')
        return self


class ScenarioConfig(Contract):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: Identifier
    seed: int = Field(ge=0, le=2**31 - 1)
    controller: ControllerKind
    network_file: Path
    route_files: tuple[Path, ...] = Field(min_length=1)
    build: NetworkBuild | None = None
    step_length_s: PositiveSeconds = Field(default=0.1, le=1)
    horizon_s: PositiveSeconds = 120.0
    wall_timeout_s: PositiveSeconds = 60.0
    expected_journeys: tuple[ExpectedJourney, ...] = Field(min_length=1)
    approach_distance_m: float = Field(default=150, gt=0)
    observation_delay_s: Seconds = 0
    backend: Literal['traci','libsumo'] = 'traci'
    dynamic_routing: bool = False
    incidents: tuple[LaneIncident, ...] = ()

    @model_validator(mode="after")
    def check_timeline(self):
        if self.horizon_s < self.step_length_s:
            raise ValueError("horizon_s must be at least one simulation step")
        ids = [j.vehicle_id for j in self.expected_journeys]
        if len(ids) != len(set(ids)):
            raise ValueError("expected_journeys contains duplicate vehicle IDs")
        if any(j.scheduled_departure_s >= self.horizon_s for j in self.expected_journeys):
            raise ValueError("expected departures must precede horizon_s")
        return self


class MovementObservation(Contract):
    intersection_id: str
    movement_id: str
    incoming_lane: str
    outgoing_lane: str
    observed_at_s: Seconds
    queue_count: int | None = Field(default=None, ge=0)
    queue_extent_m: float | None = Field(default=None, ge=0)
    receiving_entry_space_m: float | None = Field(default=None, ge=0)
    phase_index: int | None = Field(default=None, ge=0)


class PriorityRequest(Contract):
    request_id: Identifier
    journey_id: Identifier
    intersection_id: str
    movement_id: str
    route_version: int = Field(ge=0)
    requested_at_s: Seconds
    arrival_earliest_s: Seconds
    arrival_latest_s: Seconds
    expires_at_s: Seconds
    priority_class: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_window(self):
        if not self.requested_at_s <= self.arrival_earliest_s <= self.arrival_latest_s:
            raise ValueError("arrival window must follow request time and be ordered")
        if self.expires_at_s <= self.requested_at_s:
            raise ValueError("expiry must follow request time")
        if self.expires_at_s < self.arrival_latest_s:
            raise ValueError("expiry must cover the arrival window")
        return self


class SimulationEvent(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    sequence: int = Field(ge=0)
    simulation_time_s: Seconds
    kind: str
    vehicle_id: str | None = None
    details: dict[str, str | float | int | bool | None] = Field(default_factory=dict)


class JourneyResult(Contract):
    vehicle_id: Identifier
    scheduled_departure_s: Seconds
    actual_departure_s: Seconds | None = None
    arrival_s: Seconds | None = None
    completed: bool = False
    departure_delay_s: Seconds | None = None
    journey_time_s: Seconds | None = None
    scheduled_start_to_arrival_s: Seconds | None = None
    stopped_time_s: Seconds | None = None
    stops: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_completion(self):
        if self.completed != (self.arrival_s is not None):
            raise ValueError("completed must agree with arrival_s")
        if self.arrival_s is not None:
            if self.actual_departure_s is None or self.arrival_s < self.actual_departure_s:
                raise ValueError("arrival must follow actual departure")
            expected = self.arrival_s - self.actual_departure_s
            if self.journey_time_s is None or abs(self.journey_time_s - expected) > 1e-6:
                raise ValueError("journey_time_s must equal arrival minus departure")
        elif self.journey_time_s is not None:
            raise ValueError("unfinished journeys must not have completed travel times")
        return self


class RunFailure(Contract):
    error_type: str
    message: str


class RunResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    scenario_id: Identifier
    seed: int
    controller: ControllerKind
    status: RunStatus
    simulated_duration_s: Seconds
    wall_duration_s: Seconds
    journeys: tuple[JourneyResult, ...]
    runtime_versions: dict[str, str]
    input_hashes: dict[str, str]
    artifacts: dict[str, str]
    collision_events: int = Field(ge=0)
    teleport_events: int = Field(ge=0)
    unavailable_metrics: tuple[str, ...] = ()
    failure: RunFailure | None = None
    metrics: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_status(self):
        if self.status in (RunStatus.FAILED, RunStatus.TIMED_OUT) and self.failure is None:
            raise ValueError("failed or timed-out runs require an error record")
        if self.status == RunStatus.COMPLETED and (
            self.failure is not None or not self.journeys or not all(j.completed for j in self.journeys)
        ):
            raise ValueError("completed run requires completed journeys and no error")
        return self

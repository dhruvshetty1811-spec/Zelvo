"""A real headless runtime check, deliberately not a coordination benchmark."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

from zelvo.config import load_scenario
from zelvo.contracts import (
    ControllerKind, JourneyResult, RunFailure, RunResult, RunStatus, SimulationEvent,
)
from zelvo.runtime import RuntimeInfo, child_environment, discover_tools, installed_sumo_environment


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: str) -> None:
    import os
    import uuid
    temporary = path.with_suffix(path.suffix + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        stream.write(value+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers and sync clients can briefly deny replacement. Keep the
    # old complete document visible, and bound retries for persistent failures.
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==7:raise
            time.sleep(min(.025*2**attempt,.4))


def run_smoke(config_path: Path, output_root: Path, *,
              runtime: RuntimeInfo | None = None, wall_timeout_s: float | None = None) -> RunResult:
    import traci

    config = load_scenario(config_path)
    if config.controller != ControllerKind.ACTUATED:
        raise ValueError("Slice 0 smoke supports actuated ordinary signals only")
    runtime = runtime or discover_tools()
    if wall_timeout_s is not None:
        config = type(config).model_validate({**config.model_dump(), "wall_timeout_s": wall_timeout_s})
    run_id = "smoke-" + uuid.uuid4().hex
    output = output_root.resolve() / run_id
    output.mkdir(parents=True, exist_ok=False)
    sources = [config_path.resolve(), *config.route_files]
    if config.build:
        sources += [config.build.nodes_file, config.build.edges_file]
    else:
        sources.append(config.network_file)
    hashes = {str(path): sha256(path) for path in sources}
    artifacts = {name: str(output / filename) for name, filename in {
        "result": "result.json", "config": "config.json", "events": "events.jsonl",
        "tripinfo": "tripinfo.xml", "sumo_log": "sumo.log", "sumo_errors": "sumo-errors.log",
        "network_build_log": "netconvert.log",
    }.items()}
    started = time.monotonic()
    simulation_time = 0.0
    collisions = teleports = 0
    failure = None
    status = RunStatus.FAILED
    connection = None
    journeys = tuple(JourneyResult(vehicle_id=j.vehicle_id,
                                   scheduled_departure_s=j.scheduled_departure_s)
                     for j in config.expected_journeys)
    sequence = 0
    atomic_json(Path(artifacts["config"]), config.model_dump_json(indent=2))
    with Path(artifacts["events"]).open("w", encoding="utf-8") as events:
        def emit(kind: str, vehicle_id: str | None = None, **details):
            nonlocal sequence
            event = SimulationEvent(run_id=run_id, sequence=sequence,
                                    simulation_time_s=simulation_time, kind=kind,
                                    vehicle_id=vehicle_id, details=details)
            events.write(event.model_dump_json() + "\n")
            events.flush()
            sequence += 1

        emit("run_started", started_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            if config.build:
                network = output / "network.net.xml"
                build = subprocess.run([
                    str(runtime.netconvert_binary), "--node-files", str(config.build.nodes_file),
                    "--edge-files", str(config.build.edges_file), "--output-file", str(network),
                    "--tls.default-type", "actuated", "--tls.allred.time", "2",
                    "--no-turnarounds", "true",
                ], capture_output=True, text=True, timeout=config.wall_timeout_s,
                    env=child_environment(runtime))
                Path(artifacts["network_build_log"]).write_text(
                    build.stdout + build.stderr, encoding="utf-8")
                build.check_returncode()
                config = config.model_copy(update={"network_file": network})
            hashes[str(config.network_file)] = sha256(config.network_file)
            atomic_json(Path(artifacts["config"]), config.model_dump_json(indent=2))
            command = [
                str(runtime.sumo_binary), "--net-file", str(config.network_file),
                "--route-files", ",".join(map(str, config.route_files)),
                "--step-length", str(config.step_length_s), "--seed", str(config.seed),
                "--tripinfo-output", artifacts["tripinfo"],
                "--tripinfo-output.write-unfinished", "true",
                "--log", artifacts["sumo_log"], "--error-log", artifacts["sumo_errors"],
                "--no-step-log", "true", "--duration-log.disable", "true",
                "--time-to-teleport", "-1",
            ]
            emit("simulation_starting")
            with (output / "process.log").open("w", encoding="utf-8") as process_log:
                with installed_sumo_environment(runtime), redirect_stdout(process_log):
                    traci.start(command, label=run_id, stdout=process_log, doSwitch=False, numRetries=2)
                connection = traci.getConnection(run_id)
                while connection.simulation.getMinExpectedNumber() > 0:
                    if time.monotonic() - started > config.wall_timeout_s:
                        raise TimeoutError("Smoke run exceeded wall-clock budget")
                    if simulation_time + config.step_length_s > config.horizon_s + 1e-8:
                        break
                    connection.simulationStep()
                    simulation_time = connection.simulation.getTime()
                    for vehicle_id in connection.simulation.getDepartedIDList():
                        emit("vehicle_departed", vehicle_id,
                             actual_departure_s=connection.vehicle.getDeparture(vehicle_id))
                    for vehicle_id in connection.simulation.getArrivedIDList():
                        emit("vehicle_arrived", vehicle_id)
                    colliding = connection.simulation.getCollidingVehiclesIDList()
                    teleporting = connection.simulation.getStartingTeleportIDList()
                    collisions += len(colliding)
                    teleports += len(teleporting)
                    if colliding:
                        emit("collision_observed", vehicles=",".join(colliding))
                    if teleporting:
                        emit("teleport_observed", vehicles=",".join(teleporting))
                remaining_traffic = connection.simulation.getMinExpectedNumber()
                connection.close()
                connection = None
            tripinfo = {item.attrib["id"]: item.attrib
                        for item in ET.parse(artifacts["tripinfo"]).getroot().findall("tripinfo")}
            measured = []
            for expected in config.expected_journeys:
                trip = tripinfo.get(expected.vehicle_id)
                if trip is None:
                    measured.append(JourneyResult(vehicle_id=expected.vehicle_id,
                                                  scheduled_departure_s=expected.scheduled_departure_s))
                    continue
                departure = float(trip["depart"])
                arrival = float(trip["arrival"])
                completed = arrival >= 0
                measured.append(JourneyResult(
                    vehicle_id=expected.vehicle_id,
                    scheduled_departure_s=expected.scheduled_departure_s,
                    actual_departure_s=departure, arrival_s=arrival if completed else None,
                    completed=completed,
                    departure_delay_s=max(0.0, departure - expected.scheduled_departure_s),
                    journey_time_s=arrival - departure if completed else None,
                    scheduled_start_to_arrival_s=arrival - expected.scheduled_departure_s if completed else None,
                ))
            journeys = tuple(measured)
            status = (RunStatus.COMPLETED if remaining_traffic == 0 and all(j.completed for j in journeys)
                      else RunStatus.INCOMPLETE)
        except Exception as exc:
            failure = RunFailure(error_type=type(exc).__name__, message=str(exc))
            status = RunStatus.TIMED_OUT if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)) else RunStatus.FAILED
            emit("run_error", error_type=failure.error_type, message=failure.message)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception as close_error:
                    emit("close_error", message=str(close_error))
        emit("run_finished", status=status.value)
    result = RunResult(
        run_id=run_id, scenario_id=config.scenario_id, seed=config.seed, controller=config.controller,
        status=status, simulated_duration_s=simulation_time,
        wall_duration_s=time.monotonic() - started, journeys=journeys,
        runtime_versions=runtime.versions, input_hashes=hashes, artifacts=artifacts,
        collision_events=collisions, teleport_events=teleports,
        unavailable_metrics=("stop_tracking", "junction_response", "passage_wait", "network_delay",
                             "pedestrian_wait", "spillback", "signal_safety_audit", "planner_latency"),
        failure=failure,
    )
    atomic_json(Path(artifacts["result"]), result.model_dump_json(indent=2))
    return result

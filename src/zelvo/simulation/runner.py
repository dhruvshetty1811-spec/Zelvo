"""Measured fixed-horizon SUMO episodes, all five controller variants."""
from contextlib import redirect_stdout
from pathlib import Path
import json
import subprocess
import time
import uuid
import hashlib
import shutil
import xml.etree.ElementTree as ET

from zelvo.config import load_scenario
from zelvo.contracts import RunResult, RunStatus, RunFailure, ControllerKind
from zelvo.runtime import discover_tools, child_environment, installed_sumo_environment
from zelvo.simulation.smoke import sha256, atomic_json
from zelvo.control import Supervisor, install_fixed_programs, retain_demands
from zelvo.planning import Observer, Planner, route_with_hysteresis, analytical_eta, lane_queue
from zelvo.recording import Recorder
from zelvo.metrics import distribution


def archive_input(path: Path,root: Path) -> Path:
    """One content-addressed COPY per input version; mutable originals stay separate."""
    digest=sha256(path)
    root.mkdir(parents=True,exist_ok=True)
    target=root/(digest+path.suffix)
    from zelvo.campaign_io import exclusive
    # Serialize publication of the same content across native workers. Two
    # writers must not replace a file that the other worker has begun reading.
    with exclusive(root/(digest+'.lock'),blocking=True):
        temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        for attempt in range(8):
            try:
                if target.exists():
                    if sha256(target)!=digest:raise ValueError('Archived input hash mismatch: '+str(target))
                else:
                    shutil.copyfile(path,temporary)
                    if sha256(temporary)!=digest:
                        temporary.unlink()
                        raise ValueError('Input changed while being archived: '+str(path))
                    temporary.replace(target)
                break
            except PermissionError:
                if attempt==7:raise
                time.sleep(min(.025*2**attempt,.4))
        if temporary.exists():temporary.unlink()
    return target


def run_episode(config_path: Path, output_root: Path, *, controller=None, model_path=None,
                collect_training=False, horizon=None, wall_timeout=None,backend=None,run_id=None,
                telemetry=None) -> RunResult:
    import traci
    import traci.constants as tc
    config = load_scenario(config_path)
    updates = {}
    if controller is not None: updates['controller'] = ControllerKind(controller)
    if horizon is not None: updates['horizon_s'] = horizon
    if wall_timeout is not None: updates['wall_timeout_s'] = wall_timeout
    if backend is not None: updates['backend'] = backend
    config = type(config).model_validate({**config.model_dump(),**updates})
    runtime = discover_tools()
    run_id = run_id or 'run-'+uuid.uuid4().hex
    if not run_id.startswith('run-') or len(run_id)!=36 or any(c not in '0123456789abcdef' for c in run_id[4:]):
        raise ValueError('run_id must be run- followed by 32 lowercase hexadecimal characters')
    output = output_root.resolve()/run_id
    output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    sources = [config_path.resolve(),*config.route_files]
    if config.build: sources += [config.build.nodes_file,config.build.edges_file]
    else: sources += [config.network_file]
    hashes = {str(p):sha256(p) for p in sources}
    source_root=Path(__file__).resolve().parents[1]
    engine=hashlib.sha256()
    for source in sorted(source_root.rglob('*.py')):
        engine.update(source.relative_to(source_root).as_posix().encode())
        engine.update(source.read_bytes())
    hashes['engine_source_sha256']=engine.hexdigest()
    lock=source_root.parents[1]/'uv.lock'
    if lock.exists():hashes['dependency_lock_sha256']=sha256(lock)
    if model_path:
        hashes[str(Path(model_path).resolve())] = sha256(Path(model_path))
    artifacts = {key:str(output/value) for key,value in {
        'result':'result.json','events':'events.jsonl','tripinfo':'tripinfo.xml','config':'config.json',
        'aggregate':'aggregate.jsonl','predictions':'predictions.jsonl','training':'training.jsonl',
        'sumo_log':'sumo.log','sumo_errors':'sumo-errors.log','network_build_log':'netconvert.log',
        'planning_latency':'planning-latency.json'}.items()}
    atomic_json(Path(artifacts['config']),config.model_dump_json(indent=2))
    now = 0.0
    c = None
    failure = None
    status = RunStatus.INCOMPLETE
    sequence = collisions = teleports = 0
    collision_records=0
    collision_pairs=set()
    previous_contacts=set()
    metrics = {}
    unavailable = []
    recorder = None
    planner = None
    latencies = []
    planning_samples = []
    pending = []
    completed_labels = []
    snapshots_history = []
    spillback_seconds = 0
    event_counts = {}
    try:
        with Path(artifacts['events']).open('w',encoding='utf-8') as events, \
             Path(artifacts['aggregate']).open('w',encoding='utf-8') as aggregates, \
             (output/'process.log').open('w',encoding='utf-8') as process_log:
            def emit(kind,**details):
                nonlocal sequence
                event_counts[kind] = event_counts.get(kind,0)+1
                events.write(json.dumps({'schema_version':'1.0','run_id':run_id,'sequence':sequence,
                    'simulation_time_s':now,'kind':kind,'details':details},allow_nan=False)+'\n')
                sequence += 1
            emit('run_started',controller=config.controller.value)
            if config.build:
                network = output/'network.net.xml'
                build = subprocess.run([str(runtime.netconvert_binary),'--node-files',str(config.build.nodes_file),
                    '--edge-files',str(config.build.edges_file),'--output-file',str(network),
                    '--tls.default-type','actuated','--tls.allred.time','2','--tls.yellow.time','3',
                    '--no-turnarounds','true'],capture_output=True,text=True,timeout=60,env=child_environment(runtime))
                Path(artifacts['network_build_log']).write_text(build.stdout+build.stderr,encoding='utf-8')
                build.check_returncode()
                config = config.model_copy(update={'network_file':network,'build':None})
                hashes[str(network)] = sha256(network)
            input_store=output_root.resolve().parent/'inputs'
            archived_network=archive_input(config.network_file,input_store)
            archived_routes=tuple(archive_input(p,input_store) for p in config.route_files)
            hashes[str(archived_network)]=sha256(archived_network)
            for p in archived_routes:hashes[str(p)]=sha256(p)
            config=config.model_copy(update={'network_file':archived_network,'route_files':archived_routes})
            if model_path:
                archived_model=archive_input(Path(model_path),input_store)
                manifest_source=Path(model_path).with_suffix('.json')
                manifest_target=archived_model.with_suffix('.json')
                if manifest_target.exists() and sha256(manifest_target)!=sha256(manifest_source):
                    raise ValueError('Archived model manifest mismatch')
                if not manifest_target.exists():
                    temporary_manifest=manifest_target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
                    shutil.copyfile(manifest_source,temporary_manifest)
                    if sha256(temporary_manifest)!=sha256(manifest_source):
                        raise ValueError('Model manifest changed during archival')
                    temporary_manifest.replace(manifest_target)
                artifacts['model']=str(archived_model)
                model_path=archived_model
            atomic_json(Path(artifacts['config']),config.model_dump_json(indent=2))
            command = [str(runtime.sumo_binary),'--net-file',str(config.network_file),
                '--route-files',','.join(map(str,config.route_files)),'--step-length',str(config.step_length_s),
                '--seed',str(config.seed),'--tripinfo-output',artifacts['tripinfo'],
                '--tripinfo-output.write-unfinished','true','--log',artifacts['sumo_log'],
                '--error-log',artifacts['sumo_errors'],'--no-step-log','true',
                '--duration-log.disable','true','--time-to-teleport','-1',
                '--collision.action','warn','--collision.check-junctions','true']
            if config.backend=='libsumo':
                import libsumo
                import importlib.metadata
                if importlib.metadata.version('libsumo')!=runtime.versions['sumo']:
                    raise ValueError('libsumo binary must match SUMO version')
                runtime.versions['libsumo']=importlib.metadata.version('libsumo')
                c=libsumo
                with installed_sumo_environment(runtime),redirect_stdout(process_log):
                    c.start(command)
            else:
                with installed_sumo_environment(runtime),redirect_stdout(process_log):
                    traci.start(command,label=run_id,stdout=process_log,doSwitch=False,numRetries=2)
                c = traci.getConnection(run_id)
            if config.controller == ControllerKind.FIXED:
                install_fixed_programs(c)
            ordinary_policy = config.controller in (ControllerKind.FIXED,ControllerKind.ACTUATED)
            supervisor = Supervisor(c,emit,occupancy_guard=not ordinary_policy)
            observer = Observer(c)
            predictor = None
            if config.controller == ControllerKind.AI:
                if model_path is None: raise ValueError('zelvo_ai requires a frozen trained --model')
                from zelvo.learning import Predictor
                predictor = Predictor(Path(model_path))
            planner = Planner(config.controller.value,emit,predictor)
            recorder = Recorder(config.expected_journeys,config.approach_distance_m,emit)
            if telemetry is not None:
                telemetry.start(c)
            active_demands = []
            next_plan = next_aggregate = next_route = 0.0
            applied_incidents = set()
            restored_incidents = set()
            old_limits = {}
            while now+config.step_length_s<=config.horizon_s+1e-8:
                if (output_root/'STOP').exists():
                    raise InterruptedError('Episode stopped by local STOP marker')
                if time.monotonic()-started>config.wall_timeout_s:
                    raise TimeoutError('Episode wall-clock budget exceeded')
                c.simulationStep()
                now = c.simulation.getTime()
                for vid in c.simulation.getDepartedIDList():
                    variables = (tc.VAR_SPEED,tc.VAR_ROAD_ID,tc.VAR_LANE_ID,tc.VAR_TIMELOSS,
                                 tc.VAR_LANEPOSITION,tc.VAR_LENGTH)
                    if telemetry is not None:
                        variables += (tc.VAR_POSITION,tc.VAR_ANGLE)
                    c.vehicle.subscribe(vid,variables)
                snapshots = c.vehicle.getAllSubscriptionResults()
                recorder.update(c,now,config.step_length_s,snapshots)
                reported_collisions=c.simulation.getCollisions()
                collision_records+=len(reported_collisions)
                contacts={tuple(sorted((collision.collider,collision.victim))) for collision in reported_collisions}
                collisions+=len(contacts-previous_contacts)
                collision_pairs.update(contacts)
                for collision in reported_collisions:
                    if tuple(sorted((collision.collider,collision.victim))) not in previous_contacts:
                        emit('collision_observed',collider=collision.collider,victim=collision.victim,
                             lane=collision.lane,position_m=collision.pos)
                previous_contacts=contacts
                teleporting=c.simulation.getStartingTeleportIDList()
                teleports += len(teleporting)
                for vid in teleporting:emit('teleport_observed',vehicle=vid)
                # Incidents are observations when they occur, never future model features.
                for index,incident in enumerate(config.incidents):
                    if now>=incident.start_s and index not in applied_incidents:
                        lane = incident.lane
                        old_limits[index] = c.lane.getMaxSpeed(lane)
                        c.lane.setMaxSpeed(lane,incident.speed_mps)
                        applied_incidents.add(index)
                        emit('incident_started',lane=lane)
                    if index in applied_incidents and index not in restored_incidents and now>=incident.end_s:
                        c.lane.setMaxSpeed(incident.lane,old_limits[index])
                        restored_incidents.add(index)
                        emit('incident_finished',lane=incident.lane)
                active_evs = sorted(set(recorder.expected)&snapshots.keys())
                if config.dynamic_routing and now>=next_route:
                    for vid in active_evs:
                        if route_with_hysteresis(c,vid):
                            recorder.route_changed(vid)
                            planner.route_versions[vid] = planner.route_versions.get(vid,0)+1
                            active_demands = [d for d in active_demands if d.vehicle!=vid]
                            emit('route_changed',vehicle=vid,version=planner.route_versions[vid])
                    next_route = now+10
                if now>=next_plan:
                    plan_started = time.perf_counter()
                    observed = [o for vid in active_evs for o in observer.observe(vid,now)]
                    supervisor.monitor_corridor({o.tls for o in observed})
                    if collect_training:
                        # Independent training records for every baseline too.
                        for o in observed:
                            o.action_hold = float(any(d.permitted and d.tls==o.tls and d.link==o.link for d in active_demands))
                            pending.append({'episode':run_id,'seed':config.seed,'controller':config.controller.value,
                                            'observation':o,'features':o.features(),'analytical_eta':analytical_eta(o),
                                            'queue_label':None,'cross_time':None})
                    snapshots_history.append((now,observed))
                    cutoff = now-config.observation_delay_s
                    available = [items for t,items in snapshots_history if t<=cutoff+1e-8]
                    planning_observations = available[-1] if available else []
                    snapshots_history = [(t,items) for t,items in snapshots_history if t>=now-config.observation_delay_s-4]
                    active_demands = planner.plan(now,planning_observations)
                    spillback_seconds += 2*sum(o.entry_space_m<10 for o in observed)
                    latency = (time.perf_counter()-plan_started)*1000
                    latencies.append(latency)
                    planning_samples.append({'simulation_time_s':now,'duration_ms':latency})
                    next_plan = now+2
                # Remove requests immediately after confirmed crossing, not at a periodic plan tick.
                crossed = {key for key,r in recorder.approaches.items() if r['crossed_s'] is not None}
                active_demands = retain_demands(active_demands,active_evs,planner.route_versions,crossed)
                supervisor.tick(now,active_demands,recorder.current_person_lanes)
                if collect_training:
                    for item in pending:
                        o = item['observation']
                        if item['queue_label'] is None and now>=o.time+10:
                            item['queue_label'] = lane_queue(c,o.outgoing)[0]
                        record = recorder.approaches.get((o.vehicle,o.tls,o.link))
                        if record and record['crossed_s'] is not None:
                            item['cross_time'] = record['crossed_s']
                    done = [p for p in pending if p['queue_label'] is not None and p['cross_time'] is not None]
                    completed_labels.extend(done)
                    pending = [p for p in pending if p not in done]
                if now>=next_aggregate:
                    congestion=recorder.congestion(c,snapshots,now)
                    aggregates.write(json.dumps({'time_s':now,'active_vehicles':len(snapshots),
                        'pending_insertions':len(c.simulation.getPendingVehicles()),
                        'active_ambulances':active_evs,'collisions':collisions,'teleports':teleports,
                        'congestion':congestion})+'\n')
                    events.flush()
                    next_aggregate = now+1
                if telemetry is not None:
                    telemetry.tick(c,now,snapshots,recorder,collisions,teleports)
                # Preserve a common horizon even when ambulances finish for fair recovery metrics.
            pending_insertions = len(c.simulation.getPendingVehicles())
            expected_remaining = c.simulation.getMinExpectedNumber()
            emit('run_finished',expected_remaining=expected_remaining,pending_insertions=pending_insertions)
            c.close()
            c = None
            metrics = recorder.metrics(artifacts['tripinfo'],now)
            scheduled = {v.attrib['id']:float(v.attrib['depart'])
                         for route_file in config.route_files for v in ET.parse(route_file).getroot().findall('vehicle')
                         if v.attrib.get('depart','').replace('.','',1).isdigit() and float(v.attrib['depart'])<=now}
            uninserted = {v:t for v,t in scheduled.items() if v not in recorder.inserted and v not in recorder.expected}
            metrics['ordinary'].update(scheduled=len([v for v in scheduled if v not in recorder.expected]),
                                       uninserted_at_end=len(uninserted),
                                       uninserted_delay_lower_bound_s=sum(now-t for t in uninserted.values()))
            metrics.update(safety_audit_errors=supervisor.audit_errors,
                           collision_records=collision_records,unique_collision_pairs=len(collision_pairs),
                           collision_count_definition='New contact episodes per vehicle pair; raw per-step collision records also retained',
                           measurement_resolution_s=config.step_length_s,
                           event_counts=event_counts,
                           sampled_corridor_blocked_lane_seconds=spillback_seconds,
                           planner_latency_ms={'samples':len(latencies),'max':max(latencies,default=0),
                                               'mean':sum(latencies)/max(1,len(latencies)),
                                               'distribution':distribution(latencies)},
                           signal_policy='ordinary unmodified cycling; audit only' if ordinary_policy else 'priority with corridor occupancy guard',
                           pending_insertions_at_end=pending_insertions,expected_remaining=expected_remaining,
                           training={'complete_labels':len(completed_labels),'censored_labels':len(pending)})
            metrics['internal_lane_occupancy_coverage']={'scope':'observed emergency corridors',
                                                        'monitored_lanes':len(supervisor.watched_lanes)}
            status = RunStatus.COMPLETED if expected_remaining==0 and all(j.completed for j in recorder.journeys()) else RunStatus.INCOMPLETE
    except (Exception,KeyboardInterrupt) as exc:
        failure = RunFailure(error_type=type(exc).__name__,message=str(exc))
        status = RunStatus.TIMED_OUT if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)) else RunStatus.FAILED
        with Path(artifacts['events']).open('a',encoding='utf-8') as events:
            events.write(json.dumps({'schema_version':'1.0','run_id':run_id,'sequence':sequence,
                'simulation_time_s':now,'kind':'run_error','details':failure.model_dump()})+'\n')
    finally:
        if c is not None:
            try: c.close()
            except Exception: pass
    if recorder is None:
        recorder = Recorder(config.expected_journeys,config.approach_distance_m,lambda *a,**kw:None)
    if failure:
        metrics.update(event_counts=event_counts,partial_measurements=True)
    Path(artifacts['planning_latency']).write_text(json.dumps(planning_samples)+'\n',encoding='utf-8')
    with Path(artifacts['predictions']).open('w',encoding='utf-8') as f:
        for p in planner.predictions if planner else []:
            f.write(json.dumps(p)+'\n')
    with Path(artifacts['training']).open('w',encoding='utf-8') as f:
        for p in completed_labels+pending:
            o = p['observation']
            f.write(json.dumps({'episode':run_id,'seed':config.seed,'controller':config.controller.value,
                'time':o.time,'vehicle':o.vehicle,'tls':o.tls,'link':o.link,'features':p['features'],
                'analytical_eta':p['analytical_eta'],
                'eta_residual':None if p['cross_time'] is None else max(0,p['cross_time']-o.time)-p['analytical_eta'],
                'queue_10s':p['queue_label'],'censored':p['cross_time'] is None,
                'network_hash':hashes.get(str(config.network_file)),
                'engine_hash':hashes['engine_source_sha256'],
                'collision_records':collisions,'safety_audit_errors':metrics.get('safety_audit_errors'),
                'episode_status':status.value,
                'target_definition':'ETA to observed stopline crossing; queue on receiving lane at +10s'})+'\n')
    result = RunResult(run_id=run_id,scenario_id=config.scenario_id,seed=config.seed,controller=config.controller,
        status=status,simulated_duration_s=now,wall_duration_s=time.monotonic()-started,
        journeys=recorder.journeys(),runtime_versions=runtime.versions,input_hashes=hashes,artifacts=artifacts,
        collision_events=collisions,teleport_events=teleports,metrics=metrics,failure=failure,
        unavailable_metrics=('district_calibrated_pedestrian_demand','physical_controller_measurements',
                             'calibrated_contiguous_queue_extent','full_intersection_box_occupancy'))
    atomic_json(Path(artifacts['result']),result.model_dump_json(indent=2))
    return result

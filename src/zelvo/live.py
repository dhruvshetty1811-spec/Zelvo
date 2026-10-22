"""Local, bounded live-demo sessions. Separate from the paused evaluation campaign."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import math
import os
import re
from pathlib import Path
import random
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from zelvo.config import load_scenario
from zelvo.simulation.smoke import atomic_json, sha256

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / 'scenarios/bengaluru-hospital/demo-long-links-cross-60-start-3-second-60-second-at-120.json'
MODEL = ROOT / 'models/predictor.joblib'
EXPANDED = ROOT / 'scenarios/bengaluru-expanded/expanded.json'
CURATED = ROOT / 'scenarios/bengaluru-curated-demo/expanded.json'


def worker_startup_error(path: Path) -> str:
    """Expose the final startup exception, without returning an entire worker log."""
    fallback = 'The simulation worker exited before saving a result. Check its worker.log in the run folder.'
    if not path.is_file():
        return fallback
    with path.open('rb') as stream:
        stream.seek(0,2)
        stream.seek(max(0,stream.tell()-8192))
        lines = stream.read().decode('utf-8',errors='replace').splitlines()
    for line in reversed(lines):
        if re.match(r'^(ImportError|ModuleNotFoundError|PermissionError|FileNotFoundError|RuntimeError|OSError): ',line):
            return 'Simulation worker startup failed: '+line[:500]
    return fallback


class DemoSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    density: Literal['light', 'moderate', 'heavy'] = 'moderate'
    density_percent: int | None = Field(default=None, ge=0, le=200)
    corridor: Literal['reference', 'expanded', 'curated'] = 'reference'
    seed: int = Field(default=42, ge=0, le=2**31-1)
    dispatch_s: int = Field(default=60, ge=30, le=180)
    observation_delay_s: float = Field(default=0, ge=0, le=6)


def prepare_inputs(settings: DemoSettings, directory: Path, source=None) -> dict:
    """Density changes demand, never baseline signals or ambulance driving settings."""
    directory = directory.resolve()
    source = source or {'reference':DEMO,'expanded':EXPANDED,'curated':CURATED}[settings.corridor]
    config = load_scenario(source)
    tree = ET.parse(config.route_files[0])
    root = tree.getroot()
    ordinary = [v for v in root.findall('vehicle') if v.get('id') != 'ambulance-0']
    rng = random.Random(settings.seed)
    percent = settings.density_percent
    if percent is None:
        percent = {'light':50, 'moderate':100, 'heavy':200}[settings.density]
    target = len(ordinary) * percent // 100
    if target < len(ordinary):
        selected = set(rng.sample(range(len(ordinary)), target))
        for index, vehicle in enumerate(ordinary):
            if index not in selected:
                root.remove(vehicle)
    elif target > len(ordinary):
        # Add a seeded sample of OD departures with bounded departure offsets.
        # Preserve every original route and type; both policies receive this same file.
        extra = target - len(ordinary)
        indices = range(len(ordinary)) if extra == len(ordinary) else rng.sample(range(len(ordinary)), extra)
        for index in indices:
            vehicle = ordinary[index]
            clone = ET.fromstring(ET.tostring(vehicle))
            clone.set('id', 'extra-'+str(index))
            clone.set('depart', str(round(float(vehicle.get('depart'))+rng.uniform(.5,5),3)))
            root.append(clone)
    ambulance = next(v for v in root.findall('vehicle') if v.get('id') == 'ambulance-0')
    ambulance.set('depart', str(settings.dispatch_s))
    vehicles = root.findall('vehicle')
    for vehicle in vehicles:
        root.remove(vehicle)
    root.extend(sorted(vehicles,key=lambda v:float(v.get('depart'))))
    directory.mkdir(parents=True,exist_ok=False)
    routes = directory/'demand.rou.xml'
    tree.write(routes,encoding='utf-8',xml_declaration=True)
    data = config.model_dump(mode='json')
    data.update(seed=settings.seed,route_files=[str(routes)],network_file=str(config.network_file),
                observation_delay_s=settings.observation_delay_s,
                expected_journeys=[{'vehicle_id':'ambulance-0','scheduled_departure_s':settings.dispatch_s}],
                wall_timeout_s=900)
    atomic_json(directory/'scenario.json',json.dumps(data,indent=2))
    receipt = {'schema_version':'1.0','settings':settings.model_dump(),
               'density_percent':percent,
               'created_at_utc':datetime.now(timezone.utc).isoformat(),
               'ordinary_vehicle_count':len(vehicles)-1,'demand_sha256':sha256(routes),
               'network_sha256':sha256(config.network_file),'model_sha256':sha256(MODEL),
               'source_demo_sha256':sha256(source),
               'comparison':'Identical demand, network, seed and vehicle parameters; ordinary actuated signals versus ZELVO AI',
               'evaluation_campaign':False,'curated_corridor':True}
    atomic_json(directory/'inputs.json',json.dumps(receipt,indent=2))
    return receipt


def geometry(source=DEMO) -> dict:
    """Projected OSM road shapes and exact controlled route movements; no remote tiles."""
    config = load_scenario(source)
    root = ET.parse(config.network_file).getroot()
    vehicles = ET.parse(config.route_files[0]).getroot().findall('vehicle')
    route = next(v for v in vehicles
                 if v.get('id') == 'ambulance-0').find('route').get('edges').split()
    edges = {e.get('id'):e for e in root.findall('edge')}
    def points(lane):
        return [[round(float(c),2) for c in p.split(',')] for p in lane.get('shape').split()]
    def drivable(lane):
        allowed = lane.get('allow')
        return ('passenger' in allowed.split() or 'bus' in allowed.split()) if allowed else 'passenger' not in lane.get('disallow','').split()
    shapes = [points(next(l for l in edges[e].findall('lane') if drivable(l))) for e in route]
    all_points = [p for shape in shapes for p in shape]
    bounds = [min(p[0] for p in all_points)-180,min(p[1] for p in all_points)-180,
              max(p[0] for p in all_points)+180,max(p[1] for p in all_points)+180]
    roads = []
    for edge in edges.values():
        lanes = [l for l in edge.findall('lane') if drivable(l)]
        if not lanes:
            continue
        shape = points(lanes[0])
        if any(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3] for x,y in shape):
            roads.append({'id':edge.get('id'),'shape':shape,'lanes':len(lanes),
                          'internal':edge.get('id').startswith(':'),'name':edge.get('name','')})
    pairs = set(zip(route,route[1:]))
    signals = []
    seen = set()
    for connection in root.findall('connection'):
        a = connection.attrib
        if 'tl' not in a or (a['from'],a['to']) not in pairs or a['tl'] in seen:
            continue
        lane = next(l for l in edges[a['from']].findall('lane') if l.get('index')==a['fromLane'])
        signals.append({'id':a['tl'],'link':int(a['linkIndex']),'position':points(lane)[-1]})
        seen.add(a['tl'])
    length = sum(float(edges[e].find('lane').get('length')) for e in route)
    return {'bounds':bounds,'roads':roads,'route':shapes,'signals':signals,
            'origin':shapes[0][0],'hospital':shapes[-1][-1], 'route_length_m':round(length,2),
            'attribution':'© OpenStreetMap contributors','attribution_url':'https://www.openstreetmap.org/copyright',
            'location':'Bengaluru / simulated hospital' if config.scenario_id=='bengaluru-curated-demo-v1' else 'Victoria Hospital district, Bengaluru',
            'destination_label':'Demo hospital' if config.scenario_id=='bengaluru-curated-demo-v1' else 'Hospital',
            'ordinary_vehicle_count':len(vehicles)-1,
            'scenario_note':'Curated synthetic peak traffic and signal plan; simulated hospital destination on real OSM roads.' if config.scenario_id=='bengaluru-curated-demo-v1' else 'Synthetic traffic on OSM geometry.',
            'network_sha256':sha256(config.network_file)}


class LiveTelemetry:
    def __init__(self, stream, signals, dispatch, interval_s=.2):
        if not math.isfinite(interval_s) or not .2 <= interval_s <= 2:
            raise ValueError('Telemetry interval must be between 0.2 and 2 seconds.')
        self.interval_s = interval_s
        self.stream, self.signals, self.dispatch = stream, signals, dispatch
        self.next_frame = dispatch
        self.types = {}
        self.last_position = None
        self.finished = False
        self.last_frame = None

    def start(self, connection):
        pass

    def tick(self,c,now,snapshots,recorder,collisions,teleports):
        if now+1e-8<self.next_frame or self.finished:
            return
        import traci.constants as tc
        self.next_frame = now+self.interval_s
        vehicles = []
        for vid,data in snapshots.items():
            if vid not in self.types:
                self.types[vid] = c.vehicle.getTypeID(vid)
            position = data[tc.VAR_POSITION]
            vehicles.append([vid,round(position[0],2),round(position[1],2),round(data[tc.VAR_ANGLE],2),
                             round(data[tc.VAR_SPEED],3),self.types[vid]])
        vid = 'ambulance-0'
        departure = recorder.departures.get(vid)
        arrival = recorder.arrivals.get(vid)
        active = snapshots.get(vid)
        if active:
            self.last_position = list(active[tc.VAR_POSITION])
        ambulance = {'departed':departure is not None,'arrived':arrival is not None,
                     'departure_s':departure,'arrival_s':arrival,
                     'travel_s':None if departure is None else round((arrival or now)-departure,3),
                     'stopped_s':round(recorder.stopped.get(vid,0),3),
                     'red_wait_s':round(sum(r['stopped_on_red_s'] for r in recorder.approaches.values() if r['vehicle']==vid),3),
                     'speed_mps':round(active[tc.VAR_SPEED],3) if active else 0,
                     'stops':recorder.stops.get(vid,0),'position':self.last_position,
                     'distance_m':round(c.vehicle.getDistance(vid),2) if active else None}
        states = {s['id']:c.trafficlight.getRedYellowGreenState(s['id'])[s['link']] for s in self.signals}
        self.last_frame = {'time_s':round(now,3),'vehicles':vehicles,'ambulance':ambulance,
                          'signals':states,'collisions':collisions,'teleports':teleports}
        self.stream.write(json.dumps(self.last_frame,allow_nan=False)+'\n')
        self.stream.flush()
        self.finished = arrival is not None

    def finalize(self,result):
        """Replace step-observed arrival with authoritative tripinfo, at the same map time."""
        if self.last_frame is None or result.failure or not result.journeys[0].completed:
            return
        journey = result.journeys[0]
        self.last_frame['ambulance'].update(departure_s=journey.actual_departure_s,
            arrival_s=journey.arrival_s,travel_s=journey.journey_time_s,stopped_s=journey.stopped_time_s)
        self.stream.write(json.dumps(self.last_frame,allow_nan=False)+'\n')
        self.stream.flush()


class LiveSession:
    """Two owned native workers, complete on-disk receipts, bounded lifetime."""
    def __init__(self, settings: DemoSettings, base: Path, map_data: dict):
        self.id = uuid.uuid4().hex
        self.directory = base/self.id
        self.receipt = prepare_inputs(settings,self.directory)
        self.settings = settings
        self.signals = map_data['signals']
        self.processes = {}
        self.logs = []
        self.frames = {'baseline':[],'zelvo':[]}
        self.offsets = {'baseline':0,'zelvo':0}
        self.results = {}
        self.errors = {}
        self.status = 'starting'
        self.started = self.last_client = time.monotonic()
        self.finished_at = None
        self.clients = 0
        self.task = None
        self.sequential = os.environ.get('ZELVO_WORKER_MODE','parallel') == 'sequential'

    def start_worker(self, side, policy):
        work = self.directory/side
        work.mkdir()
        atomic_json(work/'signals.json',json.dumps(self.signals))
        log = (work/'worker.log').open('w',encoding='utf-8')
        self.logs.append(log)
        command = [sys.executable,'-m','zelvo.live_worker',str(self.directory/'scenario.json'),
                   str(work),policy,str(MODEL),str(self.settings.dispatch_s)]
        self.processes[side] = subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def start(self):
        self.status = 'running'
        try:
            self.start_worker('baseline','actuated')
            if not self.sequential:
                self.start_worker('zelvo','zelvo_ai')
        except Exception:
            self.cancel()
            raise

    def read_frames(self,side):
        path = self.directory/side/'frames.jsonl'
        if not path.exists():
            return
        with path.open('r',encoding='utf-8') as f:
            f.seek(self.offsets[side])
            while True:
                offset = f.tell()
                line = f.readline()
                if not line or not line.endswith('\n'):
                    f.seek(offset)
                    break
                self.frames[side].append(json.loads(line))
            self.offsets[side] = f.tell()

    def poll(self):
        for side,process in self.processes.items():
            self.read_frames(side)
            if process.poll() is not None and side not in self.results and side not in self.errors:
                result = self.directory/side/'result.json'
                if result.exists():
                    self.results[side] = json.loads(result.read_text(encoding='utf-8'))
                    if self.results[side]['failure'] and self.status in ('starting','running'):
                        self.errors[side] = self.results[side]['failure']['message']
                elif self.status in ('starting','running'):
                    self.errors[side] = worker_startup_error(self.directory/side/'worker.log')
        if self.status in ('running','starting'):
            if self.errors:
                self.cancel('failed')
            elif self.sequential and 'baseline' in self.results and 'zelvo' not in self.processes:
                try:
                    self.start_worker('zelvo','zelvo_ai')
                except Exception:
                    self.errors['zelvo'] = 'Could not start the ZELVO simulation worker.'
                    self.cancel('failed')
            elif len(self.results)==2:
                self.status = 'complete'
                self.finish()

    def finish(self):
        if self.finished_at is None:
            self.finished_at = datetime.now(timezone.utc).isoformat()
        for log in self.logs:
            if not log.closed:
                log.close()
        atomic_json(self.directory/'receipt.json',json.dumps(self.summary(),indent=2))

    def cancel(self,status='cancelled'):
        self.status = status
        for side,process in self.processes.items():
            (self.directory/side/'STOP').touch()
        # STOP lets the runner close SUMO and save partial measurements first.

    async def watch(self):
        try:
            while True:
                self.poll()
                elapsed = time.monotonic()-self.started
                if self.status in ('running','starting') and (elapsed>940 or (not self.clients and time.monotonic()-self.last_client>60)):
                    self.cancel('expired')
                if self.status not in ('running','starting'):
                    deadline = time.monotonic()+8
                    for process in self.processes.values():
                        while process.poll() is None and time.monotonic()<deadline:
                            await asyncio.sleep(.1)
                        if process.poll() is None:
                            process.terminate()
                            await asyncio.to_thread(process.wait,5)
                    self.poll()
                    self.finish()
                    break
                await asyncio.sleep(.1)
        finally:
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
            for log in self.logs:
                if not log.closed:
                    log.close()

    def summary(self):
        return {'id':self.id,'status':self.status,'inputs':self.receipt,'errors':self.errors,
                'execution_mode':'sequential' if self.sequential else 'parallel',
                'finished_at_utc':self.finished_at,
                'worker_exit_codes':{k:p.poll() for k,p in self.processes.items()},
                'partial_run':self.status!='complete',
                'frames':{k:len(v) for k,v in self.frames.items()},'results':self.results}


class SessionManager:
    def __init__(self,base=None):
        self.base = base or ROOT/'results/live'
        self.sessions = {}
        self.map_data = None
        self.expanded_map_data = None
        self.curated_map_data = None

    def get_geometry(self, corridor='reference'):
        if corridor == 'curated':
            if self.curated_map_data is None:
                self.curated_map_data = geometry(CURATED)
            return self.curated_map_data
        if corridor == 'expanded':
            if self.expanded_map_data is None:
                self.expanded_map_data = geometry(EXPANDED)
            return self.expanded_map_data
        if self.map_data is None:
            self.map_data = geometry()
        return self.map_data

    def create(self,settings):
        # Do not allocate another pair until all previous owned workers have exited.
        if any(p.poll() is None for s in self.sessions.values() for p in s.processes.values()):
            raise RuntimeError('A comparison is already running. Stop it before starting another.')
        for key in list(self.sessions):
            if len(self.sessions)>=4:
                del self.sessions[key]
        session = LiveSession(settings,self.base,self.get_geometry(settings.corridor))
        self.sessions[session.id] = session
        session.start()
        session.task = asyncio.create_task(session.watch())
        return session

    async def close(self):
        tasks = []
        for session in self.sessions.values():
            if session.task and not session.task.done():
                session.cancel()
                tasks.append(session.task)
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)

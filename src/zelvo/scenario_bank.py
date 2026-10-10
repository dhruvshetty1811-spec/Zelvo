"""Seeded OSM experiment inputs; scenario selection never uses run outcomes."""
from collections import defaultdict
import copy
import json
from pathlib import Path
import random
import shutil
import xml.etree.ElementTree as ET

from zelvo.network import make_scenario
from zelvo.simulation.smoke import sha256

FAMILIES = ('standard_one', 'following_pair', 'competing_pair', 'queued_corridor',
            'downstream_incident', 'burst_demand', 'stale_telemetry',
            'delayed_telemetry', 'rerouting_incident', 'pedestrian_peak')
CONTROLLERS = ('fixed_time', 'actuated', 'local_preemption', 'zelvo_analytical', 'zelvo_ai')


def save_routes(path, definitions, demand):
    root=ET.Element('routes')
    root.extend(copy.deepcopy(definitions))
    root.extend(sorted(demand,key=lambda child:float(child.get('depart','0'))))
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)


def prepare_bank(root: Path, directory: Path, *, seeds, levels, horizon=900, wall_timeout=1200):
    """Prepare shared background demand once; variants change explicit interventions.

    Road OD paths are resampled from a saved, validated road-route pool. Evaluation
    seeds/demand differ from training; no claim of unseen-city/route testing is made.
    """
    root=root.resolve()
    directory=directory.resolve()
    if not seeds or not levels or min(levels)<60 or len(set(seeds))!=len(seeds) or len(set(levels))!=len(levels):
        raise ValueError('Unique seeds and demand levels >=60 are required')
    inputs=root/'inputs'
    configs=root/'configs'
    inputs.mkdir(parents=True,exist_ok=True)
    configs.mkdir(exist_ok=True)
    for name in ('district.net.xml','registry.json'):
        shutil.copyfile(directory/name,inputs/name)
    network=ET.parse(inputs/'district.net.xml').getroot()
    edges={edge.get('id') for edge in network.findall('edge')}
    connections={(c.get('from'),c.get('to')) for c in network.findall('connection')}
    lanes={lane.get('id'):lane for edge in network.findall('edge') for lane in edge.findall('lane')}
    registry=json.loads((inputs/'registry.json').read_text(encoding='utf-8'))
    controlled=defaultdict(list)
    for m in registry['movements']:
        controlled[(m['from_edge'],m['to_edge'])].append(m)
    pool=defaultdict(set)
    definitions=None
    pool_hashes={}
    rejected=0
    # Fixed explicit inputs, not whatever unrelated files happen to be in a folder.
    sources=[directory/'seed-42-demand-300-ev-2-od-0.rou.xml']
    for seed in range(1000,1008):
        sources.extend(sorted(directory.glob(f'seed-{seed}-demand-*-ev-*-od-*.rou.xml')))
    for path in sources:
        document=ET.parse(path).getroot()
        if definitions is None:definitions=document.findall('vType')
        pool_hashes[path.name]=sha256(path)
        for vehicle in document.findall('vehicle'):
            if vehicle.get('type') not in ('car','bike','bus'):continue
            route=tuple(vehicle.find('route').get('edges').split())
            if not all(edge in edges for edge in route) or any(pair not in connections for pair in zip(route,route[1:])):
                rejected+=1
                continue
            pool[vehicle.get('type')].add(route)
    if not definitions or any(not pool[kind] for kind in ('car','bike','bus')):
        raise ValueError('A validated car/bike/bus route pool is required')
    pool={kind:sorted(routes) for kind,routes in pool.items()}
    pedestrian_source=directory/'seed-42-demand-300-ev-2-od-0-ped-60.rou.xml'
    walking=ET.parse(pedestrian_source).getroot().findall('person')
    pool_hashes[pedestrian_source.name]=sha256(pedestrian_source)
    if not walking:raise ValueError('Saved synthetic walking routes are required')
    assets={}
    def asset(path):
        assets[path.relative_to(root).as_posix()]=sha256(path)
        return path.relative_to(root).as_posix()
    asset(inputs/'district.net.xml')
    asset(inputs/'registry.json')
    scenarios=[]
    for seed in seeds:
        # Geometry-only selection: reject receiving links below 10 m. Never inspect outcomes.
        template=make_scenario(inputs,seed=seed,demand=0,emergencies=2,horizon=horizon,min_receiving_m=10)
        metadata=json.loads(template.with_suffix('.metadata.json').read_text(encoding='utf-8'))
        candidates=metadata['emergency_route_candidates']
        if len(candidates)<5:raise ValueError('Five distinct hospital OD paths required')
        asset(template.with_suffix('.metadata.json'))
        rng=random.Random(seed)
        background=[]
        for i in range(max(levels)):
            kind=rng.choices(('car','bike','bus'),(70,25,5))[0]
            vehicle=ET.Element('vehicle',id=f'traffic-{i}',type=kind,depart=f'{rng.uniform(0,300):.1f}',departLane='best')
            ET.SubElement(vehicle,'route',edges=' '.join(rng.choice(pool[kind])))
            background.append(vehicle)
        walkers=[]
        for i in range(60):
            person=copy.deepcopy(rng.choice(walking))
            person.set('id',f'walker-{i}')
            person.set('depart',f'{rng.uniform(30,300):.1f}')
            walkers.append(person)
        person_path=inputs/f'walkers-{seed}.rou.xml'
        save_routes(person_path,[],walkers)
        asset(person_path)
        for level in levels:
            for style in ('ordinary','burst','excluding-queue'):
                traffic=copy.deepcopy(background[:level])
                if style=='burst':
                    for vehicle in traffic:vehicle.set('depart',f"{30+float(vehicle.get('depart'))*.4:.1f}")
                if style=='excluding-queue':traffic=traffic[min(60,level):]
                path=inputs/f'background-{seed}-{level}-{style}.rou.xml'
                save_routes(path,definitions,traffic)
                asset(path)
        for od in range(5):
            route=candidates[od]
            alternative=candidates[(od+1)%len(candidates)]
            movements=[controlled[pair][0] for pair in zip(route,route[1:]) if pair in controlled]
            if not movements:raise ValueError('Selected ambulance route has no controlled movements')
            # Choose the longest receiving link, from geometry alone, for incidents.
            incident_movement=max(movements,key=lambda m:m['length_m'])
            incident_lane=incident_movement['outgoing']
            lane_limit=float(lanes[incident_lane].get('speed'))
            ambulance_paths={}
            for style in ('one','following','competing'):
                vehicles=[]
                for i in range(1 if style=='one' else 2):
                    vehicle=ET.Element('vehicle',id=f'ambulance-{i}',type='ambulance',
                        depart=str(60+i*8),departLane='best')
                    ET.SubElement(vehicle,'route',edges=' '.join(alternative if i and style=='competing' else route))
                    vehicles.append(vehicle)
                path=inputs/f'ambulances-{seed}-{od}-{style}.rou.xml'
                save_routes(path,[],vehicles)
                ambulance_paths[style]=path
                asset(path)
            queue=[]
            for i in range(min(60,min(levels))):
                vehicle=ET.Element('vehicle',id=f'traffic-{i}',type='car',depart=f'{i*.75:.1f}',departLane='best')
                ET.SubElement(vehicle,'route',edges=' '.join(route))
                queue.append(vehicle)
            queue_path=inputs/f'corridor-queue-{seed}-{od}.rou.xml'
            save_routes(queue_path,[],queue)
            asset(queue_path)
            for level in levels:
                for family in FAMILIES:
                    style={'following_pair':'following','competing_pair':'competing'}.get(family,'one')
                    background_style='burst' if family=='burst_demand' else ('excluding-queue' if family=='queued_corridor' else 'ordinary')
                    files=[inputs/f'background-{seed}-{level}-{background_style}.rou.xml',ambulance_paths[style]]
                    if family=='queued_corridor':files.append(queue_path)
                    if family=='pedestrian_peak':files.append(person_path)
                    scenario_id=f'{family}-s{seed}-d{level}-o{od}'
                    config={'schema_version':'1.0','scenario_id':scenario_id,'seed':seed,'controller':'actuated',
                        'network_file':str(inputs/'district.net.xml'),'route_files':list(map(str,files)),
                        'step_length_s':.1,'horizon_s':horizon,'wall_timeout_s':wall_timeout,'backend':'libsumo',
                        'expected_journeys':[{'vehicle_id':f'ambulance-{i}','scheduled_departure_s':60+i*8}
                            for i in range(1 if style=='one' else 2)],
                        'observation_delay_s':5 if family=='stale_telemetry' else (1 if family=='delayed_telemetry' else 0),
                        'dynamic_routing':family=='rerouting_incident','incidents':[]}
                    if family in ('downstream_incident','rerouting_incident'):
                        config['incidents']=[{'lane':incident_lane,'start_s':80,'end_s':200,
                            'speed_mps':0 if family=='downstream_incident' else min(1,lane_limit)}]
                    path=configs/(scenario_id+'.json')
                    path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
                    asset(path)
                    scenarios.append({'scenario_id':scenario_id,'seed':seed,'demand':level,'od':od,'family':family,
                        'config':path.relative_to(root).as_posix(),'controlled_movements':len(movements),
                        'minimum_receiving_link_m':min(m['length_m'] for m in movements)})
        print(json.dumps({'prepared_seed':seed,'scenarios':len(scenarios)}),flush=True)
    return scenarios,assets,{'route_pool_hashes':pool_hashes,'pool_routes':{k:len(v) for k,v in pool.items()},
        'rejected_pool_routes':rejected,'demand_calibration':'Synthetic OD resampling, not field-calibrated demand',
        'route_selection':'Seeded hospital-bound OSM shortest paths; receiving links >=10m; no outcomes used',
        'dependence':'Demand prefixes and OD paths reused across variants; inference clusters by entire seed',
        'queue_family':'First 60 ordinary vehicles follow the ambulance corridor before departure; total demand preserved'}

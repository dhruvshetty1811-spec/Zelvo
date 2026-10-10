"""Reproducible OSM compilation, lane-level movement registry and demand."""
from pathlib import Path
import json
import random
import subprocess
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
import uuid

import sumolib

from zelvo.runtime import child_environment, discover_tools, installed_sumo_environment
from zelvo.simulation.smoke import sha256, atomic_json


def registry(network_file: Path) -> dict:
    root = ET.parse(network_file).getroot()
    lanes = {lane.attrib['id']: {**lane.attrib, 'edge': edge.attrib['id']}
             for edge in root.findall('edge') for lane in edge.findall('lane')}
    programs = {}
    for tls in root.findall('tlLogic'):
        phases = [dict(p.attrib) for p in tls.findall('phase')]
        programs[tls.attrib['id']] = {'type': tls.attrib['type'], 'phases': phases}
    movements = []
    uncontrolled_crossings = []
    for c in root.findall('connection'):
        a = c.attrib
        if 'tl' not in a:
            continue
        if a['tl'] not in programs:
            # netconvert annotates some priority pedestrian crossings with tl/linkIndex
            # despite having no program. These are not controllable signal movements.
            junction = next((j for j in root.findall('junction') if j.get('id')==a['tl']),None)
            if junction is not None and junction.get('type')=='priority' and a.get('state')=='M':
                uncontrolled_crossings.append(dict(a))
                continue
            raise ValueError('Connection references absent signal program: '+a['tl'])
        incoming = a['from'] + '_' + a['fromLane']
        outgoing = a['to'] + '_' + a['toLane']
        index = int(a['linkIndex'])
        if incoming not in lanes or outgoing not in lanes:
            raise ValueError('Controlled connection references missing lane')
        states = [p['state'] for p in programs[a['tl']]['phases']]
        if any(index >= len(s) for s in states):
            raise ValueError('Controlled link index outside signal state')
        movements.append({'tls': a['tl'], 'index': index, 'incoming': incoming,
                          'outgoing': outgoing, 'via': a.get('via'),
                          'from_edge': a['from'], 'to_edge': a['to'],
                          'length_m': float(lanes[outgoing]['length']),
                          'direction': a.get('dir'),
                          'protected_phases': [i for i,s in enumerate(states) if s[index] == 'G']})
    return {'schema_version': '1.0', 'network_sha256': sha256(network_file),
            'uncontrolled_crossing_annotations':uncontrolled_crossings,
            'controllers': programs, 'movements': movements,
            'counts': {'controllers':len(programs), 'movements':len(movements),
                       'external_edges':len([e for e in root.findall('edge') if not e.attrib['id'].startswith(':')]),
                       'lanes':len(lanes)},
            'review_required': ['OSM-inferred signals are not surveyed signal plans',
                                'hospital endpoint is road access, not a modelled hospital entrance',
                                'pedestrian crossings and joined controllers need field validation']}


def repair_orphan_crossings(network_file: Path) -> list[dict]:
    """SUMO 1.26 netconvert may leave tl attributes on unsignalized crossings.

    Only remove orphan control metadata on walkingarea->crossing links at an
    explicitly priority junction. Any other unresolved controller is an error.
    """
    tree=ET.parse(network_file)
    root=tree.getroot()
    programs={p.get('id') for p in root.findall('tlLogic')}
    junctions={j.get('id'):j.get('type') for j in root.findall('junction')}
    functions={e.get('id'):e.get('function') for e in root.findall('edge')}
    patches=[]
    for c in root.findall('connection'):
        a=c.attrib
        if a.get('tl') and a['tl'] not in programs:
            if not (junctions.get(a['tl'])=='priority' and a.get('state')=='M'
                    and functions.get(a['from'])=='walkingarea' and functions.get(a['to'])=='crossing'):
                raise ValueError('Cannot repair unexplained missing controller '+a['tl'])
            patches.append(dict(a))
            del a['tl']
            a.pop('linkIndex',None)
    if patches:
        tree.write(network_file,encoding='utf-8',xml_declaration=True)
    return patches


def build_district(directory: Path, *, source: Path | None = None, bbox=None) -> dict:
    directory = directory.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    runtime = discover_tools()
    source = source.resolve() if source else directory / 'district.osm.xml'
    output = directory / 'district.net.xml'
    if not source.is_file():
        raise ValueError('Download the OSM extract with node --use-system-ca scripts/fetch-osm.mjs')
    options = ['--osm-files', str(source), '--output-file', str(output),
               '--lefthand', 'true', '--geometry.remove', 'true',
               '--junctions.join', 'true', '--tls.guess', 'true', '--tls.guess-signals', 'true',
               '--tls.join', 'true', '--tls.join-dist', '10',
               '--tls.default-type', 'actuated', '--tls.allred.time', '2',
               '--tls.yellow.time', '3', '--no-turnarounds', 'true',
               '--keep-edges.by-vclass', 'passenger,pedestrian',
               '--osm.sidewalks', 'true', '--crossings.guess', 'true',
               '--remove-edges.isolated', 'true', '--output.original-names', 'true']
    # Preserve separate OSM junctions where the automatic merge produced
    # overlapping vehicle paths in an observed junction-collision diagnostic.
    junction_join_exclusions=['1277414211','249137297','10026725123','10028793385','429231026','429231031']
    options += ['--junctions.join-exclude',','.join(junction_join_exclusions)]
    if bbox:
        if len(bbox)!=4 or not bbox[0]<bbox[2] or not bbox[1]<bbox[3]:
            raise ValueError('BBox must be west,south,east,north')
        options += ['--keep-edges.in-geo-boundary',','.join(map(str,bbox))]
    # This serial four-junction cluster emitted missing-actuation-detector warnings
    # and failed the downstream-clearance pilot. Retain independent controllers.
    serial_join_exclusions=['570758310','9939398569','9939398599','9939407828']
    options += ['--tls.join-exclude',','.join(serial_join_exclusions)]
    # The saved command is the exact reproducible configuration, including every heuristic.
    atomic_json(directory / 'netconvert-options.json', json.dumps(options, indent=2))
    result = subprocess.run([str(runtime.netconvert_binary), *options],
                            capture_output=True, text=True, timeout=180,
                            env=child_environment(runtime))
    (directory / 'netconvert.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    result.check_returncode()
    # Oversized joined controllers often merge distinct intersections into one
    # very long cycle. Recompile those members separately instead of trimming
    # phase clearance or hiding warnings. Original junction geometry is retained.
    tree = ET.parse(output).getroot()
    excluded = set(serial_join_exclusions)
    oversized = []
    for logic in tree.findall('tlLogic'):
        duration = sum(float(p.attrib['duration']) for p in logic.findall('phase'))
        if duration>180 and logic.attrib['id'].startswith('joinedS_'):
            members = logic.attrib['id'][8:].split('_')
            if all(m.isdigit() for m in members):
                excluded.update(members)
                oversized.append({'id':logic.attrib['id'],'cycle_s':duration,'members':members})
    if oversized:
        options[options.index('--tls.join-exclude')+1]=','.join(sorted(excluded))
        atomic_json(directory/'netconvert-options.json',json.dumps(options,indent=2))
        result = subprocess.run([str(runtime.netconvert_binary),*options],capture_output=True,
                                text=True,timeout=180,env=child_environment(runtime))
        (directory/'netconvert.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        result.check_returncode()
    crossing_repairs=repair_orphan_crossings(output)
    atomic_json(directory/'topology-refinements.json',json.dumps({
        'rule':'Do not join numeric OSM signal clusters with nominal cycle above 180s',
        'excluded_joins':oversized,'manual_geometry_patches':[],
        'serial_join_exclusions':serial_join_exclusions,
        'serial_join_exclusion_reason':'Missing controlling detectors and observed serial-junction clearance deadlock',
        'junction_join_exclusions':junction_join_exclusions,
        'junction_join_exclusion_reason':'Observed overlapping paths at the merged junction; retain original separate nodes',
        'orphan_priority_crossing_control_metadata_removed':crossing_repairs,
        'note':'Heuristic model review, not surveyed signal validation'},indent=2))
    data = registry(output)
    data['source_sha256'] = sha256(source)
    data['source_file'] = str(source)
    data['clipped_bbox_west_south_east_north'] = bbox
    data['netconvert_version'] = runtime.versions['netconvert']
    atomic_json(directory / 'registry.json', json.dumps(data, indent=2))
    return data['counts']


def make_scenario(directory: Path, *, seed: int = 42, demand: int = 600,
                  emergencies: int = 1, horizon: float = 900, route_index: int = 0,
                  min_receiving_m: float = 0) -> Path:
    """Fixed seeded demand/routes shared byte-for-byte by all controllers."""
    if not 0<=seed<=2**31-1 or demand<0 or not 1<=emergencies<=8 or horizon<=60+(emergencies-1)*8 or min_receiving_m<0:
        raise ValueError('Invalid seed, demand, emergency count or horizon')
    directory = directory.resolve()
    network_file = directory / 'district.net.xml'
    net = sumolib.net.readNet(str(network_file))
    rng = random.Random(seed)
    edges = sorted([e for e in net.getEdges() if e.allows('passenger') and e.getLength() > 30],
                   key=lambda e:e.getID())
    arterial_types={'highway.primary','highway.secondary','highway.tertiary','highway.trunk',
                    'highway.primary_link','highway.secondary_link','highway.tertiary_link','highway.trunk_link'}
    bus_edges=[e for e in edges if e.getType() in arterial_types and e.allows('bus')]
    # Victoria Hospital area, Bengaluru. Endpoint is explicitly a nearby road access.
    try:
        x,y = net.convertLonLat2XY(77.5747,12.9630)
    except ImportError:
        # SUMO's own PROJ support remains available if the optional Python
        # projection wheel cannot be downloaded. Use the identical network CRS.
        import traci
        runtime=discover_tools()
        label='projection-'+uuid.uuid4().hex
        with (directory/'projection.log').open('w',encoding='utf-8') as log:
            with installed_sumo_environment(runtime),redirect_stdout(log):
                traci.start([str(runtime.sumo_binary),'--net-file',str(network_file),
                             '--no-step-log','true'],label=label,doSwitch=False,stdout=log)
            connection=traci.getConnection(label)
            try:x,y=connection.simulation.convertGeo(77.5747,12.9630,fromGeo=True)
            finally:connection.close()
    access_edges=bus_edges or edges
    target = min(access_edges, key=lambda e: sumolib.geomhelper.distancePointToPolygon((x,y),e.getShape()))
    candidates = []
    movement_data=json.loads((directory/'registry.json').read_text(encoding='utf-8'))
    controlled_pairs={(m['from_edge'],m['to_edge']):m['tls'] for m in movement_data['movements']
                      if not m['from_edge'].startswith(':')}
    receiving_lengths={}
    for movement in movement_data['movements']:
        pair=(movement['from_edge'],movement['to_edge'])
        if pair in controlled_pairs:
            receiving_lengths.setdefault(pair,[]).append(movement['length_m'])
    origins = rng.sample(edges,min(180,len(edges)))
    for edge in origins:
        route,cost = net.getShortestPath(edge,target,vClass='passenger')
        if route and cost > 600:
            ids=[e.getID() for e in route]
            if min_receiving_m and any(min(receiving_lengths.get((a,b),[float('inf')]))<min_receiving_m
                                       for a,b in zip(ids,ids[1:])):
                continue
            controlled = sum((a,b) in controlled_pairs for a,b in zip(ids,ids[1:]))
            candidates.append((controlled,cost,tuple(e.getID() for e in route)))
    candidates.sort(reverse=True)
    if len(candidates) < 5:
        raise ValueError('District lacks five connected hospital-bound routes')
    # Distinct source routes, favour many controlled intersections without artificial signals.
    selected = candidates[route_index % min(5,len(candidates))][2]
    root = ET.Element('routes')
    for name,vclass,length,accel in [('car','passenger',4.5,2.6),('bike','motorcycle',2,3),
                                    ('bus','bus',10,1.3),('ambulance','passenger',5.5,2.8)]:
        ET.SubElement(root,'vType',id=name,vClass=vclass,length=str(length),accel=str(accel),
                      decel='4.5',sigma='0.5',minGap='2.5',maxSpeed='16.67',
                      guiShape='emergency' if name=='ambulance' else ('bus' if name=='bus' else ('motorcycle' if name=='bike' else 'passenger')))
    vehicles = []
    for i in range(demand):
        desired_type=rng.choices(['car','bike','bus'],[70,25,5])[0]
        fallback_route=None
        inserted=False
        for _ in range(30):
            origin,destination = rng.sample(bus_edges if desired_type=='bus' and len(bus_edges)>=2 else edges,2)
            route,cost = net.getShortestPath(origin,destination,vClass='passenger')
            if route and 400 < cost < 8000:
                fallback_route=route
                vehicle_type = desired_type
                if vehicle_type=='bus' and not all(e.getType() in arterial_types for e in route):
                    continue
                # Some restricted edges cannot accept buses/bikes; keep valid routes.
                vclass = {'car':'passenger','bike':'motorcycle','bus':'bus'}[vehicle_type]
                if not all(e.allows(vclass) for e in route):
                    vehicle_type = 'car'
                vehicles.append((rng.uniform(0,300),f'traffic-{i}',vehicle_type,tuple(e.getID() for e in route)))
                inserted=True
                break
        if not inserted:
            if fallback_route is None:
                raise ValueError('Could not generate requested connected OD demand; adjust district or seed')
            vehicles.append((rng.uniform(0,300),f'traffic-{i}','car',tuple(e.getID() for e in fallback_route)))
    expected = []
    for i in range(emergencies):
        route = selected if i % 2 == 0 else candidates[(route_index+1)%len(candidates)][2]
        depart = 60+i*8
        vehicles.append((depart,f'ambulance-{i}','ambulance',route))
        expected.append({'vehicle_id':f'ambulance-{i}','scheduled_departure_s':depart})
    for depart,vid,kind,route in sorted(vehicles):
        vehicle = ET.SubElement(root,'vehicle',id=vid,type=kind,depart=f'{depart:.1f}',departLane='best',departSpeed='0')
        ET.SubElement(vehicle,'route',edges=' '.join(route))
    name = f'seed-{seed}-demand-{demand}-ev-{emergencies}-od-{route_index}'
    if min_receiving_m:name += f'-storage-{min_receiving_m:g}'
    routes = directory / (name+'.rou.xml')
    ET.indent(root)
    ET.ElementTree(root).write(routes,encoding='utf-8',xml_declaration=True)
    config = {'scenario_id':name,'seed':seed,'controller':'actuated','network_file':'district.net.xml',
              'route_files':[routes.name],'step_length_s':0.1,'horizon_s':horizon,
              'wall_timeout_s':600,'expected_journeys':expected}
    config_path = directory / (name+'.json')
    atomic_json(config_path,json.dumps(config,indent=2))
    metadata={
        'name':'Victoria Hospital road access (model approximation)',
        'reference_lon_lat':[77.5747,12.9630], 'target_edge':target.getID(),
        'selected_route_edges':selected,'candidate_routes':len(candidates),
        'emergency_route_candidates':[candidate[2] for candidate in candidates[:6]],
        'minimum_receiving_link_m':min_receiving_m,
        'selected_controlled_movements':sum((a,b) in controlled_pairs for a,b in zip(selected,selected[1:])),
        'generated_types':{kind:sum(v[2]==kind for v in vehicles) for kind in ('car','bike','bus','ambulance')},
        'requested_traffic':demand,'generated_traffic':len(vehicles)-emergencies,
        'pedestrian_demand':0,'note':'Sidewalk/crossing topology imported; district pedestrian demand not calibrated.'}
    atomic_json(directory / (name+'.metadata.json'),json.dumps(metadata,indent=2))
    atomic_json(directory / 'hospital-access.json',json.dumps(metadata,indent=2))
    return config_path

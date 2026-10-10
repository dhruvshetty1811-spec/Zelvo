"""Add reproducible, explicitly synthetic walking demand to a saved scenario.

This keeps the original matched experiment intact. SUMO computes walking routes
from the imported sidewalk/crossing topology. Demand is not field calibrated.
"""
import argparse
import json
import os
from pathlib import Path
import random
import xml.etree.ElementTree as ET

import sumolib
from zelvo.config import load_scenario

parser = argparse.ArgumentParser()
parser.add_argument('config', type=Path)
parser.add_argument('--people', type=int, default=60)
args = parser.parse_args()
if args.people < 1:
    parser.error('--people must be positive')
config = load_scenario(args.config)
net = sumolib.net.readNet(str(config.network_file))
edges = [e for e in net.getEdges() if e.allows('pedestrian') and e.allows('passenger')]
rng = random.Random(config.seed + 9127)
root = ET.Element('routes')
for route_file in config.route_files:
    root.extend(ET.parse(route_file).getroot())
walks = []
for i in range(args.people):
    for attempt in range(200):
        origin = rng.choice(edges)
        neighbours = [edge for edge, distance in net.getNeighboringEdges(*origin.getShape()[-1], r=250)
            if edge != origin and edge in edges]
        if not neighbours:
            continue
        destination = rng.choice(neighbours)
        route, cost = net.getShortestPath(origin, destination, vClass='pedestrian',
            ignoreDirection=True, maxCost=600)
        if route and len(route) > 1 and 50 < cost < 600:
            break
    else:
        raise ValueError('Could not construct connected pedestrian demand')
    depart = rng.uniform(30, min(300, config.horizon_s - 30))
    person = ET.SubElement(root, 'person', id=f'walker-{i}', depart=f'{depart:.1f}',
        departPos='random')
    ET.SubElement(person, 'walk', attrib={'from': origin.getID(), 'to': destination.getID()},
        arrivalPos='random', speed='1.4')
    walks.append({'person': f'walker-{i}', 'from': origin.getID(), 'to': destination.getID()})
# SUMO requires traffic demand to be ordered by departure, with definitions first.
definitions = [child for child in root if child.tag not in ('vehicle', 'person', 'flow')]
demand = sorted((child for child in root if child.tag in ('vehicle', 'person', 'flow')),
    key=lambda child: float(child.get('depart', child.get('begin', '0'))))
root[:] = definitions + demand
stem = args.config.stem + f'-ped-{args.people}'
route_path = args.config.with_name(stem + '.rou.xml').resolve()
ET.ElementTree(root).write(route_path, encoding='utf-8', xml_declaration=True)
updated = config.model_copy(update={'scenario_id': stem, 'route_files': (route_path,)})
path = args.config.with_name(stem + '.json')
payload = updated.model_dump(mode='json')
payload['network_file'] = os.path.relpath(config.network_file, path.parent.resolve())
payload['route_files'] = [route_path.name]
path.write_text(json.dumps(payload, indent=2)+'\n', encoding='utf-8')
path.with_suffix('.metadata.json').write_text(json.dumps({
    'source_scenario': str(args.config), 'people': args.people, 'seed': config.seed,
    'calibration': 'Synthetic walking demand; no measured pedestrian OD counts',
    'walks': walks}, indent=2)+'\n', encoding='utf-8')
print(path)

"""Save a geometry-selected longer-route baseline pilot with reproducible demand."""
import argparse
import copy
import json
from pathlib import Path
import random
import xml.etree.ElementTree as ET
from zelvo.simulation.smoke import sha256

parser=argparse.ArgumentParser()
parser.add_argument('--demand',type=int,default=2400)
parser.add_argument('--seed',type=int,default=2026)
args=parser.parse_args()
if args.demand<0:raise ValueError('Demand must be nonnegative')
directory=Path('scenarios/bengaluru').resolve()
inventory=Path('reports/long-corridor-inventory-storage-10.json')
data=json.loads(inventory.read_text())
if sha256(directory/'district.net.xml')!=data['network_sha256']:raise ValueError('Stale geometry inventory')
selected=data['candidates'][0]
source=directory/'seed-42-demand-600-ev-2-od-0.rou.xml'
old=ET.parse(source).getroot()
pool=[v for v in old.findall('vehicle') if not v.get('id').startswith('ambulance-')]
rng=random.Random(args.seed)
root=ET.Element('routes')
root.extend(copy.deepcopy(old.findall('vType')))
vehicles=[]
for i in range(args.demand):
    vehicle=copy.deepcopy(rng.choice(pool))
    vehicle.set('id',f'long-traffic-{i}')
    vehicle.set('depart',f'{rng.uniform(0,2400):.1f}')
    vehicles.append(vehicle)
ambulance=ET.Element('vehicle',id='ambulance-0',type='ambulance',depart='600',departLane='best',departSpeed='0')
ET.SubElement(ambulance,'route',edges=' '.join(selected['route_edges']))
vehicles.append(ambulance)
root.extend(sorted(vehicles,key=lambda v:float(v.get('depart'))))
ET.indent(root)
name=f'long-corridor-s{args.seed}-d{args.demand}'
routes=directory/(name+'.rou.xml')
ET.ElementTree(root).write(routes,encoding='utf-8',xml_declaration=True)
config={'scenario_id':name,'seed':args.seed,'controller':'actuated',
    'network_file':'district.net.xml','route_files':[routes.name],
    'step_length_s':0.1,'horizon_s':4200,'wall_timeout_s':1200,'backend':'libsumo',
    'expected_journeys':[{'vehicle_id':'ambulance-0','scheduled_departure_s':600}]}
(directory/(name+'.json')).write_text(json.dumps(config,indent=2)+'\n')
metadata={'target_baseline_journey_s':[1800,2100],'actual_baseline_journey_s':None,
    'selection_source':str(inventory),'selection_source_sha256':sha256(inventory),
    'geometry_selection':selected,'background_source_sha256':sha256(source),
    'background_sampling':'Seeded resampling of saved valid full-district OD routes, uniform departures 0–2400s; original vehicle types and driving parameters retained.',
    'calibration_levels':[1200,2400,4800],
    'note':'A baseline calibration pilot, not a confirmed 30–35 minute scenario or a measured ZELVO benefit. No loops, added red time, artificial ambulance stop or changed vehicle speeds.'}
(directory/(name+'.metadata.json')).write_text(json.dumps(metadata,indent=2)+'\n')
print(directory/(name+'.json'))

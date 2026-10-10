"""Choose a hospital corridor by geometry; preserve saved background traffic."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from zelvo.simulation.smoke import sha256
from zelvo.contracts import ScenarioConfig

parser=argparse.ArgumentParser()
parser.add_argument('--queue',type=int,default=0)
parser.add_argument('--cross-traffic',type=int,default=0)
parser.add_argument('--depart',type=float,default=60)
parser.add_argument('--route-start',type=int,default=0)
parser.add_argument('--second-cross-traffic',type=int,default=0)
parser.add_argument('--second-cross-start',type=float,default=100)
args=parser.parse_args()
if args.depart<0 or args.second_cross_start<0:raise ValueError('Departure times must be nonnegative')
if not 0<=args.queue<=60:raise ValueError('Queue cohort must be between 0 and 60')
if not 0<=args.cross_traffic<=120 or not 0<=args.second_cross_traffic<=120 or args.cross_traffic+args.second_cross_traffic+args.queue>300:raise ValueError('Invalid cross traffic count')
name='demo-long-links' if not args.queue else f'demo-long-links-queue-{args.queue}'
if args.cross_traffic:name+=f'-cross-{args.cross_traffic}'
if args.depart!=60:name+=f'-depart-{args.depart:g}'
if args.route_start:name+=f'-start-{args.route_start}'
if args.second_cross_traffic:name+=f'-second-{args.second_cross_traffic}'
if args.second_cross_traffic and args.second_cross_start!=100:name+=f'-second-at-{args.second_cross_start:g}'
directory=Path('scenarios/bengaluru-hospital').resolve()
source=directory/'seed-42-demand-300-ev-2-od-0.rou.xml'
geometry=directory/'seed-42-demand-0-ev-2-od-0-storage-10.metadata.json'
metadata=json.loads(geometry.read_text())
route=metadata['selected_route_edges']
if not 0<=args.route_start<len(route)-1:raise ValueError('Route start must leave a valid hospital-bound route')
route=route[args.route_start:]
root=ET.parse(source).getroot()
for vehicle in list(root.findall('vehicle')):
    if vehicle.get('id','').startswith('ambulance-'):
        root.remove(vehicle)
for i,vehicle in enumerate(root.findall('vehicle')[:args.queue]):
    vehicle.set('type','car')
    vehicle.set('depart',f'{45+i*0.6:.1f}')
    vehicle.find('route').set('edges',' '.join(route))
for i,vehicle in enumerate(root.findall('vehicle')[args.queue:args.queue+args.cross_traffic]):
    vehicle.set('type','car')
    vehicle.set('depart',f'{60+i*1.5:.1f}')
    vehicle.find('route').set('edges','1552750442#1 162569524#0')
start=args.queue+args.cross_traffic
for i,vehicle in enumerate(root.findall('vehicle')[start:start+args.second_cross_traffic]):
    vehicle.set('type','car')
    vehicle.set('depart',f'{args.second_cross_start+i*1.5:.1f}')
    vehicle.find('route').set('edges','759364436#6 1370769169#3')
ambulance=ET.SubElement(root,'vehicle',id='ambulance-0',type='ambulance',depart=f'{args.depart:g}',departLane='best',departSpeed='0')
ET.SubElement(ambulance,'route',edges=' '.join(route))
definitions=list(root.findall('vType'))
vehicles=sorted(root.findall('vehicle'),key=lambda v:float(v.get('depart')))
root[:]=definitions+vehicles
ET.indent(root)
routes=directory/(name+'.rou.xml')
ET.ElementTree(root).write(routes,encoding='utf-8',xml_declaration=True)
config={'scenario_id':name,'seed':42,'controller':'actuated',
    'network_file':'district.net.xml','route_files':[routes.name],'step_length_s':0.1,
    'horizon_s':700,'wall_timeout_s':600,'backend':'libsumo',
    'expected_journeys':[{'vehicle_id':'ambulance-0','scheduled_departure_s':args.depart}]}
path=directory/(name+'.json')
ScenarioConfig.model_validate(config)
path.write_text(json.dumps(config,indent=2)+'\n')
registry=json.loads((directory/'registry.json').read_text())
pairs=set(zip(route,route[1:]))
movements=[m for m in registry['movements'] if (m['from_edge'],m['to_edge']) in pairs]
evidence={'selection_rule':'Underlying hospital route selected geometrically: receiving lanes >=10m, ranked by controlled movements then path length. Demo route start, departures and cross-traffic cohorts tuned using preserved measured development trials.',
    'background_source':source.name,'background_source_sha256':sha256(source),
    'geometry_source':geometry.name,'route_edges':route,'controlled_movements':movements,
    'ordinary_vehicles':len(vehicles)-1,'queue_cohort':args.queue,
    'cross_traffic_cohort':args.cross_traffic,
    'emergency_departure_s':args.depart,
    'route_start_index':args.route_start,'second_cross_traffic_cohort':args.second_cross_traffic,
    'second_cross_traffic_intervention':f'Next N ordinary trips become cars on the second opposing left turn, departing {args.second_cross_start:g}+i*1.5s; identical for both controllers.',
    'cross_traffic_intervention':'Next N ordinary trips become cars on the opposing controlled left turn, departing 60+i*1.5s; identical for both controllers.',
    'queue_intervention':'First N saved ordinary trips become cars on the emergency corridor, departing 45+i*0.6s; identical for both controllers.',
    'target':'Zero measured stopped-on-red seconds; a target, not a guaranteed outcome.',
    'note':'Curated demo tuned using development trials, separate from population evaluation; OSM-derived signal plans are not field calibrated.'}
(directory/(name+'.metadata.json')).write_text(json.dumps(evidence,indent=2)+'\n')
print(path)

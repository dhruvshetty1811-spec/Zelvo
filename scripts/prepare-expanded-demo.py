"""Build reproducible road/demand candidates; outcomes require paired trials."""
import copy
import argparse
import json
import math
from pathlib import Path
import random
import subprocess
import xml.etree.ElementTree as ET
from zelvo.network import registry, repair_orphan_crossings
from zelvo.runtime import discover_tools, child_environment
from zelvo.simulation.smoke import sha256

parser=argparse.ArgumentParser()
parser.add_argument('--inventory',type=Path,default=Path('reports/long-corridor-inventory-storage-10.json'))
parser.add_argument('--index',type=int,default=2)
parser.add_argument('--output',type=Path,default=Path('scenarios/bengaluru-expanded'))
parser.add_argument('--cross-per-signal',type=int,default=0)
parser.add_argument('--cross-only',action='store_true')
parser.add_argument('--demand',type=int,default=600)
args=parser.parse_args()
source=Path('scenarios/bengaluru')
target=args.output
target.mkdir(exist_ok=True)
inventory=args.inventory
data=json.loads(inventory.read_text())
assert sha256(source/'district.net.xml')==data['network_sha256']
candidate=data['candidates'][args.index]
route=candidate['route_edges']
original=ET.parse(source/'district.net.xml').getroot()
edges={e.get('id'):e for e in original.findall('edge')}
def samples(shape):
    points=[tuple(map(float,p.split(','))) for p in shape.split()]
    for a,b in zip(points,points[1:]):
        steps=max(1,math.ceil(math.dist(a,b)/40))
        for i in range(steps+1):
            yield a[0]+(b[0]-a[0])*i/steps,a[1]+(b[1]-a[1])*i/steps
cells=set()
for eid in route:
    for x,y in samples(edges[eid].find('lane').get('shape')):
        gx,gy=math.floor(x/100),math.floor(y/100)
        cells.update((gx+dx,gy+dy) for dx in range(-2,3) for dy in range(-2,3))
keep=set(route)
for eid,edge in edges.items():
    if not eid.startswith(':') and any((math.floor(x/100),math.floor(y/100)) in cells for x,y in samples(edge.find('lane').get('shape'))):keep.add(eid)
pairs=set(zip(route,route[1:]))
controllers={c.get('tl') for c in original.findall('connection') if (c.get('from'),c.get('to')) in pairs and c.get('tl')}
for c in original.findall('connection'):
    if c.get('tl') in controllers:keep.update([c.get('from'),c.get('to')])
# Optional opposing rush cohorts use actual protected connections in this same
# road network. Their schedule is based on geometry, never observed outcomes.
cross_routes=[]
original_reg=registry(source/'district.net.xml') if args.cross_per_signal else None
if original_reg:
    lanes={lane.get('id'):lane for edge in original.findall('edge') for lane in edge.findall('lane')}
    def passenger(lane_id):
        lane=lanes[lane_id]
        return ('passenger' in lane.get('allow').split()) if lane.get('allow') else 'passenger' not in lane.get('disallow','').split()
    links={}
    for c in original.findall('connection'):links.setdefault((c.get('from'),c.get('to')),[]).append(c)
    def internal_time(a,b):
        choices=[]
        for c in links.get((a,b),[]):
            if not passenger(a+'_'+c.get('fromLane')) or not passenger(b+'_'+c.get('toLane')):continue
            via=c.get('via');cost=0;seen=set()
            while via and via not in seen:
                seen.add(via);lane=lanes[via];cost+=float(lane.get('length'))/min(16.67,float(lane.get('speed')))
                eid=via.rsplit('_',1)[0]
                following=next((x for x in links.get((eid,b),[]) if x.get('fromLane')==lane.get('index')),None)
                via=following.get('via') if following is not None else None
            choices.append(cost)
        return min(choices,default=0)
    elapsed=60.0
    scheduled=set()
    previous_pair=None
    for a,b in zip(route,route[1:]):
        if previous_pair:elapsed+=internal_time(*previous_pair)
        previous_pair=a,b
        lane=edges[a].find('lane')
        elapsed+=float(lane.get('length'))/min(16.67,float(lane.get('speed')))
        ms=[m for m in original_reg['movements'] if m['from_edge']==a and m['to_edge']==b]
        if not ms or ms[0]['tls'] in scheduled:continue
        m=next((m for m in ms if m['protected_phases']),ms[0])
        phases=original_reg['controllers'][m['tls']]['phases']
        opposing=[x for x in original_reg['movements'] if x['tls']==m['tls'] and x['from_edge']!=a
                  and passenger(x['incoming']) and passenger(x['outgoing']) and x['to_edge']!=b
                  and x['protected_phases'] and x['length_m']>=30
                  and float(edges[x['from_edge']].find('lane').get('length'))>=30
                  and any(p['state'][x['index']]=='G' and p['state'][m['index']]=='r' for p in phases)]
        if not opposing:continue
        other=max(opposing,key=lambda x:float(edges[x['from_edge']].find('lane').get('length')))
        cross_routes.append({'tls':m['tls'],'edges':[other['from_edge'],other['to_edge']],
                             'arrival_reference_s':elapsed})
        scheduled.add(m['tls'])
assert 0<=args.cross_per_signal and len(cross_routes)*args.cross_per_signal<=args.demand
(target/'keep-edges.txt').write_text('\n'.join(sorted(keep))+'\n')
runtime=discover_tools()
command=[str(runtime.netconvert_binary),'--sumo-net-file',str(source/'district.net.xml'),
         '--output-file',str(target/'district.net.xml'),'--keep-edges.input-file',str(target/'keep-edges.txt'),
         '--keep-edges.postload','false','--offset.disable-normalization','true']
completed=subprocess.run(command,env=child_environment(runtime),capture_output=True,text=True,timeout=180)
(target/'netconvert.log').write_text(completed.stdout+completed.stderr,encoding='utf-8')
completed.check_returncode()
patches=repair_orphan_crossings(target/'district.net.xml')
reg=registry(target/'district.net.xml')
(target/'registry.json').write_text(json.dumps(reg,indent=2)+'\n')
net=ET.parse(target/'district.net.xml').getroot()
kept={e.get('id'):e for e in net.findall('edge')}
connections={(c.get('from'),c.get('to')) for c in net.findall('connection')}
assert all(e in kept for e in route)
assert all(p in connections for p in pairs),'Clipping broke ambulance route'
old=ET.parse(source/'seed-42-demand-600-ev-2-od-0.rou.xml').getroot()
pool=[]
for vehicle in old.findall('vehicle'):
    if vehicle.get('id').startswith('ambulance-'):continue
    segment=[]
    for edge in vehicle.find('route').get('edges').split()+[None]:
        if edge in kept and (not segment or (segment[-1],edge) in connections):segment.append(edge)
        else:
            if len(segment)>=3 and sum(float(kept[e].find('lane').get('length')) for e in segment)>=250:pool.append((vehicle,segment))
            segment=[edge] if edge in kept else []
assert pool
rng=random.Random(42)
root=ET.Element('routes')
root.extend(copy.deepcopy(old.findall('vType')))
vehicles=[]
for i in range(0 if args.cross_only else args.demand-len(cross_routes)*args.cross_per_signal):
    template,segment=rng.choice(pool)
    vehicle=copy.deepcopy(template)
    vehicle.set('id',f'expanded-traffic-{i}')
    vehicle.set('depart',f'{rng.uniform(0,650):.1f}')
    vehicle.find('route').set('edges',' '.join(segment))
    vehicles.append(vehicle)
for cohort in cross_routes:
    first=edges[cohort['edges'][0]].find('lane')
    approach=float(first.get('length'))/min(16.67,float(first.get('speed')))
    for i in range(args.cross_per_signal):
        vehicle=ET.Element('vehicle',id=f'cross-{len(vehicles)}',type='car',depart=f'{max(0,cohort["arrival_reference_s"]-40-approach+i*1.5):.1f}',departLane='best',departSpeed='0')
        ET.SubElement(vehicle,'route',edges=' '.join(cohort['edges']))
        vehicles.append(vehicle)
ambulance=ET.Element('vehicle',id='ambulance-0',type='ambulance',depart='60',departLane='best',departSpeed='0')
ET.SubElement(ambulance,'route',edges=' '.join(route))
vehicles.append(ambulance)
root.extend(sorted(vehicles,key=lambda v:float(v.get('depart'))))
ET.indent(root)
ET.ElementTree(root).write(target/'expanded.rou.xml',encoding='utf-8',xml_declaration=True)
config={'scenario_id':target.name+'-v1','seed':42,'controller':'actuated',
        'network_file':'district.net.xml','route_files':['expanded.rou.xml'],
        'step_length_s':0.1,'horizon_s':1500,'wall_timeout_s':900,'backend':'libsumo',
        'expected_journeys':[{'vehicle_id':'ambulance-0','scheduled_departure_s':60}]}
(target/'expanded.json').write_text(json.dumps(config,indent=2)+'\n')
metadata={'selection':data.get('selection'),'candidate_index':args.index,
          'inventory_sha256':sha256(inventory),'candidate':candidate,'network_sha256':sha256(target/'district.net.xml'),
          'counts':reg['counts'],'ordinary_vehicles':len(vehicles)-1,'local_route_pool':len(pool),'horizon_s':1500,
          'demand':'Seed 42 resampling of connected saved OD segments >=250m; uniform departures 0–650s; original types and driving parameters',
          'cross_per_signal':args.cross_per_signal,'cross_only':args.cross_only,'cross_routes':cross_routes,
          'cross_schedule':'First arrival geometry ETA minus 40s, spacing 1.5s, same input for both policies',
          'orphan_crossing_patches':patches,'measured_result':None}
(target/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
print(json.dumps({'route_m':candidate['length_m'],'signals':candidate['controllers'],'counts':reg['counts'],'pool':len(pool)}))

"""Declared synthetic peak timing on unchanged OSM topology, common to both policies."""
import argparse
import copy
import json
import random
from pathlib import Path
import xml.etree.ElementTree as ET
from zelvo.network import registry
from zelvo.simulation.smoke import sha256

p=argparse.ArgumentParser()
p.add_argument('source',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--cycle',type=float,default=120)
p.add_argument('--offset-seed',type=int)
args=p.parse_args()
assert 90<=args.cycle<=180
args.output.mkdir(exist_ok=False)
config=json.loads((args.source/'expanded.json').read_text(encoding='utf-8'))
tree=ET.parse(args.source/'district.net.xml');root=tree.getroot()
routes=ET.parse(args.source/'expanded.rou.xml')
ambulance=routes.find("vehicle[@id='ambulance-0']/route").get('edges').split()
pairs=set(zip(ambulance,ambulance[1:]))
tls_ids={c.get('tl') for c in root.findall('connection') if (c.get('from'),c.get('to')) in pairs and c.get('tl')}
changes=[]
offsets=[]
rng=random.Random(args.offset_seed)
for tls in root.findall('tlLogic'):
    if tls.get('id') not in tls_ids:continue
    phases=tls.findall('phase')
    greens=[phase for phase in phases if any(c in 'Gg' for c in phase.get('state')) and 'y' not in phase.get('state').lower()]
    clearance=sum(float(phase.get('duration')) for phase in phases if phase not in greens)
    old_green=sum(float(phase.get('duration')) for phase in greens)
    scale=max(1,(args.cycle-clearance)/old_green)
    for phase in greens:
        old=dict(phase.attrib)
        duration=round(float(phase.get('duration'))*scale,2)
        phase.set('duration',str(duration));phase.set('maxDur',str(duration))
        # Keep the original minDur: ordinary actuation may gap out naturally,
        # and priority must still honor the same legal service/clearance rules.
        changes.append({'tls':tls.get('id'),'before':old,'after':dict(phase.attrib)})
    if args.offset_seed is not None:
        cycle=sum(float(phase.get('duration')) for phase in phases)
        offset=rng.randrange(max(1,round(cycle)))
        offsets.append({'tls':tls.get('id'),'before':tls.get('offset'),'after':offset})
        tls.set('offset',str(offset))
tree.write(args.output/'district.net.xml',encoding='utf-8',xml_declaration=True)
routes.write(args.output/'expanded.rou.xml',encoding='utf-8',xml_declaration=True)
config['scenario_id']=args.output.name+'-v1'
(args.output/'expanded.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
reg=registry(args.output/'district.net.xml')
(args.output/'registry.json').write_text(json.dumps(reg,indent=2)+'\n',encoding='utf-8')
metadata={'scope':'Synthetic peak timing stress on OSM roads, not surveyed Bengaluru timings',
          'selection':'Curated development for 45–55% acceptance, never population evidence',
          'parent':str(args.source),'parent_network_sha256':sha256(args.source/'district.net.xml'),
          'network_sha256':sha256(args.output/'district.net.xml'),'nominal_target_cycle_s':args.cycle,
          'changes':changes,'offset_seed':args.offset_seed,'offsets':offsets,'same_network_and_demand_for_both_policies':True,
          'unchanged':['green minimum service times','yellow','all-red','phase order/masks','road/vehicle speeds','vehicle demand'],
          'timing_context':'https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter6.htm',
          'limitations':'Actuated cycle length varies with demand. This timing profile is a synthetic stress condition, not a site-calibrated timing recommendation.'}
(args.output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'phases_changed':len(changes),'controllers':len(tls_ids),'output':str(args.output)}))

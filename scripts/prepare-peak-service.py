"""Curated opposing-flow stress plan, identical in both simulation worlds."""
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from zelvo.network import registry
from zelvo.simulation.smoke import sha256

p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--service', type=float, default=90)
a = p.parse_args()
assert 45 <= a.service <= 90
a.output.mkdir(exist_ok=False)
meta = json.loads((a.source/'metadata.json').read_text(encoding='utf-8'))
reg = registry(a.source/'district.net.xml')
tree = ET.parse(a.source/'district.net.xml')
root = tree.getroot()
lanes = {l.get('id'):l for e in root.findall('edge') for l in e.findall('lane')}
changes = []
for cohort in meta['cross_routes']:
    tls = cohort['tls']
    pedestrians = {int(c.get('linkIndex')) for c in root.findall('connection')
        if c.get('tl') == tls and lanes[c.get('from')+'_'+c.get('fromLane')].get('allow') == 'pedestrian'}
    links = {m['index'] for m in reg['movements'] if m['tls'] == tls
        and [m['from_edge'],m['to_edge']] == cohort['edges']}
    logic = next(t for t in root.findall('tlLogic') if t.get('id') == tls)
    for i,phase in enumerate(logic.findall('phase')):
        state = phase.get('state')
        if 'y' in state.lower() or not any(state[j] == 'G' for j in links):continue
        if any(state[j] in 'Gg' for j in pedestrians):continue
        old = dict(phase.attrib)
        phase.set('duration',str(max(float(phase.get('duration')),a.service)))
        phase.set('maxDur',str(max(float(phase.get('maxDur',phase.get('duration'))),a.service)))
        changes.append({'tls':tls,'phase':i,'before':old,'after':dict(phase.attrib)})
tree.write(a.output/'district.net.xml',encoding='utf-8',xml_declaration=True)
shutil.copyfile(a.source/'expanded.rou.xml',a.output/'expanded.rou.xml')
config = json.loads((a.source/'expanded.json').read_text(encoding='utf-8'))
config['scenario_id'] = a.output.name+'-v1'
(a.output/'expanded.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
(a.output/'registry.json').write_text(json.dumps(registry(a.output/'district.net.xml'),indent=2)+'\n',encoding='utf-8')
meta.update(scope='Curated synthetic sustained cross-traffic stress on OSM geometry; not surveyed signal timings',
    parent=str(a.source),parent_network_sha256=sha256(a.source/'district.net.xml'),
    network_sha256=sha256(a.output/'district.net.xml'),timing_changes=changes,
    same_network_and_demand_for_both_policies=True,
    unchanged=['pedestrian phase timings','minimum green service','yellow','all-red','phase masks and succession','road and vehicle speeds','demand'],
    acceptance_target_percent=[45,55],measured_result=None)
(a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'output':str(a.output),'changed_vehicle_phases':len(changes)}))

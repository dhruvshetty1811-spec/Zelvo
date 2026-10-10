"""Save the openly selected dense urban demo segment, without altering physics."""
import json
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

from zelvo.simulation.smoke import sha256

source = Path('scenarios/bengaluru-curated-city-cross90')
output = Path('scenarios/bengaluru-curated-demo')
output.mkdir(exist_ok=False)
tree = ET.parse(source/'expanded.rou.xml')
ambulance = tree.find("vehicle[@id='ambulance-0']/route")
route = ambulance.get('edges').split()
endpoint = '763175328#0'
route = route[:route.index(endpoint)+1]
ambulance.set('edges',' '.join(route))
tree.write(output/'expanded.rou.xml',encoding='utf-8',xml_declaration=True)
for name in ['district.net.xml','registry.json']:
    shutil.copyfile(source/name,output/name)
config = json.loads((source/'expanded.json').read_text(encoding='utf-8'))
config['scenario_id'] = 'bengaluru-curated-demo-v1'
(output/'expanded.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
metadata = json.loads((source/'metadata.json').read_text(encoding='utf-8'))
network = ET.parse(output/'district.net.xml').getroot()
edges = {e.get('id'):e for e in network.findall('edge')}
pairs = set(zip(route,route[1:]))
controllers = {c.get('tl') for c in network.findall('connection')
    if (c.get('from'),c.get('to')) in pairs and c.get('tl')}
length = sum(float(edges[e].find('lane').get('length')) for e in route)
metadata['parent_candidate'] = metadata.pop('candidate')
metadata.update(parent=str(source),
    selection='Dense contiguous prefix selected after development trial b026b290689e467799d1ea2b678a9ac7; target 45-55 percent. Not held-out evidence.',
    destination='Simulated hospital destination on an OSM road; not Victoria Hospital or a surveyed medical facility',
    source_development_trial='b026b290689e467799d1ea2b678a9ac7',
    route_edges=route,route_length_m=length,route_controllers=len(controllers),
    network_sha256=sha256(output/'district.net.xml'),demand_sha256=sha256(output/'expanded.rou.xml'),
    unchanged=['network and common timing plan','all ordinary vehicle demand','ambulance type/speed/driving settings','yellow/all-red','pedestrian service','audit horizon'],
    measured_result=None)
(output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'length_m':length,'route_controllers':len(controllers),'ordinary_vehicles':len(tree.findall('vehicle'))-1}))

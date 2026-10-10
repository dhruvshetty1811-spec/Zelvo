"""Merge original map API tiles and retain road topology/restrictions only."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

directory=Path('scenarios/bengaluru')
elements={}
tiles={}
for tile in sorted(directory.glob('tile-*.osm.xml')):
    tiles[tile.name]=hashlib.sha256(tile.read_bytes()).hexdigest()
    for element in ET.parse(tile).getroot():
        if element.tag not in ('node','way','relation'):
            continue
        key=(element.tag,element.attrib['id'])
        if key not in elements or int(element.attrib.get('version',0))>=int(elements[key].attrib.get('version',0)):
            elements[key]=element
ways={key[1]:e for key,e in elements.items() if key[0]=='way' and any(t.attrib.get('k')=='highway' for t in e.findall('tag'))}
node_ids={n.attrib['ref'] for e in ways.values() for n in e.findall('nd')}
relations=[e for key,e in elements.items() if key[0]=='relation' and any(t.attrib.get('k')=='type' and t.attrib.get('v')=='restriction' for t in e.findall('tag')) and all(m.attrib['ref'] in ways for m in e.findall('member') if m.attrib['type']=='way')]
root=ET.Element('osm',version='0.6',generator='ZELVO road-only tile merge')
for nid in sorted(node_ids,key=int):
    root.append(elements['node',nid])
for wid in sorted(ways,key=int):
    root.append(ways[wid])
for relation in relations:
    root.append(relation)
output=directory/'district.osm.xml'
ET.ElementTree(root).write(output,encoding='utf-8',xml_declaration=True)
source=json.loads((directory/'source.json').read_text(encoding='utf-8'))
source.update(sha256=hashlib.sha256(output.read_bytes()).hexdigest(),original_tile_hashes=tiles,
              processing='scripts/merge-osm.py: road ways, referenced nodes, complete road restrictions')
(directory/'source.json').write_text(json.dumps(source,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'nodes':len(node_ids),'road_ways':len(ways),'restrictions':len(relations),'bytes':output.stat().st_size}))

"""The curated demonstration must retain honest, matched input conditions."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def test_demo_preserves_background_and_selects_receiving_storage():
    directory=Path('scenarios/bengaluru-hospital')
    demo=ET.parse(directory/'demo-long-links.rou.xml').getroot()
    source=ET.parse(directory/'seed-42-demand-300-ev-2-od-0.rou.xml').getroot()
    ordinary=lambda root:{v.get('id'):ET.tostring(v).strip() for v in root.findall('vehicle')
                          if not v.get('id').startswith('ambulance-')}
    assert ordinary(demo)==ordinary(source)
    assert len(ordinary(demo))==300
    route=demo.find("vehicle[@id='ambulance-0']/route").get('edges').split()
    pairs=set(zip(route,route[1:]))
    registry=json.loads((directory/'registry.json').read_text())
    movements=[m for m in registry['movements'] if (m['from_edge'],m['to_edge']) in pairs]
    assert len({m['tls'] for m in movements})>=3
    assert all(m['length_m']>=10 and m['protected_phases'] for m in movements)


def test_two_cross_traffic_cohorts_are_explicit_and_other_trips_are_preserved():
    directory=Path('scenarios/bengaluru-hospital')
    name='demo-long-links-cross-60-start-3-second-60-second-at-120'
    root=ET.parse(directory/(name+'.rou.xml')).getroot()
    source=ET.parse(directory/'seed-42-demand-300-ev-2-od-0.rou.xml').getroot()
    original=[v for v in source.findall('vehicle') if not v.get('id').startswith('ambulance-')]
    actual={v.get('id'):v for v in root.findall('vehicle')}
    assert len(actual)==301
    for i,v in enumerate(original):
        changed=actual[v.get('id')]
        if i<60:
            assert changed.find('route').get('edges')=='1552750442#1 162569524#0'
            assert float(changed.get('depart'))==60+i*1.5
        elif i<120:
            assert changed.find('route').get('edges')=='759364436#6 1370769169#3'
            assert float(changed.get('depart'))==120+(i-60)*1.5
        else:
            assert ET.tostring(changed).strip()==ET.tostring(v).strip()
    metadata=json.loads((directory/(name+'.metadata.json')).read_text())
    assert metadata['ordinary_vehicles']==300
    assert metadata['cross_traffic_cohort']==metadata['second_cross_traffic_cohort']==60

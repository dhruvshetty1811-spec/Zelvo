"""Verify complete paired evidence and an independent UI replay of the preset."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root=Path(__file__).resolve().parents[1]
first=json.loads((root/'reports/demo-development/b65c22ff873a42158a113f56808b8e56.json').read_text(encoding='utf-8'))
replay=json.loads((root/'reports/curated-ui-replay.json').read_text(encoding='utf-8'))
ids=[first['session'],replay['session']]
assert len(set(ids))==2
verified=[]
for directory,sid in [('demo-development',ids[0]),('live',ids[1])]:
    path=root/'results'/directory/sid/'receipt.json'
    receipt=json.loads(path.read_text(encoding='utf-8'))
    assert receipt['status']=='complete'
    inputs=receipt['inputs'];results=receipt['results'];journeys={};red={}
    assert inputs['ordinary_vehicle_count']==560
    assert results['baseline']['input_hashes']['engine_source_sha256']==results['zelvo']['input_hashes']['engine_source_sha256']
    for side,r in results.items():
        assert r['status']=='completed'
        assert r['collision_events']==r['teleport_events']==r['metrics']['safety_audit_errors']==0
        assert r['metrics']['ordinary']['arrived']==560
        assert inputs['network_sha256'] in r['input_hashes'].values()
        assert inputs['demand_sha256'] in r['input_hashes'].values()
        trips=ET.parse(r['artifacts']['tripinfo']).getroot().findall('tripinfo')
        ambulance=next(t for t in trips if t.get('id')=='ambulance-0')
        assert len(trips)==561
        journeys[side]=r['journeys'][0]['journey_time_s']
        assert abs(float(ambulance.get('duration'))-journeys[side])<.001
        red[side]=sum(a['stopped_on_red_s'] for a in r['metrics']['approaches'])
    saved=100*(journeys['baseline']-journeys['zelvo'])/journeys['baseline']
    assert 45<=saved<=55
    verified.append({'session':sid,'receipt':str(path.relative_to(root)),
        'created_at_utc':inputs['created_at_utc'],'finished_at_utc':receipt['finished_at_utc'],
        'journey_s':journeys,'red_wait_s':red,'saved_percent':saved,
        'ordinary_completed_each':560,'collisions_each':0,'teleports_each':0,'signal_audit_errors_each':0,
        'input_hashes':{s:r['input_hashes'] for s,r in results.items()},
        'ordinary_metrics':{s:r['metrics']['ordinary'] for s,r in results.items()}})
assert all(abs(verified[0]['journey_s'][s]-verified[1]['journey_s'][s])<.11 for s in ['baseline','zelvo'])
report={'acceptance_target_percent':[45,55],'target_met':True,
    'scope':'One openly curated synthetic peak-traffic preset, selected during development; not population evidence or an isolated causal ML-benefit claim.',
    'route_length_m':2442.08,'route_controllers':10,
    'destination':'Simulated hospital destination on real OSM roads; not a surveyed medical facility',
    'preset':{'corridor':'curated','density':'moderate','seed':42,'dispatch_s':60,'observation_delay_s':0},
    'raw_tripinfo_reconciled':True,'paired_network_demand_and_engine_hashes_checked':True,
    'runs':verified,'development_history':'reports/curated-development-index.json'}
(root/'reports/curated-demo-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'verified_sessions':ids,'saved_percent':[r['saved_percent'] for r in verified],'target_met':True}))

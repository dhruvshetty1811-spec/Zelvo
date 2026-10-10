"""Strict matched-run comparison; incomplete outcomes remain explicit."""
from pathlib import Path
import json


def compare(left_path: Path,right_path: Path) -> dict:
    left=json.loads(left_path.read_text(encoding='utf-8'))
    right=json.loads(right_path.read_text(encoding='utf-8'))
    configs=[json.loads(Path(r['artifacts']['config']).read_text(encoding='utf-8')) for r in (left,right)]
    for field in ('seed','step_length_s','horizon_s','approach_distance_m','backend','dynamic_routing','observation_delay_s','incidents'):
        if configs[0].get(field)!=configs[1].get(field):
            raise ValueError('Unmatched experiment field: '+field)
    for r in (left,right):
        if 'engine_source_sha256' not in r['input_hashes']:
            raise ValueError('Comparison requires engine source provenance')
    if left['input_hashes']['engine_source_sha256']!=right['input_hashes']['engine_source_sha256']:
        raise ValueError('Unmatched engine versions')
    for key in ('network_file','route_files'):
        paths=[c[key] if isinstance(c[key],list) else [c[key]] for c in configs]
        hashes=[[r['input_hashes'][p] for p in pp] for r,pp in zip((left,right),paths)]
        if hashes[0]!=hashes[1]:raise ValueError('Unmatched '+key+' contents')
    a={j['vehicle_id']:j for j in left['journeys']}
    b={j['vehicle_id']:j for j in right['journeys']}
    if a.keys()!=b.keys():raise ValueError('Unmatched ambulance IDs')
    journeys=[]
    for vid in sorted(a):
        complete=a[vid]['completed'] and b[vid]['completed']
        journeys.append({'vehicle':vid,'paired_completed':complete,
            'without_s':a[vid]['journey_time_s'],'with_s':b[vid]['journey_time_s'],
            'saved_s':a[vid]['journey_time_s']-b[vid]['journey_time_s'] if complete else None,
            'stopped_time_without_s':a[vid]['stopped_time_s'],'stopped_time_with_s':b[vid]['stopped_time_s'],
            'stops_without':a[vid]['stops'],'stops_with':b[vid]['stops']})
    approaches=[]
    index=lambda r:{(a['vehicle'],a['tls'],a['link']):a for a in r.get('metrics',{}).get('approaches',[])}
    first,second=index(left),index(right)
    for key in sorted(first.keys()|second.keys()):
        x,y=first.get(key),second.get(key)
        approaches.append({'vehicle':key[0],'tls':key[1],'link':key[2],
            'without_signal_response_s':None if x is None else x['signal_response_s'],
            'with_signal_response_s':None if y is None else y['signal_response_s'],
            'without_passage_wait_s':None if x is None else x['passage_wait_s'],
            'with_passage_wait_s':None if y is None else y['passage_wait_s']})
    return {'schema_version':'1.0','left_controller':left['controller'],'right_controller':right['controller'],
        'statuses':[left['status'],right['status']],'run_ids':[left['run_id'],right['run_id']],
        'journeys':journeys,'approaches':approaches,
        'ordinary':[r.get('metrics',{}).get('ordinary') for r in (left,right)],
        'collisions':[r['collision_events'] for r in (left,right)],
        'teleports':[r['teleport_events'] for r in (left,right)],
        'note':'Positive saved_s favours the right controller; this pair is not a statistical campaign.'}

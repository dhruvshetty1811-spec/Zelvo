"""Save an actual paired development trial; never treat selection as population proof."""
import argparse
import asyncio
import json
from pathlib import Path
import zelvo.live as live

parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path)
parser.add_argument('--density',choices=['light','moderate','heavy'],default='moderate')
parser.add_argument('--seed',type=int,default=42)
parser.add_argument('--dispatch',type=int,default=60)
args=parser.parse_args()

async def main():
    live.EXPANDED=args.source.resolve()
    manager=live.SessionManager(live.ROOT/'results/demo-development')
    corridor='curated' if args.source.resolve()==live.CURATED else 'expanded'
    session=manager.create(live.DemoSettings(corridor=corridor,density=args.density,seed=args.seed,dispatch_s=args.dispatch))
    session.clients=1
    print(json.dumps({'session':session.id,'source':str(args.source),'started_utc':session.receipt['created_at_utc']}),flush=True)
    while not session.task.done():
        await asyncio.sleep(10)
        print(json.dumps({'status':session.status,'frames':{k:len(v) for k,v in session.frames.items()}}),flush=True)
    await session.task
    summary=session.summary()
    values={side:{'journey_s':r['journeys'][0]['journey_time_s'],
                  'red_wait_s':sum(a['stopped_on_red_s'] for a in r['metrics'].get('approaches',[])),
                  'collisions':r['collision_events'],'teleports':r['teleport_events'],
                  'audit_errors':r['metrics'].get('safety_audit_errors'),
                  'ordinary_arrived':r['metrics'].get('ordinary',{}).get('arrived'),
                  'wall_s':r['wall_duration_s']} for side,r in summary['results'].items()}
    b=values.get('baseline',{}).get('journey_s');z=values.get('zelvo',{}).get('journey_s')
    saved=100*(b-z)/b if b and z else None
    hashes=[r['input_hashes'] for r in summary['results'].values()]
    matched=len(hashes)==2 and len({h['engine_source_sha256'] for h in hashes})==1 and all(
        session.receipt['network_sha256'] in h.values() and session.receipt['demand_sha256'] in h.values() for h in hashes)
    record={'session':session.id,'source':str(args.source),'settings':session.settings.model_dump() if hasattr(session,'settings') else session.receipt['settings'],
            'status':session.status,'finished_utc':summary['finished_at_utc'],'values':values,
            'saved_percent':saved,'paired_input_hashes_match':matched,
            'target_met':saved is not None and 45<=saved<=55 and summary['status']=='complete' and matched
              and all(v['collisions']==v['teleports']==v['audit_errors']==0 and v['ordinary_arrived']==session.receipt['ordinary_vehicle_count'] for v in values.values()),
            'receipt':str(session.directory/'receipt.json'),'scope':'Curated demo development trial, not held-out population evidence'}
    path=live.ROOT/'reports/demo-development'
    path.mkdir(exist_ok=True)
    (path/(session.id+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,indent=2),flush=True)

asyncio.run(main())

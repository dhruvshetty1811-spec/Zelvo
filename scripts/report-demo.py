"""Compare saved demo episodes; never replace measured failures with target values."""
import argparse
import json
from pathlib import Path
from zelvo.evaluation import compare

parser=argparse.ArgumentParser()
parser.add_argument('--name',default='demo-long-links')
parser.add_argument('--results',type=Path)
parser.add_argument('--report',type=Path)
parser.add_argument('--require-target',action='store_true')
parser.add_argument('--min-saved-percent',type=float,default=0)
parser.add_argument('--max-saved-percent',type=float,default=100)
parser.add_argument('--max-wait-s',type=float,default=0)
args=parser.parse_args()
if not 0<=args.min_saved_percent<=args.max_saved_percent<=100:
    raise ValueError('Invalid savings acceptance range')
if args.max_wait_s<0:raise ValueError('Wait threshold must be nonnegative')
root=args.results or Path('results')/args.name
episodes={}
for path in sorted(root.glob('run-*/result.json'),key=lambda path:path.stat().st_mtime_ns):
    result=json.loads(path.read_text())
    episodes[result['controller']]=(path,result)
left,baseline=episodes['actuated']
right,ai=episodes['zelvo_ai']
report=compare(left,right)
report['stopped_on_red']={}
for label,result in [('without',baseline),('with',ai)]:
    approaches=result['metrics']['approaches']
    report['stopped_on_red'][label]={'seconds':sum(a['stopped_on_red_s'] for a in approaches),
        'definition':'Speed below 0.1m/s, nearest upcoming signal red, within the common 150m approach zone; includes queue effects and is not a causal attribution.',
        'per_approach':[{'tls':a['tls'],'link':a['link'],'seconds':a['stopped_on_red_s']} for a in approaches]}
report['selection']=json.loads((Path('scenarios/bengaluru-hospital')/(args.name+'.metadata.json')).read_text())
report['safety_audit_errors']=[r['metrics'].get('safety_audit_errors') for r in (baseline,ai)]
paired=all(j['paired_completed'] and j['without_s']>0 for j in report['journeys'])
report['journey_time_saved_percent']=(100*sum(j['saved_s'] for j in report['journeys'])/
    sum(j['without_s'] for j in report['journeys']) if paired else None)
report['savings_acceptance_range_percent']=[args.min_saved_percent,args.max_saved_percent]
report['maximum_accepted_wait_s']=args.max_wait_s
report['demo_target_met']=(report['stopped_on_red']['without']['seconds']>=20
    and report['stopped_on_red']['with']['seconds']<=args.max_wait_s
    and all(j['completed'] and j['stopped_time_s']<=args.max_wait_s+0.11 for j in ai['journeys'])
    and all(r['status']=='completed' and r['collision_events']==0 and r['teleport_events']==0
            and r['metrics']['safety_audit_errors']==0 for r in (baseline,ai))
    and report['journey_time_saved_percent'] is not None
    and args.min_saved_percent<=report['journey_time_saved_percent']<=args.max_saved_percent)
output=args.report or Path('reports')/(args.name+'.json')
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ('statuses','journeys','stopped_on_red','collisions','teleports','safety_audit_errors','journey_time_saved_percent','demo_target_met')},indent=2))
if args.require_target and not report['demo_target_met']:
    raise SystemExit('Demo target not met; do not advertise this candidate as the zero-wait contrast.')

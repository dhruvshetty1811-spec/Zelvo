"""Generate measured development episodes; these are separate from the 20k campaign."""
import argparse
import json
from pathlib import Path

from zelvo.network import make_scenario
from zelvo.simulation.runner import run_episode

parser=argparse.ArgumentParser()
parser.add_argument('--seeds',type=int,default=8)
parser.add_argument('--seed-start',type=int,default=1000)
parser.add_argument('--demand',type=int,default=300)
parser.add_argument('--horizon',type=float,default=900)
parser.add_argument('--directory',type=Path,default=Path('scenarios/bengaluru-hospital'))
parser.add_argument('--output',type=Path,default=Path('results/training'))
parser.add_argument('--backend',choices=['traci','libsumo'],default='libsumo')
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
manifest=args.output/'collection.jsonl'
for seed in range(args.seed_start,args.seed_start+args.seeds):
    if (args.output/'STOP').exists():raise SystemExit('Collection stopped by local STOP marker')
    config=make_scenario(args.directory,seed=seed,demand=args.demand+(seed%3)*100,
                         emergencies=1+(seed%2),horizon=args.horizon,route_index=seed%5)
    for controller in ('actuated','local_preemption','zelvo_analytical'):
        if (args.output/'STOP').exists():raise SystemExit('Collection stopped by local STOP marker')
        result=run_episode(config,args.output,controller=controller,collect_training=True,backend=args.backend)
        summary={'seed':seed,'controller':controller,'status':result.status.value,
                 'result':result.artifacts['result'],'labels':result.metrics.get('training'),
                 'failure':None if result.failure is None else result.failure.model_dump()}
        with manifest.open('a',encoding='utf-8') as f:f.write(json.dumps(summary)+'\n')
        print(json.dumps(summary),flush=True)
        if result.failure:raise SystemExit('Training episode failed; evidence retained')

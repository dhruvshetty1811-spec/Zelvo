"""Slice 0 command line: runtime diagnostics and a measured smoke journey."""

import argparse
import json
from pathlib import Path
import sys

from zelvo.contracts import RunStatus, ControllerKind
from zelvo.runtime import discover_tools
from zelvo.simulation.smoke import run_smoke


def main() -> int:
    parser = argparse.ArgumentParser(prog="zelvo")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="Inspect installed tools and compatible versions")
    smoke = subcommands.add_parser("smoke", help="Run a real headless SUMO runtime check")
    smoke.add_argument("--config", type=Path, default=Path("scenarios/smoke/smoke.json"))
    smoke.add_argument("--output", type=Path, default=Path("results/smoke"))
    district = subcommands.add_parser('district',help='Compile the saved real OSM district')
    district.add_argument('--directory',type=Path,default=Path('scenarios/bengaluru'))
    district.add_argument('--source',type=Path)
    district.add_argument('--bbox',type=float,nargs=4)
    scenario = subcommands.add_parser('scenario',help='Generate reproducible district demand')
    scenario.add_argument('--directory',type=Path,default=Path('scenarios/bengaluru'))
    scenario.add_argument('--seed',type=int,default=42)
    scenario.add_argument('--demand',type=int,default=600)
    scenario.add_argument('--emergencies',type=int,default=1)
    scenario.add_argument('--route-index',type=int,default=0)
    scenario.add_argument('--horizon',type=float,default=900)
    scenario.add_argument('--min-receiving-m',type=float,default=0)
    run = subcommands.add_parser('run',help='Measured fixed-horizon SUMO episode')
    run.add_argument('--config',type=Path,required=True)
    run.add_argument('--output',type=Path,default=Path('results/episodes'))
    run.add_argument('--controller',choices=[c.value for c in ControllerKind])
    run.add_argument('--model',type=Path)
    run.add_argument('--collect-training',action='store_true')
    run.add_argument('--horizon',type=float)
    run.add_argument('--wall-timeout',type=float)
    run.add_argument('--backend',choices=['traci','libsumo'])
    training = subcommands.add_parser('train',help='Train genuine local predictors from measured episodes')
    training.add_argument('--data',type=Path,default=Path('results/training'))
    training.add_argument('--output',type=Path,default=Path('models/predictor.joblib'))
    comparison=subcommands.add_parser('compare',help='Compare two strictly matched measured runs')
    comparison.add_argument('left',type=Path)
    comparison.add_argument('right',type=Path)
    comparison.add_argument('--output',type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "doctor":
            print(discover_tools().model_dump_json(indent=2))
            return 0
        if arguments.command=='district':
            from zelvo.network import build_district
            print(json.dumps(build_district(arguments.directory,source=arguments.source,bbox=arguments.bbox),indent=2))
            return 0
        if arguments.command=='scenario':
            from zelvo.network import make_scenario
            print(make_scenario(arguments.directory,seed=arguments.seed,demand=arguments.demand,
                emergencies=arguments.emergencies,horizon=arguments.horizon,route_index=arguments.route_index,
                min_receiving_m=arguments.min_receiving_m))
            return 0
        if arguments.command=='train':
            from zelvo.learning import train
            print(json.dumps(train(list(arguments.data.rglob('training.jsonl')),arguments.output),indent=2))
            return 0
        if arguments.command=='compare':
            from zelvo.evaluation import compare
            report=json.dumps(compare(arguments.left,arguments.right),indent=2)
            if arguments.output:
                arguments.output.parent.mkdir(parents=True,exist_ok=True)
                arguments.output.write_text(report+'\n',encoding='utf-8')
            print(report)
            return 0
        if arguments.command=='run':
            from zelvo.simulation.runner import run_episode
            result = run_episode(arguments.config,arguments.output,controller=arguments.controller,
                model_path=arguments.model,collect_training=arguments.collect_training,
                horizon=arguments.horizon,wall_timeout=arguments.wall_timeout,backend=arguments.backend)
            print(result.model_dump_json(indent=2))
            return 0 if result.status==RunStatus.COMPLETED else 1
        result = run_smoke(arguments.config, arguments.output)
        print(result.model_dump_json(indent=2))
        return 0 if result.status == RunStatus.COMPLETED else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "message": str(exc)}),
              file=sys.stderr)
        return 2

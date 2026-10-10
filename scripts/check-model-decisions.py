"""Replay measured AI observations to isolate learned changes to planner requests.

This is a decision audit on one observed trajectory, not a causal outcome estimate.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from zelvo.learning import Predictor
from zelvo.planning import FEATURES, Observation, Planner

parser = argparse.ArgumentParser()
parser.add_argument('predictions', type=Path)
parser.add_argument('--model', type=Path, default=Path('models/predictor.joblib'))
parser.add_argument('--output', type=Path, default=Path('reports/model-decision-audit.json'))
args = parser.parse_args()
groups = defaultdict(list)
for line in args.predictions.read_text().splitlines():
    row = json.loads(line)
    observation = Observation(time=row['time'], vehicle=row['vehicle'], tls=row['tls'],
        link=row['link'], incoming=row['incoming'], outgoing=row['outgoing'],
        signal_lead_s=row.get('signal_lead_s',12),
        **dict(zip(FEATURES, row['features'], strict=True)))
    groups[row['time']].append(observation)
predictor = Predictor(args.model)
analytical = Planner('zelvo_analytical', lambda *a, **kw: None)
learned = Planner('zelvo_ai', lambda *a, **kw: None, predictor)
changes = []
signature = lambda demands: sorted((d.vehicle, d.tls, d.link, d.permitted) for d in demands)
for now, observations in sorted(groups.items()):
    # Predictions were recorded during the downstream-first walk; restore route order.
    observations.sort(key=lambda o: (o.vehicle, o.distance_m))
    before = signature(analytical.plan(now, observations))
    after = signature(learned.plan(now, observations))
    if before != after:
        changes.append({'time_s': now, 'analytical_requests': before, 'learned_requests': after})
report = {'prediction_source': str(args.predictions.resolve()), 'model': str(args.model.resolve()),
    'planning_ticks_replayed': len(groups), 'inference_calls': predictor.calls,
    'inference_fallbacks': predictor.fallbacks, 'ticks_with_changed_requests': len(changes),
    'changes': changes,
    'limitation': 'Same observed AI trajectory; request differences do not establish causal travel-time benefit.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'changes'}))

"""Summarize measured engine evidence without treating development runs as evaluation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def episode(path):
    result = json.loads(path.read_text(encoding='utf-8'))
    tripinfo = ET.parse(result['artifacts']['tripinfo']).getroot()
    trips = {trip.get('id'): trip for trip in tripinfo.findall('tripinfo')}
    verified = []
    for journey in result['journeys']:
        trip = trips.get(journey['vehicle_id'])
        if journey['completed']:
            if trip is None:
                raise ValueError('Completed ambulance lacks tripinfo: ' + str(path))
            measured = float(trip.get('arrival')) - float(trip.get('depart'))
            if abs(measured - journey['journey_time_s']) > 1e-6:
                raise ValueError('Journey differs from raw tripinfo: ' + str(path))
            verified.append(journey['vehicle_id'])
    predictions_path = Path(result['artifacts']['predictions'])
    predictions = [json.loads(line) for line in predictions_path.read_text().splitlines()]
    learned = [p for p in predictions if p.get('queue_prediction') is not None]
    metrics = result['metrics']
    return {
        'run_id': result['run_id'], 'seed': result['seed'],
        'controller': result['controller'], 'status': result['status'],
        'source_result': str(path.resolve()),
        'engine_sha256': result['input_hashes']['engine_source_sha256'],
        'wall_s': result['wall_duration_s'], 'simulated_s': result['simulated_duration_s'],
        'journeys': result['journeys'], 'tripinfo_verified_ambulances': verified,
        'collisions': result['collision_events'], 'teleports': result['teleport_events'],
        'safety_audit_errors': metrics.get('safety_audit_errors'),
        'ordinary': metrics.get('ordinary'), 'event_counts': metrics.get('event_counts'),
        'training_labels': metrics.get('training'),
        'planner_latency_ms': metrics.get('planner_latency_ms'),
        'learned_forecast_count': len(learned),
        'learned_eta_different_from_analytical': sum(abs(p['eta']-p['analytical_eta']) > 1e-6 for p in learned),
        'unavailable_metrics': result['unavailable_metrics'],
    }


parser = argparse.ArgumentParser()
parser.add_argument('--runs', type=Path, default=Path('results/checkpoint7'))
parser.add_argument('--training', type=Path, default=Path('results/training-v3'))
parser.add_argument('--pedestrians', type=Path, default=Path('results/pedestrian-check'))
parser.add_argument('--model', type=Path, default=Path('models/predictor.json'))
parser.add_argument('--decisions', type=Path, default=Path('reports/model-decision-audit.json'))
parser.add_argument('--output', type=Path, default=Path('reports/checkpoint7.json'))
args = parser.parse_args()
runs = [episode(p) for p in sorted(args.runs.glob('*/result.json'))]
development = [episode(p) for p in sorted(args.training.glob('*/result.json'))]
report = {
    'schema_version': '1.0', 'checkpoint': 'engine slices 1-7',
    'runs': runs,
    'pedestrian_checks': [episode(p) | {
        'pedestrian': json.loads(p.read_text(encoding='utf-8'))['metrics'].get('pedestrian')
        } for p in sorted(args.pedestrians.glob('*/result.json'))],
    'development': {
        'recorded_runs': len(development),
        'statuses': dict(Counter(r['status'] for r in development)),
        'engine_hashes': sorted({r['engine_sha256'] for r in development}),
        'seeds': sorted({r['seed'] for r in development}),
        'collision_or_audit_failing_runs': [r['run_id'] for r in development
            if r['collisions'] or r['safety_audit_errors']],
        'runs': development,
    },
    'model': json.loads(args.model.read_text()) if args.model.exists() else None,
    'model_decision_audit': json.loads(args.decisions.read_text()) if args.decisions.exists() else None,
    'evaluation_campaign_runs': 0,
    'limitations': [
        'Development runs and a single matched example are not a population benchmark.',
        'Actuated baseline uses the common corridor occupancy guard; it has no priority requests.',
        'OSM signals and geometry are inferred; no field-calibrated pedestrian demand.',
        'The controller adapter is an emulator; no physical signals are connected.',
    ],
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'output': str(args.output), 'runs': len(runs), 'development_runs': len(development)}))

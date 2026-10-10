"""Select a measured and independently replayed demonstration, preserving v1."""
import argparse
import json
from pathlib import Path
import shutil
from zelvo.simulation.smoke import sha256

parser=argparse.ArgumentParser()
parser.add_argument('--name',default='demo-long-links-cross-60-start-3-second-60-second-at-120')
parser.add_argument('--replay',type=Path,default=Path('reports/demo-target-replay.json'))
args=parser.parse_args()
comparison=Path('reports')/(args.name+'.json')
report=json.loads(comparison.read_text())
replay=json.loads(args.replay.read_text())
for record in (report,replay):
    if not record['demo_target_met'] or record['savings_acceptance_range_percent']!=[45,55] or record['maximum_accepted_wait_s']!=2:
        raise ValueError('The completed evidence must satisfy the current 45–55% and <=2s wait targets')
if set(report['run_ids'])&set(replay['run_ids']):raise ValueError('Replay must use independent execution IDs')
if report['journeys']!=replay['journeys'] or report['stopped_on_red']!=replay['stopped_on_red']:
    raise ValueError('Replay outcomes differ; inspect before selecting this demo')
directory=Path('scenarios/bengaluru-hospital')
files=[directory/(args.name+suffix) for suffix in ('.json','.rou.xml','.metadata.json')]
files += [directory/'district.net.xml',Path('models/predictor.joblib'),Path('models/predictor.json')]
originals=[]
for run_id in report['run_ids']:
    result=Path('results')/args.name/run_id/'result.json'
    originals.append(json.loads(result.read_text()))
for result in originals:
    for path in (files[1],files[3]):
        if result['input_hashes'][str(path.resolve())]!=sha256(path):raise ValueError('Changed simulation input '+str(path))
ai=next(r for r in originals if r['controller']=='zelvo_ai')
if ai['input_hashes'][str(Path('models/predictor.joblib').resolve())]!=sha256(Path('models/predictor.joblib')):
    raise ValueError('Changed AI model')
manifest={'name':args.name,'config':str(files[0]),'comparison':str(comparison),'replay':str(args.replay),
    'target_met':True,'acceptance':{'journey_time_saved_percent':[45,55],'maximum_wait_s':2},
    'measured':{'journey_time_saved_percent':report['journey_time_saved_percent'],
                'red_stop_without_s':report['stopped_on_red']['without']['seconds'],
                'red_stop_with_s':report['stopped_on_red']['with']['seconds']},
    'curated_demo_not_population_benchmark':True,'engine_source_sha256':ai['input_hashes']['engine_source_sha256'],
    'sha256':{str(path):sha256(path) for path in files}}
path=Path('scenarios/demo-selection.json')
previous=path.with_name('demo-selection-v1.json')
if path.exists() and not previous.exists():shutil.copyfile(path,previous)
path.write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest['measured']))

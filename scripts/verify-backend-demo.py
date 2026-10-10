"""Replay the selected demo on a frozen engine without restarting the campaign."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from zelvo.campaign import verify
from zelvo.campaign_io import read, save
from zelvo.evaluation import compare
from zelvo.simulation.smoke import sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('results/evaluation-v1'))
    parser.add_argument('--output', type=Path, default=Path('results/backend-delivery'))
    parser.add_argument('--workers', type=int, choices=(1,2), default=2)
    args = parser.parse_args()
    root = args.root.resolve(); output = args.output.resolve()
    header = verify(root)
    selection = read('scenarios/demo-selection.json')
    for name, digest in selection['sha256'].items():
        if sha256(Path(name)) != digest:
            raise ValueError('Selected demo input changed: '+name)
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environment[name] = '1'
    code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));import libsumo;runpy.run_module('zelvo',run_name='__main__')"

    def execute(policy):
        command = [sys.executable, '-c', code, str(root/'engine'), 'run', '--config', selection['config'],
                   '--controller', policy, '--output', str(output/policy)]
        if policy == 'zelvo_ai':command += ['--model', str(root/'models/predictor.joblib')]
        with (output/(policy+'.stdout.log')).open('w') as stdout, (output/(policy+'.stderr.log')).open('w') as stderr:
            finished = subprocess.run(command, stdout=stdout, stderr=stderr, env=environment, timeout=800,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if finished.returncode:raise RuntimeError(policy+' replay failed; see delivery logs')
        return max((output/policy).glob('run-*/result.json'), key=lambda p:p.stat().st_mtime_ns)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        paths = dict(zip(('actuated', 'zelvo_ai'), pool.map(execute, ('actuated', 'zelvo_ai'))))
    results = {key:read(path) for key,path in paths.items()}
    comparison = compare(paths['actuated'], paths['zelvo_ai'])
    red = {key:sum(a['stopped_on_red_s'] for a in r['metrics']['approaches']) for key,r in results.items()}
    journeys = comparison['journeys']
    percent = 100*sum(j['saved_s'] for j in journeys)/sum(j['without_s'] for j in journeys)
    raw_checks = []
    for policy,result in results.items():
        trips = {t.get('id'):t for t in ET.parse(result['artifacts']['tripinfo']).getroot().findall('tripinfo')}
        for j in result['journeys']:
            trip = trips[j['vehicle_id']]
            raw_checks.append(j['completed'] and abs(float(trip.get('duration'))-j['journey_time_s'])<1e-6)
    accepted = (45<=percent<=55 and red['zelvo_ai']<=2 and all(raw_checks)
        and all(r['input_hashes']['engine_source_sha256']==header['engine_source_sha256']
            and r['status']=='completed' and not r['collision_events'] and not r['teleport_events']
            and r['metrics']['safety_audit_errors']==0 for r in results.values())
        and all(j['stopped_time_s']<=2.11 for j in results['zelvo_ai']['journeys']))
    report = {'accepted':accepted,'comparison':comparison,'journey_time_saved_percent':percent,
        'stopped_on_red_s':red,'raw_tripinfo_reconciled':all(raw_checks),
        'engine_source_sha256':header['engine_source_sha256'],'frozen_engine':str(root/'engine'/'zelvo'),
        'results':{key:str(path) for key,path in paths.items()},'selection':selection,
        'note':'Fresh full SUMO replay of a curated three-signal corridor; excluded from the paused large campaign. No population or isolated causal ML-benefit claim.'}
    save(output/'verification.json',report)
    print(json.dumps({k:report[k] for k in ('accepted','journey_time_saved_percent','stopped_on_red_s','raw_tripinfo_reconciled')}))
    if not accepted:raise SystemExit(1)


if __name__=='__main__':main()

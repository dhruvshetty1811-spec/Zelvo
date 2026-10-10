"""Run frozen district CLI replays and policy ablations outside the 20k ledger."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from zelvo.campaign import connect, get_job, verify
from zelvo.campaign_io import read, save
from zelvo.evaluation import compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    header = verify(root)
    with connect(root) as database:
        jobs = [dict(row) for row in database.execute(
            "SELECT jobs.*,attempts.result FROM jobs JOIN attempts USING(attempt_id) "
            "WHERE seed=? AND demand=? AND od=0 AND family='standard_one'",
            (header['seeds'][0], min(header['levels'])))]
    if len(jobs) != 2 or any(not j['result'] for j in jobs):
        raise ValueError('Complete the two low-load profile jobs first')
    config = root / get_job(root, jobs[0]['offset'])['config']
    output = root / 'verification-replays'
    output.mkdir(exist_ok=True)
    environment = os.environ.copy()
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environment[name] = '1'
    code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));import libsumo;runpy.run_module('zelvo',run_name='__main__')"
    paths = {}
    for policy in ('actuated', 'zelvo_ai', 'fixed_time', 'local_preemption', 'zelvo_analytical'):
        command = [sys.executable, '-c', code, str(root/'engine'), 'run', '--config', str(config),
                   '--controller', policy, '--output', str(output/policy)]
        if policy == 'zelvo_ai':
            command += ['--model', str(root/'models/predictor.joblib')]
        print(json.dumps({'starting_separate_replay': policy}), flush=True)
        with (output/(policy+'.stdout.log')).open('w') as stdout, (output/(policy+'.stderr.log')).open('w') as stderr:
            completed = subprocess.run(command, env=environment, stdout=stdout, stderr=stderr,
                                       timeout=header['horizon_s']*2+120,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        candidates = list((output/policy).glob('run-*/result.json'))
        if not candidates:
            raise RuntimeError(f'{policy} produced no result; see replay logs')
        paths[policy] = max(candidates, key=lambda p: p.stat().st_mtime)
        if completed.returncode:
            print(json.dumps({'policy': policy, 'exit_code': completed.returncode, 'result': str(paths[policy])}), flush=True)
    parity = {}
    for job in jobs:
        batch = read(job['result']); replay = read(paths[job['controller']])
        compare(Path(job['result']), paths[job['controller']])
        parity[job['controller']] = {
            'batch_run_id': batch['run_id'], 'cli_run_id': replay['run_id'],
            'same_journeys': batch['journeys'] == replay['journeys'],
            'same_approaches': batch['metrics'].get('approaches') == replay['metrics'].get('approaches'),
            'same_engine': batch['input_hashes']['engine_source_sha256'] == replay['input_hashes']['engine_source_sha256']}
    comparisons = {policy: compare(paths['actuated'], path) for policy, path in paths.items() if policy != 'actuated'}
    ai_vs_analytical = compare(paths['zelvo_analytical'], paths['zelvo_ai'])
    data = {'note': 'Five separate CLI executions outside the 20,000-job ledger. One district scenario; exploratory ablation, not population evidence. Parity covers headless CLI versus batch, not a frontend.',
            'paths': {k: str(v) for k, v in paths.items()}, 'parity': parity,
            'comparisons_against_actuated': comparisons, 'ai_vs_analytical': ai_vs_analytical,
            'all_parity_checks_passed': all(all(v for k, v in p.items() if k.startswith('same_')) for p in parity.values())}
    save(root/'pilot-verification.json', data)
    print(json.dumps({'all_parity_checks_passed': data['all_parity_checks_passed'], 'report': str(root/'pilot-verification.json')}))
    if not data['all_parity_checks_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

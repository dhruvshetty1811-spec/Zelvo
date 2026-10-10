"""Whitelist and hash a portable backend/demo evidence archive; no private files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from zelvo.campaign_io import engine_hash, read
from zelvo.config import load_scenario
from zelvo.simulation.smoke import sha256


def write_verified_zip(output, files, generated):
    """Verify member bytes before publishing; never archive an entire workspace."""
    names = list(files)+list(generated)
    if 'bundle-manifest.json' in names or len(names)!=len(set(names)) or any(not n or ':' in n
            or PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n for n in names):
        raise ValueError('Unsafe or duplicate archive member')
    digests = {name:sha256(path) for name,path in files.items()}
    digests.update({name:hashlib.sha256(data).hexdigest() for name,data in generated.items()})
    generated = {**generated,'bundle-manifest.json':(json.dumps({'schema_version':1,'sha256':digests},indent=2)+'\n').encode()}
    output = Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('Refusing to overwrite an evidence bundle')
    temporary = output.with_suffix(output.suffix+'.tmp')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name,path in files.items():archive.write(path,name)
        for name,data in generated.items():archive.writestr(name,data)
    with zipfile.ZipFile(temporary) as archive:
        for name,digest in digests.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('Archive verification failed: '+name)
    temporary.replace(output)
    return {'archive':str(output.resolve()),'sha256':sha256(output),'bytes':output.stat().st_size,'members':len(digests)+1}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--delivery',type=Path,default=Path('results/backend-delivery'))
    parser.add_argument('--campaign',type=Path,default=Path('results/evaluation-v1'))
    parser.add_argument('--output',type=Path,default=Path('dist/zelvo-backend.zip'))
    args = parser.parse_args()
    report = read(args.delivery/'verification.json')
    parity = read(args.campaign/'pilot-verification.json')
    if not report['accepted'] or not parity['all_parity_checks_passed']:
        raise ValueError('Passing demo and batch/CLI parity reports required')
    engine = Path(report['frozen_engine'])
    if engine_hash(engine)!=report['engine_source_sha256']:raise ValueError('Delivery engine changed')
    files = {f'src/zelvo/{p.relative_to(engine).as_posix()}':p for p in engine.rglob('*.py')}
    for name in ('pyproject.toml','uv.lock','ENGINE.md','IMPLEMENTATION.md','progress.md'):
        files[name] = Path(name)
    files['uv.lock'] = args.campaign/'uv.lock'
    for name in ('bootstrap.ps1','uv.ps1','download-uv.mjs'):
        files['scripts/'+name] = Path('scripts')/name
    files['evidence/demo-verification.json'] = args.delivery/'verification.json'
    files['evidence/pilot-verification.json'] = args.campaign/'pilot-verification.json'
    files['evidence/tests.txt'] = Path('reports/backend-final-tests.txt')
    files['evidence/previous-checkpoint-tests.txt'] = Path('reports/slice9-tests.txt')
    files['evidence/model-decision-audit.json'] = Path('reports/backend-model-decision-audit.json')
    files['evidence/authority-emulator.json'] = Path('results/emulator-check.json')
    original_to_member = {}
    unavailable = []
    config = load_scenario(Path(report['selection']['config']))
    files['scenario/district.net.xml'] = config.network_file
    original_to_member[str(config.network_file.resolve())]='scenario/district.net.xml'
    for index,path in enumerate(config.route_files):
        files[f'scenario/demand-{index}.rou.xml'] = path
        original_to_member[str(path.resolve())]=f'scenario/demand-{index}.rou.xml'
    for name in ('ATTRIBUTION.md','source.json','district.osm.xml','registry.json'):
        path = config.network_file.parent/name
        if path.exists():files['scenario/'+name] = path
    source = Path('scenarios/bengaluru/district.osm.xml')
    if source.exists():files['scenario/source-full.osm.xml'] = source
    for name in ('predictor.joblib','predictor.json'):
        files['models/'+name] = args.campaign/'models'/name
    for name,digest in report['selection']['sha256'].items():
        path=Path(name)
        if sha256(path)!=digest:raise ValueError('Selected input changed since verification: '+name)
        present=next((member for member,p in files.items() if p.resolve()==path.resolve()),None)
        if present is None:
            present='evidence/selected-inputs/'+path.name
            files[present]=path
        original_to_member[str(path.resolve())]=present
    for policy,result_path in report['results'].items():
        result = read(result_path)
        for key,filename in result['artifacts'].items():
            path = Path(filename)
            if not path.is_file():
                if key=='network_build_log':
                    unavailable.append({'policy':policy,'artifact':key,'reason':'Precompiled network; no netconvert process in this episode'})
                    continue
                raise ValueError('Missing evidence artifact '+filename)
            member = f'evidence/{policy}/{key}/{path.name}'
            files[member] = path
            original_to_member[str(path.resolve())] = member
    for policy,result_path in parity['paths'].items():
        for key,filename in read(result_path)['artifacts'].items():
            path = Path(filename)
            if not path.is_file():
                if key=='network_build_log':
                    unavailable.append({'policy':'ablation-'+policy,'artifact':key,'reason':'Precompiled network; no netconvert process in this episode'})
                    continue
                raise ValueError('Missing ablation artifact '+filename)
            member = f'evidence/ablation-{policy}/{key}/{path.name}'
            files[member] = path
            original_to_member[str(path.resolve())] = member
    ablation_result=read(next(iter(parity['paths'].values())))
    ablation=load_scenario(Path(ablation_result['artifacts']['config']))
    if sha256(ablation.network_file)!=sha256(config.network_file):raise ValueError('Unexpected ablation network')
    original_to_member[str(ablation.network_file.resolve())]='scenario/district.net.xml'
    for index,path in enumerate(ablation.route_files):
        files[f'scenario/ablation-demand-{index}.rou.xml']=path
        original_to_member[str(path.resolve())]=f'scenario/ablation-demand-{index}.rou.xml'
    portable_ablation=ablation.model_dump(mode='json')
    portable_ablation.update(network_file='district.net.xml',
        route_files=[f'ablation-demand-{i}.rou.xml' for i in range(len(ablation.route_files))])
    portable = config.model_dump(mode='json')
    portable.update(network_file='district.net.xml',route_files=[f'demand-{i}.rou.xml' for i in range(len(config.route_files))])
    commands = r"""# ZELVO backend reproduction

This bundle contains a validated backend and a curated SUMO demo. No UI or physical traffic-controller driver is included. The large evaluation campaign is paused and is not represented as complete.

Install matching SUMO 1.26.0. On Windows with Node available, run:

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
    .venv\Scripts\python.exe -m zelvo doctor
    .venv\Scripts\python.exe -m zelvo run --config scenario/demo.json --controller actuated --output results/baseline
    .venv\Scripts\python.exe -m zelvo run --config scenario/demo.json --controller zelvo_ai --model models/predictor.joblib --output results/zelvo

The exact source, model and demand are included. Initial setup downloads open-source dependencies; no paid service is required. For other supported platforms, install Python 3.12 and the project dependencies from uv.lock with uv sync.

To reproduce the separate five-policy pilot, use scenario/ablation.json instead of scenario/demo.json and choose actuated, fixed_time, local_preemption, zelvo_analytical or zelvo_ai. Supply --model only for zelvo_ai. Ordinary traffic remains at this pilot's horizon, so a nonzero incomplete-status exit is expected even when its ambulance finishes; inspect result.json. Advanced campaign/preparation commands in ENGINE.md refer to the full development workspace, not a complete large evaluation dataset in this bundle.

Evidence reports preserve original absolute paths. evidence/path-map.json maps archived demo artifacts to their bundle locations. bundle-manifest.json hashes every member except itself. The archive has a separate SHA-256 recorded beside it. Inspect evidence/demo-verification.json for measured outcomes, tradeoffs and safety diagnostics. The selected demo is not evidence of average city performance; the five-policy pilot is one additional district scenario. Detailed model training/split limitations are in models/predictor.json and ENGINE.md.
"""
    generated = {'README.md':commands.encode(),'scenario/demo.json':(json.dumps(portable,indent=2)+'\n').encode(),
                 'scenario/ablation.json':(json.dumps(portable_ablation,indent=2)+'\n').encode(),
                 'evidence/path-map.json':(json.dumps(original_to_member,indent=2)+'\n').encode(),
                 'evidence/unavailable-artifacts.json':(json.dumps(unavailable,indent=2)+'\n').encode()}
    summary = write_verified_zip(args.output,files,generated)
    args.output.with_suffix('.sha256').write_text(summary['sha256']+'  '+args.output.name+'\n')
    print(json.dumps(summary))


if __name__=='__main__':main()

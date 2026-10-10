"""Frozen local experiment execution: durable jobs, isolated native workers, no retries hidden."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from zelvo.campaign_io import compress_result,engine_hash,exclusive,process_alive,read,resources,save
from zelvo.config import load_scenario
from zelvo.simulation.smoke import sha256

TERMINAL=('completed','incomplete','failed','timed_out','worker_crashed')
PRIMARY_CONTROLLERS=('actuated','zelvo_ai')
CONTROLLERS=('fixed_time','actuated','local_preemption','zelvo_analytical','zelvo_ai')
PACKAGES=('numpy','scipy','scikit-learn','libsumo','sumo-data','pyproj','pydantic','traci','sumolib')


def connect(root):
    import sqlite3
    database=sqlite3.connect(Path(root)/'ledger.sqlite',timeout=30)
    database.row_factory=sqlite3.Row
    database.execute('PRAGMA journal_mode=WAL')
    database.execute('PRAGMA synchronous=FULL')
    database.executescript('''CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY, offset INTEGER NOT NULL, scenario_id TEXT NOT NULL,
        seed INTEGER, demand INTEGER, od INTEGER, family TEXT, controller TEXT,
        status TEXT NOT NULL DEFAULT 'queued', attempt_id TEXT);
        CREATE TABLE IF NOT EXISTS attempts (
        attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL,
        started REAL NOT NULL, ended REAL, pid INTEGER, result TEXT, error TEXT,
        wall_s REAL, peak_rss_bytes INTEGER, bytes INTEGER);
        CREATE INDEX IF NOT EXISTS job_status ON jobs(status);''')
    return database


def freeze(root,directory,*,model,seeds,levels,horizon=900,wall_timeout=1200,scenarios=None,assets=None,controllers=PRIMARY_CONTROLLERS):
    model_groups=read(Path(model).with_suffix('.json')).get('groups',{})
    development_seeds={seed for group in model_groups.values() for seed in group}
    if development_seeds.intersection(seeds):raise ValueError('Evaluation seeds overlap frozen model development seeds')
    if not controllers or len(set(controllers))!=len(controllers) or any(c not in CONTROLLERS for c in controllers):
        raise ValueError('Unique supported controllers are required')
    root=Path(root).resolve()
    if root.exists() and any(root.iterdir()) and scenarios is None:raise ValueError('Freeze requires a new empty directory')
    if (root/'header.json').exists() or (root/'ledger.sqlite').exists():raise ValueError('This campaign is already frozen')
    root.mkdir(parents=True,exist_ok=True)
    if scenarios is None:
        from zelvo.scenario_bank import prepare_bank
        scenarios,assets,provenance=prepare_bank(root,Path(directory),seeds=seeds,levels=levels,
            horizon=horizon,wall_timeout=wall_timeout)
    else:
        assets=assets or {}
        provenance={'note':'Explicit custom fixture; not the 20,000-job evaluation population'}
    source=Path(__file__).resolve().parent
    shutil.copytree(source,root/'engine'/'zelvo',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    lock=source.parents[1]/'uv.lock'
    shutil.copyfile(lock,root/'uv.lock')
    models=root/'models';models.mkdir()
    for original in (Path(model),Path(model).with_suffix('.json')):
        target=models/('predictor'+original.suffix)
        shutil.copyfile(original,target)
        assets[target.relative_to(root).as_posix()]=sha256(target)
    assets['uv.lock']=sha256(root/'uv.lock')
    manifest=root/'manifest.jsonl'
    with manifest.open('wb') as stream,connect(root) as database:
        for scenario in scenarios:
            for controller in controllers:
                job={**scenario,'controller':controller,'job_id':scenario['scenario_id']+'--'+controller}
                offset=stream.tell()
                stream.write((json.dumps(job,separators=(',',':'))+'\n').encode())
                database.execute('INSERT INTO jobs(job_id,offset,scenario_id,seed,demand,od,family,controller) VALUES (?,?,?,?,?,?,?,?)',
                    (job['job_id'],offset,job['scenario_id'],job['seed'],job['demand'],job['od'],job['family'],controller))
        stream.flush();os.fsync(stream.fileno())
    from zelvo.runtime import discover_tools
    header={'schema_version':1,'created_unix_s':time.time(),'root':str(root),
        'jobs':len(scenarios)*len(controllers),'scenarios':len(scenarios),'seeds':list(seeds),'levels':list(levels),
        'controllers':list(controllers),'manifest_sha256':sha256(manifest),'assets':assets,
        'package_versions':{name:importlib.metadata.version(name) for name in PACKAGES},
        'engine_source_sha256':engine_hash(root/'engine'/'zelvo'),'runtime':discover_tools().model_dump(mode='json'),
        'scenario_provenance':provenance,'horizon_s':horizon,'physics_step_s':.1,
        'primary_comparison':['actuated','zelvo_ai'],'uncertainty_cluster':'entire seed',
        'improvement_target_percent':[45,55],
        'primary_estimand':'Percent reduction in mean journey time across matched complete scenarios; censored/missing pairs and completion rates reported separately',
        'failure_policy':'First attempt retained; no automatic retry; resume queued jobs only',
        'fidelity':'Same run_episode engine and 100ms physics; record all episodes and censored outcomes',
        'collection':'Evaluation labels retained; never retrain the frozen model on evaluation outcomes',
        'baseline':'Ordinary SUMO actuation without ZELVO signal writes',
        'demo_excluded':'Tuned 46.9% demo is not a campaign scenario or acceptance requirement',
        'resource_defaults':{'workers':2,'minimum_free_memory_bytes':768*1024**2,'minimum_free_disk_bytes':5*1024**3}}
    save(root/'header.json',header)
    return header


def verify(root,*,all_assets=True):
    root=Path(root).resolve();header=read(root/'header.json')
    if str(root)!=header['root']:raise ValueError('Frozen absolute input paths require the original campaign location')
    if sha256(root/'manifest.jsonl')!=header['manifest_sha256']:raise ValueError('Changed job manifest')
    if engine_hash(root/'engine'/'zelvo')!=header['engine_source_sha256']:raise ValueError('Changed frozen engine')
    if all_assets:
        for name,digest in header['assets'].items():
            if sha256(root/name)!=digest:raise ValueError('Changed frozen asset '+name)
    return header


def get_job(root,offset):
    with (Path(root)/'manifest.jsonl').open('rb') as stream:
        stream.seek(offset)
        return json.loads(stream.readline())


def worker(root,offset,attempt_id):
    from zelvo.simulation.runner import run_episode
    root=Path(root).resolve();attempt=root/'attempts'/attempt_id
    attempt.mkdir(parents=True,exist_ok=True)
    with exclusive(attempt/'worker.lock'):
        started=time.monotonic()
        save(attempt/'started.json',{'pid':os.getpid(),'started':time.time()})
        receipt={'attempt_id':attempt_id,'status':'failed','result':None,'error':None}
        try:
            header=read(root/'header.json')
            if engine_hash(Path(__file__).parent)!=header['engine_source_sha256']:raise ValueError('Worker imported a different engine')
            if any(importlib.metadata.version(name)!=version for name,version in header['package_versions'].items()):
                raise ValueError('Installed package versions differ from the frozen environment')
            job=get_job(root,offset)
            config_path=root/job['config']
            config=load_scenario(config_path)
            required=[config_path,config.network_file,*config.route_files,root/'uv.lock']
            if job['controller']=='zelvo_ai':required += [root/'models/predictor.joblib',root/'models/predictor.json']
            for path in required:
                key=path.relative_to(root).as_posix()
                if sha256(path)!=header['assets'][key]:raise ValueError('Changed frozen job input '+key)
            result=run_episode(config_path,root/'episodes',controller=job['controller'],
                model_path=root/'models/predictor.joblib' if job['controller']=='zelvo_ai' else None,
                collect_training=True,run_id='run-'+attempt_id)
            path=Path(result.artifacts['result'])
            from zelvo.campaign_io import prediction_quality
            measured=read(path)
            measured['metrics']['evaluation_prediction_quality']=prediction_quality(measured)
            save(path,measured)
            compressed=compress_result(path)
            receipt.update(status=result.status.value,result=str(path),error=None if result.failure is None else result.failure.message,
                bytes=sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file()))
            if compressed['input_hashes']['engine_source_sha256']!=header['engine_source_sha256']:
                raise ValueError('Result engine hash differs from frozen engine')
        except Exception as error:
            receipt.update(status='failed',error=type(error).__name__+': '+str(error))
        receipt.update(wall_s=time.monotonic()-started,peak_rss_bytes=resources(root)['peak_rss_bytes'],ended=time.time())
        save(attempt/'receipt.json',receipt)
    return receipt


def worker_command(root,offset,attempt_id):
    code="import runpy,sys;sys.path.insert(0,sys.argv.pop(1));import libsumo;runpy.run_module('zelvo.campaign',run_name='__main__')"
    return [sys.executable,'-c',code,str(Path(root)/'engine'),'worker','--root',str(root),
        '--offset',str(offset),'--attempt',attempt_id]


def launch(root,job,attempt_id):
    root=Path(root);attempt=root/'attempts'/attempt_id;attempt.mkdir(parents=True,exist_ok=True)
    config=load_scenario(root/get_job(root,job['offset'])['config'])
    environment=os.environ.copy()
    for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        environment[name]='1'
    began=time.monotonic();peak=0
    with (attempt/'stdout.log').open('w') as stdout,(attempt/'stderr.log').open('w') as stderr:
        process=subprocess.Popen(worker_command(root,job['offset'],attempt_id),stdout=stdout,stderr=stderr,env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        with connect(root) as database:
            database.execute('UPDATE attempts SET pid=? WHERE attempt_id=?',(process.pid,attempt_id))
        while process.poll() is None:
            peak=max(peak,resources(root,process.pid)['peak_rss_bytes'] or 0)
            if time.monotonic()-began>config.wall_timeout_s+90:
                process.kill();process.wait()
                save(attempt/'receipt.json',{'attempt_id':attempt_id,'status':'timed_out','result':None,
                    'error':'Parent wall deadline exceeded; owned embedded worker terminated; partial episode retained',
                    'wall_s':time.monotonic()-began,'peak_rss_bytes':peak,'ended':time.time()})
                break
            time.sleep(1)
    if not (attempt/'receipt.json').exists():
        result=root/'episodes'/('run-'+attempt_id)/'result.json'
        save(attempt/'receipt.json',{'attempt_id':attempt_id,'status':'worker_crashed','result':str(result) if result.exists() else None,
            'error':f'Worker exit {process.returncode} without receipt; no automatic retry',
            'wall_s':time.monotonic()-began,'peak_rss_bytes':peak,'ended':time.time()})
    return attempt_id


def reconcile(root,database):
    """Adopt receipts or live workers; never duplicate an interrupted logical job."""
    for row in database.execute("SELECT * FROM attempts WHERE status='running'").fetchall():
        attempt=Path(root)/'attempts'/row['attempt_id']
        attempt.mkdir(parents=True,exist_ok=True)
        receipt=attempt/'receipt.json'
        if receipt.exists():
            data=read(receipt)
        elif (attempt/'started.json').exists():
            live=False
            try:
                with exclusive(attempt/'worker.lock'):pass
            except RuntimeError:live=True
            if live:
                job=database.execute('SELECT offset FROM jobs WHERE job_id=?',(row['job_id'],)).fetchone()
                config=load_scenario(Path(root)/get_job(root,job['offset'])['config'])
                if time.time()-row['started']<=config.wall_timeout_s+95:continue
                # A held attempt lock plus its PID receipt identifies this campaign's orphan worker.
                import signal
                pid=read(attempt/'started.json')['pid']
                if process_alive(pid):os.kill(pid,signal.SIGTERM)
                data={'status':'timed_out','error':'Recovered owned worker exceeded wall deadline; partial records retained',
                      'ended':time.time(),'result':None}
                save(receipt,{**data,'attempt_id':row['attempt_id']})
            else:
                data={'status':'worker_crashed','error':'Worker lock released without receipt; no automatic retry',
                      'ended':time.time(),'result':None}
                save(receipt,{**data,'attempt_id':row['attempt_id']})
        elif time.time()-row['started']<15:continue
        else:
            data={'status':'worker_crashed','error':'Coordinator recovered an abandoned attempt; no automatic retry',
                'ended':time.time(),'result':None}
            save(receipt,{**data,'attempt_id':row['attempt_id']})
        if data['status'] not in TERMINAL:raise ValueError('Invalid worker receipt status')
        database.execute('UPDATE attempts SET status=?,ended=?,result=?,error=?,wall_s=?,peak_rss_bytes=?,bytes=? WHERE attempt_id=?',
            (data['status'],data['ended'],data.get('result'),data.get('error'),data.get('wall_s'),data.get('peak_rss_bytes'),data.get('bytes'),row['attempt_id']))
        database.execute('UPDATE jobs SET status=? WHERE job_id=?',(data['status'],row['job_id']))
    database.commit()


def status(root):
    with connect(root) as database:
        counts={row[0]:row[1] for row in database.execute('SELECT status,count(*) FROM jobs GROUP BY status')}
        total=sum(counts.values())
        attempts=database.execute('SELECT count(*) FROM attempts').fetchone()[0]
        completed_journeys=0
        for row in database.execute('SELECT result FROM attempts WHERE result IS NOT NULL'):
            if Path(row[0]).exists():completed_journeys+=sum(j['completed'] for j in read(row[0])['journeys'])
    return {'updated_unix_s':time.time(),'jobs':total,'counts':counts,'attempts':attempts,
        'terminal_jobs':sum(counts.get(s,0) for s in TERMINAL),'completed_ambulance_journeys':completed_journeys,
        'resource_snapshot':resources(root)}


def run(root,*,workers=2,max_jobs=None,job_ids=None):
    root=Path(root).resolve()
    if not 1<=workers<=4:raise ValueError('Choose 1–4 workers after profiling')
    header=verify(root)
    with exclusive(root/'coordinator.lock'),connect(root) as database,ThreadPoolExecutor(max_workers=workers) as pool:
        start=time.monotonic();futures={};dispatched=0
        while True:
            for future in list(futures):
                if future.done():
                    attempt_id=futures.pop(future)
                    try:future.result()
                    except Exception as error:
                        save(root/'attempts'/attempt_id/'receipt.json',{'attempt_id':attempt_id,'status':'worker_crashed',
                            'error':repr(error),'ended':time.time(),'result':None})
            reconcile(root,database)
            running=database.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0]
            limits=header['resource_defaults'];available=resources(root)
            permitted=available['disk_free_bytes']>=limits['minimum_free_disk_bytes'] and (
                available['available_memory_bytes'] is None or available['available_memory_bytes']>=limits['minimum_free_memory_bytes'])
            stopped=(root/'STOP').exists() or max_jobs is not None and dispatched>=max_jobs
            waiting=database.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid").fetchall()
            if job_ids is not None:waiting=[job for job in waiting if job['job_id'] in job_ids]
            while waiting and running<workers and permitted and not stopped:
                job=waiting.pop(0);attempt_id=uuid.uuid4().hex
                database.execute("INSERT INTO attempts(attempt_id,job_id,status,started) VALUES (?,?,'running',?)",
                    (attempt_id,job['job_id'],time.time()))
                database.execute("UPDATE jobs SET status='running',attempt_id=? WHERE job_id=? AND status='queued'",(attempt_id,job['job_id']))
                database.commit()
                futures[pool.submit(launch,root,dict(job),attempt_id)]=attempt_id
                running+=1;dispatched+=1
                stopped=(root/'STOP').exists() or max_jobs is not None and dispatched>=max_jobs
            counts={row[0]:row[1] for row in database.execute('SELECT status,count(*) FROM jobs GROUP BY status')}
            save(root/'status.json',{'updated_unix_s':time.time(),'coordinator_pid':os.getpid(),'jobs':header['jobs'],'counts':counts,
                'dispatched_this_session':dispatched,'elapsed_wall_s':time.monotonic()-start,
                'stop_requested':(root/'STOP').exists(),'resource_limited':not permitted,'resources':available})
            if not running and (stopped or not waiting):break
            time.sleep(2)
    return status(root)


def profile(root,workers=2):
    root=Path(root).resolve();header=verify(root)
    first=header['seeds'][0];low=min(header['levels']);high=max(header['levels'])
    with connect(root) as database:
        ids=[row[0] for row in database.execute('SELECT job_id FROM jobs WHERE seed=? AND od=0 AND '
            "((family='standard_one' AND demand=?) OR (family='queued_corridor' AND demand=?))",(first,low,high))]
        queued=database.execute('SELECT count(*) FROM jobs WHERE job_id IN ('+','.join('?' for _ in ids)+") AND status='queued'",ids).fetchone()[0]
    if not ids or queued!=len(ids):raise ValueError('Profile jobs must all be queued; use a separate saved profile for repeats')
    began=time.monotonic();run(root,workers=workers,job_ids=ids)
    elapsed=time.monotonic()-began
    with connect(root) as database:
        rows=[dict(r) for r in database.execute('SELECT attempts.* FROM attempts WHERE job_id IN ('+','.join('?' for _ in ids)+')',ids)]
    terminal=sum(r['status'] in TERMINAL for r in rows)
    completed=sum(r['status']=='completed' for r in rows)
    bytes_values=[r['bytes'] for r in rows if r['bytes'] is not None]
    data={'workers':workers,'job_ids':ids,'actual_terminal_executions':terminal,'whole_network_completed':completed,
        'elapsed_wall_s':elapsed,'executions_per_hour':terminal*3600/elapsed,
        'projected_20000_execution_wall_hours':elapsed/terminal*20000/3600 if terminal else None,
        'projected_20000_episode_bytes':sum(bytes_values)/len(bytes_values)*20000 if bytes_values else None,
        'peak_worker_rss_bytes':max((r['peak_rss_bytes'] or 0 for r in rows),default=0),
        'note':'Projection from mixed low/high-load real episodes at unchanged fidelity; not a completion promise; failed/incomplete executions count as terminal, not successes'}
    save(root/'profile.json',data)
    return data


def main():
    parser=argparse.ArgumentParser(prog='zelvo-campaign')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('freeze');p.add_argument('--root',type=Path,required=True)
    p.add_argument('--directory',type=Path,default=Path('scenarios/bengaluru-hospital'))
    p.add_argument('--model',type=Path,default=Path('models/predictor.joblib'))
    p.add_argument('--seeds',type=int,default=50);p.add_argument('--first-seed',type=int,default=20000)
    p.add_argument('--controllers',nargs='+',choices=CONTROLLERS,default=list(PRIMARY_CONTROLLERS))
    p.add_argument('--levels',type=int,nargs='+',default=[300,600,1200,2400])
    p.add_argument('--horizon',type=float,default=900);p.add_argument('--wall-timeout',type=float,default=1200)
    p=sub.add_parser('run');p.add_argument('--root',type=Path,required=True)
    p.add_argument('--workers',type=int,default=2);p.add_argument('--max-jobs',type=int)
    p.add_argument('--jobs',nargs='+')
    p=sub.add_parser('profile');p.add_argument('--root',type=Path,required=True);p.add_argument('--workers',type=int,default=2)
    for command in ('status','verify','report','audit'):
        p=sub.add_parser(command);p.add_argument('--root',type=Path,required=True)
    p=sub.add_parser('worker');p.add_argument('--root',type=Path,required=True)
    p.add_argument('--offset',type=int,required=True);p.add_argument('--attempt',required=True)
    args=parser.parse_args()
    if args.command=='freeze':
        if args.seeds<1:raise ValueError('At least one seed is required')
        result=freeze(args.root,args.directory,model=args.model,seeds=list(range(args.first_seed,args.first_seed+args.seeds)),
            levels=args.levels,horizon=args.horizon,wall_timeout=args.wall_timeout,controllers=args.controllers)
        print(json.dumps({key:result[key] for key in ('jobs','scenarios','engine_source_sha256')}))
    elif args.command=='run':print(json.dumps(run(args.root,workers=args.workers,max_jobs=args.max_jobs,job_ids=args.jobs)))
    elif args.command=='status':print(json.dumps(status(args.root)))
    elif args.command=='verify':print(json.dumps({'verified_jobs':verify(args.root)['jobs']}))
    elif args.command=='worker':worker(args.root,args.offset,args.attempt)
    elif args.command=='profile':print(json.dumps(profile(args.root,args.workers)))
    elif args.command=='audit':
        from zelvo.campaign_audit import audit
        print(json.dumps(audit(args.root)))
    else:
        from zelvo.campaign_report import report
        print(json.dumps(report(args.root)))


if __name__=='__main__':main()

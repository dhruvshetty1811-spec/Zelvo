import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

from zelvo.campaign import connect,freeze,reconcile,run,status,verify
from zelvo.campaign_io import compress_result,exclusive,read,save
from zelvo.campaign_report import clustered_estimate,report
from zelvo.campaign_audit import audit
from zelvo.simulation.smoke import sha256


def test_lossless_archive_publishes_references_and_keeps_plain_config(tmp_path):
    raw=tmp_path/'events.jsonl';raw.write_text('{"event":"measured"}\n'*100)
    config=tmp_path/'config.json';config.write_text('{}')
    result=tmp_path/'result.json'
    save(result,{'artifacts':{'events':str(raw),'config':str(config),'result':str(result)}})
    digest=sha256(raw)
    compressed=compress_result(result)
    assert not raw.exists() and config.exists()
    assert compressed['archive_integrity']['events']['uncompressed_sha256']==digest
    with gzip.open(compressed['artifacts']['events'],'rt') as stream:assert len(stream.readlines())==100
    assert compress_result(result)['archive_integrity']==compressed['archive_integrity']


def test_coordinator_lock_excludes_duplicate_owner_and_releases(tmp_path):
    lock=tmp_path/'lock'
    with exclusive(lock):
        with pytest.raises(RuntimeError,match='holds'):
            with exclusive(lock):pass
    with exclusive(lock):pass


def test_cluster_bootstrap_preserves_seed_groups_and_reports_regressions():
    pairs=[{'seed':1,'without_s':100,'with_s':50} for _ in range(100)]
    pairs += [{'seed':2,'without_s':100,'with_s':110}]
    measured=clustered_estimate(pairs,repetitions=500)
    assert measured['seed_clusters']==2
    assert measured['regressed_scenarios']==1
    assert measured['cluster_bootstrap_95_percent'][0]<=-10
    assert measured['cluster_bootstrap_95_percent'][1]>=50
    assert clustered_estimate([])['mean_saved_s'] is None


def test_recovery_preserves_abandoned_attempt_without_dispatching_duplicate(tmp_path):
    with connect(tmp_path) as database:
        database.execute("INSERT INTO jobs(job_id,offset,scenario_id,status,attempt_id) VALUES ('job',0,'scenario','running','dead')")
        database.execute("INSERT INTO attempts(attempt_id,job_id,status,started) VALUES ('dead','job','running',0)")
        database.commit()
        reconcile(tmp_path,database)
        assert database.execute('SELECT status FROM jobs').fetchone()[0]=='worker_crashed'
        reconcile(tmp_path,database)
        assert database.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
    assert read(tmp_path/'attempts/dead/receipt.json')['status']=='worker_crashed'


def test_evaluation_refuses_model_development_seed_overlap(tmp_path):
    manifest=tmp_path/'model.json';save(manifest,{'groups':{'train':[1000],'test':[1001]}})
    with pytest.raises(ValueError,match='overlap'):
        freeze(tmp_path/'campaign',None,model=manifest.with_suffix('.joblib'),seeds=[1001],levels=[60])


@pytest.fixture
def frozen_fixture(tmp_path):
    model=Path('models/predictor.joblib')
    if not model.exists():pytest.skip('Actual locally trained model required for campaign integration')
    from zelvo.runtime import discover_tools
    root=tmp_path/'campaign';inputs=root/'inputs';inputs.mkdir(parents=True)
    network=inputs/'net.xml'
    runtime=discover_tools()
    subprocess.run([str(runtime.netconvert_binary),'--node-files','scenarios/smoke/smoke.nod.xml',
        '--edge-files','scenarios/smoke/smoke.edg.xml','--output-file',str(network),
        '--tls.default-type','actuated','--tls.allred.time','2','--tls.yellow.time','3','--no-turnarounds','true'],
        check=True,capture_output=True,timeout=60)
    routes=inputs/'routes.xml';shutil.copyfile('scenarios/smoke/smoke.rou.xml',routes)
    scenarios=[];assets={p.relative_to(root).as_posix():sha256(p) for p in (network,routes)}
    for kind in ('valid','failure'):
        path=inputs/(kind+'.json')
        save(path,{'scenario_id':kind,'seed':42,'controller':'actuated','network_file':str(network),
            'route_files':[str(routes)],'step_length_s':.1,'horizon_s':65,'wall_timeout_s':60,'backend':'libsumo',
            'expected_journeys':[{'vehicle_id':'ambulance-0','scheduled_departure_s':0}],
            'incidents':[] if kind=='valid' else [{'lane':'missing-incident-lane','start_s':1,'end_s':2,'speed_mps':0}]})
        assets[path.relative_to(root).as_posix()]=sha256(path)
        scenarios.append({'scenario_id':kind,'seed':42,'demand':60,'od':0,'family':kind,'config':path.relative_to(root).as_posix()})
    freeze(root,None,model=model,seeds=[42],levels=[60],horizon=65,scenarios=scenarios,assets=assets,
           controllers=('fixed_time','actuated','local_preemption','zelvo_analytical','zelvo_ai'))
    return root


@pytest.mark.integration
def test_real_frozen_workers_resume_without_duplicate_or_erased_failures(frozen_fixture):
    root=frozen_fixture
    first=run(root,workers=2,max_jobs=2)
    assert first['attempts']==2 and first['terminal_jobs']==2
    (root/'STOP').write_text('dispatch stop test')
    assert run(root,workers=2)['attempts']==2
    (root/'STOP').unlink()
    final=run(root,workers=2)
    assert final['attempts']==10 and final['terminal_jobs']==10
    assert final['counts']['failed']==5
    assert run(root,workers=2)['attempts']==10
    summary=report(root)
    assert summary['planned']==10 and summary['terminal']==10
    assert summary['entire_campaign_target_established'] is False
    evidence=read(root/'timing-audit-20.json')
    assert evidence['sample_size']==10
    assert all(e['started_utc'] and e['ended_utc'] and e['worker_wall_s'] is not None for e in evidence['executions'])
    assert audit(root)['all_checks_passed']
    with connect(root) as database:
        results=[read(row[0]) for row in database.execute('SELECT result FROM attempts WHERE result IS NOT NULL')]
    assert len(results)==10
    assert all(r['input_hashes']['engine_source_sha256']==read(root/'header.json')['engine_source_sha256'] for r in results)
    assert any(r['metrics']['evaluation_prediction_quality']['labelled_eta_count']>0 for r in results)
    assert all(Path(r['artifacts']['tripinfo']).suffix=='.gz' for r in results)


def test_frozen_asset_changes_are_rejected_before_dispatch(frozen_fixture):
    root=frozen_fixture
    (root/'inputs/routes.xml').write_text('<routes/>')
    with pytest.raises(ValueError,match='Changed frozen asset'):verify(root)
    assert status(root)['attempts']==0

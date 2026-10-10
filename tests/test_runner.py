import json
from pathlib import Path
import pytest
from zelvo.simulation.runner import run_episode


@pytest.mark.integration
@pytest.mark.parametrize('controller',['fixed_time','actuated','local_preemption','zelvo_analytical'])
def test_measured_runner_variants_persist_crossings_and_recovery(tmp_path,controller):
    result=run_episode(Path('scenarios/smoke/smoke.json'),tmp_path,controller=controller,horizon=65)
    assert result.failure is None
    assert result.journeys[0].completed
    assert result.simulated_duration_s==65
    assert result.journeys[0].stopped_time_s is not None
    approach=result.metrics['approaches'][0]
    assert approach['detected_s']<=approach['first_green_s']<=approach['crossed_s']
    assert result.metrics['safety_audit_errors']==0
    assert result.metrics['ordinary']['scheduled']==1
    assert Path(result.artifacts['result']).is_file()


@pytest.mark.integration
def test_ai_requires_actual_model_and_keeps_failure(tmp_path):
    result=run_episode(Path('scenarios/smoke/smoke.json'),tmp_path,controller='zelvo_ai')
    assert result.status=='failed'
    assert 'trained' in result.failure.message
    assert Path(result.artifacts['result']).is_file()


@pytest.mark.integration
@pytest.mark.parametrize('controller',['actuated','fixed_time','zelvo_analytical'])
def test_embedded_and_socket_journeys_agree(tmp_path,controller):
    import importlib.util
    import subprocess
    import sys
    from zelvo.contracts import RunResult
    if importlib.util.find_spec('libsumo') is None:pytest.skip('libsumo not installed')
    def child(backend):
        output=tmp_path/backend
        subprocess.run([sys.executable,'-m','zelvo','run','--config','scenarios/smoke/smoke.json',
            '--controller',controller,'--backend',backend,'--horizon','65','--output',str(output)],
            check=True,capture_output=True,text=True,timeout=90)
        return RunResult.model_validate_json(next(output.glob('*/result.json')).read_text())
    a=child('traci')
    b=child('libsumo')
    assert a.failure is b.failure is None
    assert a.journeys==b.journeys
    assert a.metrics['approaches']==b.metrics['approaches']
    assert b.metrics['safety_audit_errors']==0


@pytest.mark.integration
@pytest.mark.parametrize('case',['following','conflicting'])
def test_real_multiple_ambulances_complete_with_individual_release(tmp_path,case):
    import copy
    import xml.etree.ElementTree as ET
    from zelvo.config import load_scenario
    from zelvo.contracts import ExpectedJourney
    config=load_scenario(Path('scenarios/smoke/smoke.json'))
    routes=ET.parse(config.route_files[0])
    root=routes.getroot()
    if case=='following':
        vehicle=copy.deepcopy(next(v for v in root.findall('vehicle') if v.get('id')=='ambulance-0'))
        vehicle.set('id','ambulance-1')
        vehicle.set('depart','3')
        root.append(vehicle)
        other=ExpectedJourney(vehicle_id='ambulance-1',scheduled_departure_s=3)
    else:
        other=ExpectedJourney(vehicle_id='cross-0',scheduled_departure_s=0)
    route_file=tmp_path/'multiple.rou.xml'
    routes.write(route_file,encoding='utf-8')
    config=config.model_copy(update={'route_files':(route_file,),
                                    'expected_journeys':(*config.expected_journeys,other),'horizon_s':100})
    path=tmp_path/'scenario.json'
    path.write_text(config.model_dump_json())
    result=run_episode(path,tmp_path/'runs',controller='local_preemption')
    assert result.failure is None
    assert all(j.completed for j in result.journeys)
    assert result.metrics['safety_audit_errors']==0
    assert result.collision_events==0
    events=[json.loads(line) for line in Path(result.artifacts['events']).read_text().splitlines()]
    if case=='conflicting':assert any(e['kind']=='arbitration' for e in events)
    if case=='following':
        second=next(a for a in result.metrics['approaches'] if a['vehicle']=='ambulance-1')
        releases=[e['simulation_time_s'] for e in events if e['kind']=='priority_released']
        assert releases and min(releases)>=second['crossed_s']


@pytest.mark.integration
@pytest.mark.parametrize('fault',['stale','incident'])
def test_real_fault_episode_keeps_safe_progress_and_explicit_events(tmp_path,fault):
    from zelvo.config import load_scenario
    from zelvo.contracts import LaneIncident
    config=load_scenario(Path('scenarios/smoke/smoke.json'))
    changes={'horizon_s':90}
    if fault=='stale':changes['observation_delay_s']=5
    else:changes['incidents']=(LaneIncident(lane='wc_0',start_s=6,end_s=14,speed_mps=0),)
    config=config.model_copy(update=changes)
    path=tmp_path/'scenario.json'
    path.write_text(config.model_dump_json())
    result=run_episode(path,tmp_path/'runs',controller='zelvo_analytical')
    assert result.failure is None
    assert result.journeys[0].completed
    assert result.metrics['safety_audit_errors']==0
    counts=result.metrics['event_counts']
    if fault=='stale':
        assert counts.get('planner_fallback',0)>0
        assert counts.get('priority_requested',0)==0
    else:
        assert counts['incident_started']==counts['incident_finished']==1
        assert result.journeys[0].journey_time_s>32.4

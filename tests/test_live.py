import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from zelvo.api import create_app, origin_allowed
from zelvo.config import load_scenario
from zelvo.live import DemoSettings, LiveTelemetry, SessionManager, prepare_inputs
from zelvo.simulation.runner import run_episode


@pytest.mark.parametrize('density,count',[('light',150),('moderate',300),('heavy',600)])
def test_live_demand_is_deterministic_and_preserves_ambulance(tmp_path,density,count):
    settings=DemoSettings(density=density,seed=17,dispatch_s=90)
    a=prepare_inputs(settings,tmp_path/'a')
    b=prepare_inputs(settings,tmp_path/'b')
    assert a['demand_sha256']==b['demand_sha256']
    assert a['ordinary_vehicle_count']==count
    config=load_scenario(tmp_path/'a/scenario.json')
    root=ET.parse(config.route_files[0]).getroot()
    vehicles=root.findall('vehicle')
    assert len({v.get('id') for v in vehicles})==count+1
    assert [float(v.get('depart')) for v in vehicles]==sorted(float(v.get('depart')) for v in vehicles)
    ambulance=next(v for v in vehicles if v.get('id')=='ambulance-0')
    assert ambulance.get('depart')=='90'
    assert config.expected_journeys[0].scheduled_departure_s==90
    assert config.dynamic_routing is False
    assert root.find("vType[@id='ambulance']").get('maxSpeed')=='16.67'


@pytest.mark.parametrize('percent,count', [(0,0),(1,3),(37,111),(100,300),(137,411),(200,600)])
def test_percentage_demand_changes_real_inputs(tmp_path,percent,count):
    settings=DemoSettings(density='heavy',density_percent=percent,seed=17)
    a=prepare_inputs(settings,tmp_path/'a')
    b=prepare_inputs(settings,tmp_path/'b')
    assert a['demand_sha256']==b['demand_sha256']
    assert a['ordinary_vehicle_count']==count
    assert a['density_percent']==percent
    root=ET.parse(tmp_path/'a/demand.rou.xml').getroot()
    vehicles=root.findall('vehicle')
    assert len(vehicles)==count+1
    assert len({v.get('id') for v in vehicles})==count+1
    assert len([v for v in vehicles if v.get('id')=='ambulance-0'])==1
    assert [float(v.get('depart')) for v in vehicles]==sorted(float(v.get('depart')) for v in vehicles)


def test_api_rejects_invalid_controls_and_foreign_origins(tmp_path):
    manager=SessionManager(tmp_path/'live')
    manager.map_data={'roads':[],'signals':[]}
    with TestClient(create_app(manager)) as client:
        for payload in ({'density':'extreme'},{'density_percent':-1},{'density_percent':201},{'density_percent':12.5},{'seed':-1},{'dispatch_s':0},{'observation_delay_s':7},{'controller':'fixed_time'}):
            assert client.post('/api/sessions',json=payload).status_code==422
        assert client.post('/api/sessions',json={},headers={'Origin':'https://other-site.example'}).status_code==403
        assert client.get('/api/sessions/not-a-session').status_code==404
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/sessions/not-a-session/stream'):
                pass


def test_manager_refuses_second_active_pair(tmp_path):
    class Process:
        def poll(self):return None
    class Session:
        processes={'baseline':Process()}
    manager=SessionManager(tmp_path)
    manager.sessions={'owned':Session()}
    with pytest.raises(RuntimeError,match='already running'):
        manager.create(DemoSettings())


def test_configured_hosted_origin_has_cors_and_foreign_origin_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv('ZELVO_ALLOWED_ORIGINS','https://zelvo.example')
    manager=SessionManager(tmp_path/'live')
    manager.map_data={'roads':[],'signals':[]}
    with TestClient(create_app(manager)) as client:
        response=client.options('/api/sessions',headers={
            'Origin':'https://zelvo.example','Access-Control-Request-Method':'POST',
            'Access-Control-Request-Headers':'content-type'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']=='https://zelvo.example'
        response=client.get('/api/network',headers={'Origin':'https://zelvo.example'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']=='https://zelvo.example'
        assert client.get('/api/network',headers={'Origin':'https://other.example'}).status_code==403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/sessions/unknown/stream',headers={'Origin':'https://other.example'}):
                pass


def test_render_trusts_deployment_origin_not_request_hostname(monkeypatch):
    from urllib.parse import urlparse
    monkeypatch.setenv('RENDER_EXTERNAL_URL','https://zelvo-live.onrender.com')
    target=urlparse('https://untrusted.example/api/sessions')
    assert origin_allowed('https://zelvo-live.onrender.com',target)
    assert not origin_allowed('https://untrusted.example',target)


@pytest.mark.parametrize('interval', [0, float('inf'), float('nan'), 10])
def test_telemetry_rejects_invalid_sampling_interval(interval):
    with pytest.raises(ValueError,match='Telemetry interval'):
        LiveTelemetry(io.StringIO(),[],60,interval_s=interval)


@pytest.mark.integration
def test_position_telemetry_does_not_change_journeys_or_phase_audits(tmp_path):
    source=Path('scenarios/smoke/smoke.json')
    plain=run_episode(source,tmp_path/'plain',controller='actuated',horizon=65)
    stream=io.StringIO()
    telemetry=LiveTelemetry(stream,[],0)
    observed=run_episode(source,tmp_path/'observed',controller='actuated',horizon=65,telemetry=telemetry)
    telemetry.finalize(observed)
    assert plain.failure is observed.failure is None
    assert observed.journeys==plain.journeys
    assert observed.metrics['approaches']==plain.metrics['approaches']
    assert observed.metrics['safety_audit_errors']==0
    frames=[json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(frames)>50
    assert all(b['time_s']>a['time_s'] for a,b in zip(frames[:-2],frames[1:-1]))
    assert frames[-1]['time_s']==frames[-2]['time_s']
    assert frames[-1]['ambulance']['arrived']
    assert frames[-1]['ambulance']['travel_s']==pytest.approx(observed.journeys[0].journey_time_s)
    assert all(len(v)==6 for f in frames for v in f['vehicles'])

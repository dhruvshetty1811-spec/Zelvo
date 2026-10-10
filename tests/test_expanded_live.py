import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from zelvo.api import create_app, origin_allowed
from starlette.datastructures import URL
from zelvo.config import load_scenario
from zelvo.live import DemoSettings, EXPANDED, SessionManager, geometry, prepare_inputs


@pytest.mark.parametrize('density,count',[('light',300),('moderate',600),('heavy',1200)])
def test_expanded_demand_is_paired_and_preserves_route(tmp_path,density,count):
    settings=DemoSettings(corridor='expanded',density=density,seed=43)
    a=prepare_inputs(settings,tmp_path/'a')
    b=prepare_inputs(settings,tmp_path/'b')
    assert a['demand_sha256']==b['demand_sha256']
    assert a['ordinary_vehicle_count']==count
    actual=load_scenario(tmp_path/'a/scenario.json')
    original=load_scenario(EXPANDED)
    assert actual.network_file==original.network_file
    assert actual.horizon_s==1500
    route=lambda path:ET.parse(path).find("vehicle[@id='ambulance-0']/route").get('edges')
    assert route(actual.route_files[0])==route(original.route_files[0])


def test_corridor_selection_controls_geometry_and_rejects_unknown(tmp_path):
    manager=SessionManager(tmp_path)
    manager.map_data={'route_length_m':913.35,'signals':[]}
    manager.expanded_map_data=geometry(EXPANDED)
    with TestClient(create_app(manager)) as client:
        expanded=client.get('/api/network?corridor=expanded').json()
        assert expanded['route_length_m']>6000
        assert len(expanded['signals'])==13
        assert client.get('/api/network').json()['route_length_m']==913.35
        assert client.get('/api/network?corridor=unknown').status_code==422
        assert client.post('/api/sessions',json={'corridor':'unknown'}).status_code==422


def test_custom_local_preview_origin_cannot_whitelist_a_foreign_host():
    assert origin_allowed('http://127.0.0.1:8037',URL('http://127.0.0.1:8037/api/sessions'))
    assert origin_allowed('http://localhost:8037',URL('ws://localhost:8037/api/sessions/id/stream'))
    assert not origin_allowed('http://evil.example:8037',URL('http://evil.example:8037/api/sessions'))
    assert not origin_allowed('http://127.0.0.1:9999',URL('http://127.0.0.1:8037/api/sessions'))


@pytest.mark.parametrize('density,count',[('light',280),('moderate',560),('heavy',1120)])
def test_curated_inputs_and_destination_are_explicit(tmp_path,density,count):
    from zelvo.live import CURATED
    receipt=prepare_inputs(DemoSettings(corridor='curated',density=density),tmp_path/'curated')
    assert receipt['ordinary_vehicle_count']==count
    assert receipt['evaluation_campaign'] is False
    original=load_scenario(CURATED)
    actual=load_scenario(tmp_path/'curated/scenario.json')
    assert actual.network_file==original.network_file
    assert actual.horizon_s==1500
    data=geometry(CURATED)
    assert data['route_length_m']==2442.08
    assert len(data['signals'])==10
    assert data['ordinary_vehicle_count']==560
    assert data['destination_label']=='Demo hospital'
    assert 'simulated hospital' in data['scenario_note']
    with TestClient(create_app(SessionManager(tmp_path/'sessions'))) as client:
        assert client.get('/api/network?corridor=curated').json()==data

from types import SimpleNamespace
from zelvo.planning import route_with_hysteresis


def test_live_routing_requires_material_gain_and_changes_only_remaining_route():
    calls=[]
    vehicle=SimpleNamespace(getRoute=lambda vid:('done','a','b','c'),getRouteIndex=lambda vid:1,
        getRoadID=lambda vid:'a',getTypeID=lambda vid:'ambulance',
        setRoute=lambda vid,edges:calls.append((vid,edges)))
    stage=SimpleNamespace(edges=('a','alternate','c'),travelTime=130)
    c=SimpleNamespace(vehicle=vehicle,edge=SimpleNamespace(getTraveltime=lambda edge:50),
                      simulation=SimpleNamespace(findRoute=lambda *a,**kw:stage))
    assert not route_with_hysteresis(c,'ev',minimum_gain_s=30)
    stage.travelTime=90
    assert route_with_hysteresis(c,'ev',minimum_gain_s=30)
    assert calls==[('ev',('a','alternate','c'))]
    vehicle.getRoadID=lambda vid:':junction_internal'
    assert not route_with_hysteresis(c,'ev')

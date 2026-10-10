from zelvo.recording import Recorder
from zelvo.contracts import ExpectedJourney


def test_arrival_is_reconciled_to_tripinfo_not_next_step_notification(tmp_path):
    recorder=Recorder((ExpectedJourney(vehicle_id='ev',scheduled_departure_s=10),),150,lambda *a,**kw:None)
    recorder.departures['ev']=10
    recorder.arrivals['ev']=32.5
    tripinfo=tmp_path/'tripinfo.xml'
    tripinfo.write_text('<tripinfos><tripinfo id="ev" depart="10" arrival="32.4"/></tripinfos>')
    metrics=recorder.metrics(str(tripinfo),40)
    assert recorder.journeys()[0].arrival_s==32.4
    assert recorder.journeys()[0].journey_time_s==22.4
    assert metrics['pedestrian']['maximum_observed_continuous_wait_s'] is None


def test_unfinished_tripinfo_does_not_invent_arrival(tmp_path):
    recorder=Recorder((ExpectedJourney(vehicle_id='ev',scheduled_departure_s=10),),150,lambda *a,**kw:None)
    tripinfo=tmp_path/'tripinfo.xml'
    tripinfo.write_text('<tripinfos><tripinfo id="ev" depart="12" arrival="-1"/></tripinfos>')
    recorder.metrics(str(tripinfo),40)
    journey=recorder.journeys()[0]
    assert journey.actual_departure_s==12
    assert journey.journey_time_s is None
    assert not journey.completed


def test_route_change_archives_visit_before_same_movement_is_revisited():
    recorder=Recorder((ExpectedJourney(vehicle_id='ev',scheduled_departure_s=0),),150,lambda *a,**kw:None)
    recorder.approaches[('ev','tls',0)]={'crossed_s':5}
    recorder.route_changed('ev')
    assert ('ev','tls',0) not in recorder.approaches
    assert recorder.archived_approaches[0]['crossed_s']==5
    assert not recorder.archived_approaches[0]['cancelled_by_reroute']


def test_red_stop_counts_nearest_red_only_and_excludes_moving_and_green():
    from types import SimpleNamespace
    import traci.constants as tc
    recorder=Recorder((ExpectedJourney(vehicle_id='ev',scheduled_departure_s=0),),150,lambda *a,**kw:None)
    signals=[('near',0,20,'r'),('far',0,100,'r')]
    connection=SimpleNamespace(
        simulation=SimpleNamespace(getDepartedIDList=lambda:[],getArrivedIDList=lambda:[]),
        vehicle=SimpleNamespace(getNextTLS=lambda vid:signals),
        trafficlight=SimpleNamespace(getControlledLinks=lambda tls:[(('in','out',':via'),)]),
        lane=SimpleNamespace(getEdgeID=lambda lane:lane),
        person=SimpleNamespace(getIDList=lambda:[]))
    snapshot={tc.VAR_SPEED:0,tc.VAR_ROAD_ID:'in'}
    recorder.update(connection,1,.1,{'ev':snapshot})
    assert recorder.approaches[('ev','near',0)]['stopped_on_red_s']==.1
    assert recorder.approaches[('ev','far',0)]['stopped_on_red_s']==0
    snapshot[tc.VAR_SPEED]=2
    recorder.update(connection,1.1,.1,{'ev':snapshot})
    signals[0]=('near',0,20,'G')
    snapshot[tc.VAR_SPEED]=0
    recorder.update(connection,1.2,.1,{'ev':snapshot})
    assert recorder.approaches[('ev','near',0)]['stopped_on_red_s']==.1

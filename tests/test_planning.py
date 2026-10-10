from dataclasses import replace
from zelvo.planning import Observation, Planner, analytical_eta, lane_queue


def observation(tls='upstream',**kw):
    values=dict(time=10,vehicle='ambulance',tls=tls,link=0,incoming='in',outgoing='out',
                distance_m=30,speed_mps=0,queue_ahead=3,downstream_queue=0,queue_extent_m=25,
                entry_space_m=100,lane_length_m=100,green=0)
    return Observation(**(values|kw))


def test_downstream_receiving_block_propagates_upstream():
    events=[]
    planner=Planner('zelvo_analytical',lambda kind,**d:events.append((kind,d)))
    demands=planner.plan(10,[observation(),observation('downstream',entry_space_m=0)])
    assert demands and not any(d.permitted for d in demands)
    assert [d['tls'] for kind,d in events if kind=='corridor_blocked']==['downstream','upstream']
    # Once the sink has actually drained, downstream and upstream may request service.
    assert len(planner.plan(12,[observation(time=12),observation('downstream',time=12)]))==2


def test_stopped_eta_finite_and_stale_data_cannot_request():
    o=observation()
    assert 0<analytical_eta(o)<120
    planner=Planner('zelvo_analytical',lambda *a,**kw:None)
    assert planner.plan(20,[o])==[]


def test_ai_queue_forecast_changes_permission_without_overriding_safety():
    class Predictor:
        def predict(self,o):return 5,20
    o=observation()
    analytical=Planner('zelvo_analytical',lambda *a,**k:None)
    ai=Planner('zelvo_ai',lambda *a,**k:None,Predictor())
    assert analytical.plan(10,[o])
    assert not any(d.permitted for d in ai.plan(10,[o]))


def test_local_baseline_only_nearest_junction():
    demands=Planner('local_preemption',lambda *a,**kw:None).plan(10,[observation(),observation('far')])
    assert [d.tls for d in demands]==['upstream']


def test_preparation_accounts_for_intervening_green_and_clearance_phases():
    from types import SimpleNamespace
    from zelvo.planning import phase_preparation_time
    states=[(13,'Grr'),(3,'yrr'),(2,'rrr'),(5,'rGr'),(3,'ryr'),(2,'rrr'),(10,'rrG')]
    logic=SimpleNamespace(phases=[SimpleNamespace(state=s,duration=t,minDur=t,next=()) for t,s in states])
    assert phase_preparation_time(logic,0,3,2)==28
    assert phase_preparation_time(logic,6,0,2)==0
    o=observation(distance_m=250,speed_mps=10,queue_ahead=3,signal_lead_s=35)
    p=Planner('zelvo_analytical',lambda *a,**kw:None)
    assert p.plan(10,[o])
    assert not p.plan(10,[replace(o,signal_lead_s=12)])


def test_creeping_queue_and_receiving_entry_space_are_distinct():
    from types import SimpleNamespace
    speeds={'creeping':1.2,'moving':5}
    positions={'creeping':90,'moving':8}
    lengths={'creeping':4,'moving':5}
    connection=SimpleNamespace(
        lane=SimpleNamespace(getLength=lambda lane:100,
            getLastStepVehicleIDs=lambda lane:('creeping','moving')),
        vehicle=SimpleNamespace(getSpeed=speeds.get,getLanePosition=positions.get,
            getLength=lengths.get))
    count,extent,entry,length=lane_queue(connection,'receiving',ahead_position=50)
    assert count==1  # Slow movement still forms a queue even with no fully halted car.
    assert extent==14
    assert entry==3  # Large free space elsewhere cannot receive another vehicle at the entry.
    assert length==100
    pending=Planner('zelvo_analytical',lambda *a,**kw:None).plan(10,
        [observation(entry_space_m=entry,queue_ahead=count,queue_extent_m=extent)])
    assert pending and not any(d.permitted for d in pending)


def test_preparation_respects_unshortenable_pedestrian_phase():
    from types import SimpleNamespace
    from zelvo.planning import phase_preparation_time
    phases=[SimpleNamespace(state=s,duration=t,minDur=5,maxDur=maximum,next=())
            for s,t,maximum in [('rGG',30,50),('ryr',3,3),('rrr',2,2),('Grr',30,50)]]
    logic=SimpleNamespace(phases=phases)
    assert phase_preparation_time(logic,0,10,0,{2})==45
    assert phase_preparation_time(logic,0,10,0)==5
    # Earlier preparation changes urgency, never permission to fill a blocked exit.
    planner=Planner('zelvo_analytical',lambda *a,**k:None)
    o=observation(distance_m=400,speed_mps=10,queue_ahead=0,signal_lead_s=47)
    assert any(d.permitted for d in planner.plan(10,[o]))
    assert not any(d.permitted for d in planner.plan(10,[replace(o,entry_space_m=0)]))

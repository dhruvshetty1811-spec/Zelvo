import pytest
import traci
from zelvo.control import Supervisor, Demand


def logic(states):
    return traci.trafficlight.Logic('test',0,0,[traci.trafficlight.Phase(t,s) for t,s in states])


def test_invalid_phase_sequences_rejected():
    with pytest.raises(ValueError,match='directly'):
        Supervisor.validate(logic([(10,'Gr'),(10,'rG')]))
    with pytest.raises(ValueError,match='Yellow'):
        Supervisor.validate(logic([(10,'Gr'),(1,'yr'),(2,'rr'),(10,'rG'),(3,'ry'),(2,'rr')]))
    with pytest.raises(ValueError,match='All-red'):
        Supervisor.validate(logic([(10,'Gr'),(3,'yr'),(1,'rr'),(10,'rG'),(3,'ry'),(2,'rr')]))


def test_program_with_clearances_is_valid():
    Supervisor.validate(logic([(10,'Gr'),(3,'yr'),(2,'rr'),(10,'rG'),(3,'ry'),(2,'rr')]))


class FakeSignals:
    def __init__(self):
        self.logic=logic([(10,'Gr'),(3,'yr'),(2,'rr'),(10,'rG'),(3,'ry'),(2,'rr')])
        self.phase=0
        self.spent=9
        self.switch=9.5
        self.people=0
        self.commands=[]
    def getIDList(self):return ['tls']
    def getProgram(self,tls):return 'test'
    def getAllProgramLogics(self,tls):return [self.logic]
    def subscribe(self,*a):pass
    def getSubscriptionResults(self,tls):
        import traci.constants as tc
        return {tc.TL_CURRENT_PHASE:self.phase,tc.TL_RED_YELLOW_GREEN_STATE:self.logic.phases[self.phase].state,
                tc.TL_NEXT_SWITCH:self.switch}
    def getControlledLinks(self,tls):return [(('in','out','via'),),(('in2','out2','via2'),)]
    def getServedPersonCount(self,*a):return self.people
    def getSpentDuration(self,tls):return self.spent
    def setPhaseDuration(self,tls,duration):self.commands.append((tls,duration))


class FakeConnection:
    def __init__(self):
        self.trafficlight=FakeSignals()
        self.lane=type('Lane',(),{'getAllowed':lambda self,lane:('passenger',),
                                'subscribe':lambda *a:None,'getAllSubscriptionResults':lambda self:{},
                                'getLastStepVehicleIDs':lambda self,lane:(),
                                'getLength':lambda self,lane:100})()


def test_shared_ambulances_keep_hold_after_first_crosses():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None)
    first=Demand('first','tls',0,10,20,outgoing='out')
    second=Demand('second','tls',0,12,20,outgoing='out')
    supervisor.tick(9,[first,second])
    assert supervisor.mem['tls'].active_vehicles=={'first','second'}
    supervisor.tick(9.1,[second])
    assert supervisor.mem['tls'].active_vehicles=={'second'}
    assert len(c.trafficlight.commands)==2
    supervisor.tick(9.2,[])
    assert supervisor.mem['tls'].active_vehicles==set()
    assert supervisor.mem['tls'].recovery_until>9.2


def test_conflict_arbitration_respects_minimum_and_clearances():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None)
    demand=Demand('cross','tls',1,10,30,outgoing='out')
    c.trafficlight.switch=20
    c.trafficlight.spent=4
    supervisor.tick(4,[demand])
    assert not c.trafficlight.commands
    c.trafficlight.spent=10
    supervisor.tick(10,[demand])
    assert c.trafficlight.commands==[('tls',.1)]
    c.trafficlight.phase=1
    c.trafficlight.switch=13.1
    supervisor.tick(10.1,[demand])
    assert len(c.trafficlight.commands)==1


def test_pedestrian_service_blocks_priority_timing_change():
    c=FakeConnection()
    c.trafficlight.people=1
    supervisor=Supervisor(c,lambda *a,**kw:None)
    supervisor.tick(9,[Demand('first','tls',0,10,20,outgoing='out')])
    assert not c.trafficlight.commands


def test_priority_budget_returns_to_ordinary_service():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None,max_priority_s=3,recovery_s=5)
    demand=Demand('first','tls',0,10,30,outgoing='out')
    supervisor.tick(9,[demand])
    supervisor.tick(12.1,[demand])
    assert supervisor.mem['tls'].recovery_until==17.1
    assert supervisor.mem['tls'].first_priority is None


def test_disappeared_changed_route_and_crossed_requests_are_invalidated():
    from zelvo.control import retain_demands
    demands=[Demand('gone','tls',0,10,20),Demand('changed','tls',0,10,20,0),
             Demand('crossed','tls',0,10,20),Demand('following','tls',0,10,20)]
    retained=retain_demands(demands,{'changed','crossed','following'},{'changed':1},{('crossed','tls',0)})
    assert [d.vehicle for d in retained]==['following']


def test_missing_or_changed_receiving_capacity_cannot_extend_priority():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None)
    supervisor.tick(9,[Demand('first','tls',0,10,20)])
    assert not c.trafficlight.commands
    c.lane.getLength=lambda lane:5
    supervisor.tick(9.1,[Demand('first','tls',0,10,20,outgoing='out')])
    assert not c.trafficlight.commands


def test_pending_capacity_block_preserves_follower_without_burning_unstarted_budget():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None)
    pending=Demand('follower','tls',0,10,20,outgoing='out',permitted=False)
    supervisor.tick(9,[pending])
    assert supervisor.mem['tls'].first_priority is None
    supervisor.tick(9.1,[Demand('follower','tls',0,10,20,outgoing='out')])
    assert supervisor.mem['tls'].active_vehicles=={'follower'}
    supervisor.tick(9.2,[pending])
    assert supervisor.mem['tls'].active_vehicles=={'follower'}


def test_unmodified_baseline_audits_without_holding_occupied_all_red():
    import traci.constants as tc
    c=FakeConnection()
    c.trafficlight.phase=2
    c.trafficlight.switch=10.1
    supervisor=Supervisor(c,lambda *a,**kw:None,occupancy_guard=False)
    supervisor.internal_lanes['tls']={':occupied_0'}
    c.lane.getAllSubscriptionResults=lambda:{':occupied_0':{tc.LAST_STEP_VEHICLE_NUMBER:1}}
    supervisor.tick(10,[])
    assert c.trafficlight.commands==[]


def test_preparation_does_not_consume_green_service_budget():
    c=FakeConnection()
    supervisor=Supervisor(c,lambda *a,**kw:None,max_priority_s=3,max_preparation_s=20)
    demand=Demand('cross','tls',1,15,40,outgoing='out')
    supervisor.tick(1,[demand])
    supervisor.tick(5,[demand])
    assert supervisor.mem['tls'].first_priority==1
    assert supervisor.mem['tls'].service_started is None
    c.trafficlight.phase=3
    c.trafficlight.switch=15
    supervisor.tick(10,[demand])
    assert supervisor.mem['tls'].service_started==10
    supervisor.tick(13.1,[demand])
    assert supervisor.mem['tls'].first_priority is None

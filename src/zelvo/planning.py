"""Route-aware observations and a bounded downstream-first planner."""
from dataclasses import dataclass
from zelvo.control import Demand, classify_links

FEATURES = ('distance_m','speed_mps','queue_ahead','downstream_queue','queue_extent_m','entry_space_m',
            'lane_length_m','green','action_hold','arrival_rate','discharge_rate')


@dataclass
class Observation:
    time: float
    vehicle: str
    tls: str
    link: int
    incoming: str
    outgoing: str
    distance_m: float
    speed_mps: float
    queue_ahead: int
    downstream_queue: int
    queue_extent_m: float
    entry_space_m: float
    lane_length_m: float
    green: float
    action_hold: float = 0
    arrival_rate: float = 0
    discharge_rate: float = 0
    signal_lead_s: float = 12

    def features(self):
        return [getattr(self,name) for name in FEATURES]


def lane_queue(connection,lane: str, *, ahead_position=None):
    length = connection.lane.getLength(lane)
    vehicles = []
    for vid in connection.lane.getLastStepVehicleIDs(lane):
        speed = connection.vehicle.getSpeed(vid)
        position = connection.vehicle.getLanePosition(vid)
        if speed < 2 and (ahead_position is None or position > ahead_position):
            vehicles.append((position,connection.vehicle.getLength(vid)))
    extent = max((length-pos+vlength for pos,vlength in vehicles),default=0)
    # Receiving space at ENTRY, not a misleading total count or free area elsewhere.
    entry = min((connection.vehicle.getLanePosition(vid)-connection.vehicle.getLength(vid)
                 for vid in connection.lane.getLastStepVehicleIDs(lane)),default=length)
    return len(vehicles), min(length,extent), max(0,entry),length


class Observer:
    def __init__(self,connection):
        self.c = connection
        self.speed = {}
        self.lane_history = {}
        self.programs = {}
        self.pedestrian_links = {}

    def observe(self,vehicle: str, now: float, horizon=6) -> list[Observation]:
        c = self.c
        speed = c.vehicle.getSpeed(vehicle)
        self.speed[vehicle] = .3*speed+.7*self.speed.get(vehicle,speed)
        route = c.vehicle.getRoute(vehicle)
        route_index = c.vehicle.getRouteIndex(vehicle)
        observations = []
        for tls,link,distance,state in c.vehicle.getNextTLS(vehicle)[:horizon]:
            connections = c.trafficlight.getControlledLinks(tls)[link]
            pairs = [(route[i],route[i+1]) for i in range(max(0,route_index),len(route)-1)]
            selected = next(((a,b) for a,b,_ in connections
                             if (c.lane.getEdgeID(a),c.lane.getEdgeID(b)) in pairs),None)
            if selected is None:
                continue
            incoming,outgoing = selected
            position = c.vehicle.getLanePosition(vehicle) if c.vehicle.getLaneID(vehicle)==incoming else None
            queue,extent,_,_ = lane_queue(c,incoming,ahead_position=position)
            downstream,_,entry,length = lane_queue(c,outgoing)
            ids = set(c.lane.getLastStepVehicleIDs(incoming))
            previous = self.lane_history.get(incoming)
            arrival_rate = discharge_rate = 0
            if previous and now==previous[0]:
                arrival_rate,discharge_rate=previous[2:]
            elif previous and now>previous[0]:
                dt = now-previous[0]
                arrival_rate = len(ids-previous[1])/dt
                discharge_rate = len(previous[1]-ids)/dt
            self.lane_history[incoming] = (now,ids,arrival_rate,discharge_rate)
            if tls not in self.programs:
                self.programs[tls]=next(p for p in c.trafficlight.getAllProgramLogics(tls)
                    if p.programID==c.trafficlight.getProgram(tls))
                self.pedestrian_links[tls]=classify_links(c,tls)[1]
            lead=phase_preparation_time(self.programs[tls],c.trafficlight.getPhase(tls),
                c.trafficlight.getSpentDuration(tls),link,self.pedestrian_links[tls])
            observations.append(Observation(now,vehicle,tls,link,incoming,outgoing,max(0,distance),
                                           self.speed[vehicle],queue,downstream,extent,entry,length,
                                           float(state in 'Gg'),arrival_rate=arrival_rate,
                                           discharge_rate=discharge_rate,signal_lead_s=max(12,lead+2)))
        return observations


def analytical_eta(o: Observation) -> float:
    # Bounded speed estimate prevents infinite ETA when a vehicle is stopped.
    running = o.distance_m/max(4,min(16.67,o.speed_mps))
    return running + 2+o.queue_ahead*2.0


def queue_clearance(o: Observation) -> float:
    return 2+o.queue_ahead*max(1.6,min(3,1/max(.01,o.discharge_rate)))


def phase_preparation_time(logic, phase, spent, link, pedestrian_links=()):
    """Preparation estimate including intervening service and clearance.

    This estimates preparation, not permission to skip a phase or guarantee that
    a branching actuated program will take the shortest path. Pedestrian-serving
    phases use their possible maximum because the supervisor cannot shorten them.
    """
    import heapq
    pending=[(0.0,phase)]
    visited=set()
    while pending:
        elapsed,index=heapq.heappop(pending)
        if index in visited:continue
        visited.add(index)
        p=logic.phases[index]
        if p.state[link]=='G':return elapsed
        if 'y' in p.state.lower() or not any(s in 'Gg' for s in p.state):
            duration=p.duration
        elif any(p.state[i] in 'Gg' for i in pedestrian_links):
            # The supervisor never shortens pedestrian service. Use its
            # possible actuated maximum, rather than an unattainable 8s cut.
            duration=max(p.duration,getattr(p,'maxDur',p.duration))
        else:
            duration=max(8,p.minDur if p.minDur>=0 else 0)
        if index==phase:duration=max(0,duration-spent)
        for successor in p.next or ((index+1)%len(logic.phases),):
            heapq.heappush(pending,(elapsed+duration,successor))
    return 90.0


class Planner:
    def __init__(self,mode,emit,predictor=None,stale_after=3):
        self.mode,self.emit,self.predictor = mode,emit,predictor
        self.stale_after = stale_after
        self.predictions = []
        self.route_versions = {}

    def plan(self,now: float, observations: list[Observation]) -> list[Demand]:
        if self.mode in ('fixed_time','actuated'):
            return []
        demands = []
        by_vehicle = {}
        for o in observations:
            by_vehicle.setdefault(o.vehicle,[]).append(o)
        for vehicle,corridor in sorted(by_vehicle.items()):
            if self.mode == 'local_preemption':
                corridor = corridor[:1]
            blocked = False
            # Walk from downstream sink to ambulance. Acknowledgement cannot clear blocked.
            for o in reversed(corridor):
                if now-o.time>self.stale_after:
                    self.emit('planner_fallback',vehicle=vehicle,tls=o.tls,reason='stale_observation')
                    blocked = True
                    continue
                eta = analytical_eta(o)
                arrival_window = [max(0,.75*eta),1.35*eta+5]
                clearance = queue_clearance(o)
                predicted_queue = None
                o.action_hold = 1
                if self.predictor:
                    prediction = self.predictor.predict(o)
                    if prediction is None:
                        self.emit('planner_fallback',vehicle=vehicle,tls=o.tls,reason='model_out_of_support')
                    else:
                        eta,predicted_queue = prediction
                        arrival_window = getattr(self.predictor,'last_interval',None) or [eta,eta]
                self.predictions.append({'time':now,'vehicle':vehicle,'tls':o.tls,'link':o.link,
                                         'eta':eta,'analytical_eta':analytical_eta(o),
                                         'arrival_window_s':arrival_window,
                                         'queue_prediction':predicted_queue,'features':o.features(),
                                         'signal_lead_s':o.signal_lead_s,
                                         'incoming':o.incoming,'outgoing':o.outgoing})
                entry_ok = o.entry_space_m>=10 and (predicted_queue is None or predicted_queue*7.5<o.lane_length_m-10)
                if self.mode != 'local_preemption' and (blocked or not entry_ok):
                    self.emit('corridor_blocked',vehicle=vehicle,tls=o.tls,
                              entry_space_m=o.entry_space_m,downstream_blocked=blocked)
                    blocked = True
                    demands.append(Demand(vehicle,o.tls,o.link,now+eta,now+3,
                        self.route_versions.get(vehicle,0),outgoing=o.outgoing,permitted=False))
                    continue
                # Protect receiving storage even for the local baseline.
                if not entry_ok:
                    demands.append(Demand(vehicle,o.tls,o.link,now+eta,now+3,
                        self.route_versions.get(vehicle,0),outgoing=o.outgoing,permitted=False))
                    continue
                trigger = self.mode=='local_preemption' and o.distance_m<250 or arrival_window[0]<=clearance+o.signal_lead_s
                if trigger:
                    demands.append(Demand(vehicle,o.tls,o.link,now+eta,now+3,
                                          self.route_versions.get(vehicle,0),outgoing=o.outgoing))
                    self.emit('priority_requested',vehicle=vehicle,tls=o.tls,link=o.link,
                              eta_s=eta,clearance_s=clearance,signal_preparation_s=o.signal_lead_s,
                              receiving_space_m=o.entry_space_m)
        return demands


def route_with_hysteresis(connection,vehicle, *, minimum_gain_s=30):
    """Optional travel-time rerouting, separate from the fixed-route experiment."""
    current = connection.vehicle.getRoute(vehicle)
    index = connection.vehicle.getRouteIndex(vehicle)
    if index<0 or not current or connection.vehicle.getRoadID(vehicle).startswith(':'):
        return False
    remaining = current[index:]
    stage = connection.simulation.findRoute(remaining[0],remaining[-1],
                                           vType=connection.vehicle.getTypeID(vehicle),routingMode=1)
    old_time = sum(connection.edge.getTraveltime(edge) for edge in remaining)
    if stage.edges and stage.travelTime+minimum_gain_s<old_time and tuple(stage.edges)!=tuple(remaining):
        connection.vehicle.setRoute(vehicle,stage.edges)
        return True
    return False

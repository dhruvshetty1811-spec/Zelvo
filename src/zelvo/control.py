"""Signal safety boundary: accelerate legal succession, never jump phase masks.

This supervisor preserves the imported program's clearance phases. It is not
a certification of the imported geometry, timing values, or real road safety.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Demand:
    vehicle: str
    tls: str
    link: int
    eta: float
    expires: float
    route_version: int = 0
    outgoing: str | None = None
    permitted: bool = True


def has_green(state: str) -> bool:
    return any(c in 'Gg' for c in state)


def is_clearance(state: str) -> bool:
    return 'y' in state.lower() or not has_green(state)


def retain_demands(demands,active_vehicles,route_versions,crossed):
    return [d for d in demands if d.vehicle in active_vehicles
            and d.route_version==route_versions.get(d.vehicle,0)
            and (d.vehicle,d.tls,d.link) not in crossed]


def classify_links(connection,tls):
    links=connection.trafficlight.getControlledLinks(tls)
    pedestrian={i for i,group in enumerate(links) if group and all(
        connection.lane.getAllowed(incoming)==('pedestrian',) for incoming,_,_ in group)}
    vehicle=set(range(len(links)))-pedestrian
    internal={lane for group in links for _,outgoing,via in group
              for lane in (via,outgoing) if lane and lane.startswith(':')}
    return vehicle,pedestrian,internal


@dataclass
class SignalMemory:
    first_priority: float | None = None
    service_started: float | None = None
    previous_phase: int | None = None
    previous_switch: float | None = None
    previous_time: float = 0
    previous_state: str = ''
    active_vehicles: set = field(default_factory=set)
    recovery_until: float = 0
    accelerated_phase: tuple | None = None
    reservation: Demand | None = None


class Supervisor:
    def __init__(self, connection, emit, *, max_priority_s=30, recovery_s=20, occupancy_guard=True, max_preparation_s=90):
        import traci.constants as tc
        self.tc = tc
        self.c = connection
        self.emit = emit
        self.max_priority_s = max_priority_s
        self.recovery_s = recovery_s
        self.occupancy_guard = occupancy_guard
        self.max_preparation_s = max_preparation_s
        self.mem = {}
        self.logics = {}
        self.pedestrian_links = {}
        self.internal_lanes = {}
        self.audit_errors = 0
        for tls in self.c.trafficlight.getIDList():
            logic = next(p for p in self.c.trafficlight.getAllProgramLogics(tls)
                         if p.programID == self.c.trafficlight.getProgram(tls))
            vehicles,pedestrians,internal=classify_links(self.c,tls)
            self.validate(logic,vehicles)
            self.pedestrian_links[tls]=pedestrians
            self.internal_lanes[tls]=internal
            self.logics[tls] = logic
            self.mem[tls] = SignalMemory()
            self.c.trafficlight.subscribe(tls,(tc.TL_CURRENT_PHASE,tc.TL_RED_YELLOW_GREEN_STATE,tc.TL_NEXT_SWITCH))
        self.watched_lanes=set()

    def monitor_corridor(self,tls_ids):
        for tls in tls_ids:
            for lane in self.internal_lanes.get(tls,set())-self.watched_lanes:
                self.c.lane.subscribe(lane,(self.tc.LAST_STEP_VEHICLE_NUMBER,))
                self.watched_lanes.add(lane)

    def receiving_clear(self,demand):
        if demand.outgoing is None:return False
        lane=demand.outgoing
        ids=self.c.lane.getLastStepVehicleIDs(lane)
        entry=min((self.c.vehicle.getLanePosition(v)-self.c.vehicle.getLength(v) for v in ids),
                  default=self.c.lane.getLength(lane))
        return entry>=10

    @staticmethod
    def validate(logic,vehicle_indices=None):
        phases = logic.phases
        if not phases or len({len(p.state) for p in phases}) != 1:
            raise ValueError('Signal phase lengths inconsistent')
        # For every green ending on any program branch, require an intervening yellow.
        for index,p in enumerate(phases):
            successors = p.next or ((index+1)%len(phases),)
            for successor in successors:
                target = phases[successor]
                if any(a in 'Gg' and b in 'rR' for j,(a,b) in enumerate(zip(p.state,target.state))
                       if vehicle_indices is None or j in vehicle_indices):
                    raise ValueError('Program drops green directly to red without yellow')
                if 'y' in p.state.lower() and p.duration < 3:
                    raise ValueError('Yellow below configured 3-second minimum')
                if set(p.state.lower())=={'r'} and p.duration<2:
                    raise ValueError('All-red below configured 2-second minimum')

    def tick(self, now: float, demands: list[Demand],pedestrian_lanes=()):
        lane_snapshots=self.c.lane.getAllSubscriptionResults()
        grouped = {}
        for demand in demands:
            if now <= demand.expires and demand.tls in self.mem:
                grouped.setdefault(demand.tls,[]).append(demand)
        for tls, memory in self.mem.items():
            snapshot = self.c.trafficlight.getSubscriptionResults(tls)
            phase = snapshot[self.tc.TL_CURRENT_PHASE]
            state = snapshot[self.tc.TL_RED_YELLOW_GREEN_STATE]
            logic = self.logics[tls]
            current = logic.phases[phase]
            if memory.previous_phase is not None and phase != memory.previous_phase:
                previous = logic.phases[memory.previous_phase]
                successors = previous.next or ((memory.previous_phase+1)%len(logic.phases),)
                if phase not in successors:
                    self.audit_errors += 1
                    self.emit('safety_violation',tls=tls,reason='unexpected phase successor')
                if is_clearance(memory.previous_state) and memory.previous_switch is not None:
                    # Switch scheduled before this step; signal states sampled every simulation step.
                    if now+0.11 < memory.previous_switch:
                        self.audit_errors += 1
                        self.emit('safety_violation',tls=tls,reason='clearance ended before scheduled switch')
                self.emit('phase_transition',tls=tls,old_phase=memory.previous_phase,new_phase=phase,state=state)
                memory.accelerated_phase = None
            memory.previous_phase = phase
            memory.previous_state = state
            memory.previous_switch = snapshot[self.tc.TL_NEXT_SWITCH]
            if self.occupancy_guard and set(state.lower())=={'r'} and snapshot[self.tc.TL_NEXT_SWITCH]-now<.2:
                occupied=any(lane_snapshots.get(lane,{}).get(self.tc.LAST_STEP_VEHICLE_NUMBER,0)>0
                             or lane in pedestrian_lanes for lane in self.internal_lanes[tls])
                reservation=memory.reservation
                successors=current.next or ((phase+1)%len(logic.phases),)
                will_serve=reservation is not None and any(logic.phases[i].state[reservation.link]=='G' for i in successors)
                blocked=will_serve and reservation.expires>=now and not self.receiving_clear(reservation)
                if occupied or blocked:
                    self.c.trafficlight.setPhaseDuration(tls,1)
                    self.emit('all_red_occupied_hold' if occupied else 'all_red_receiving_hold',tls=tls)
            requests = sorted(grouped.get(tls,[]),key=lambda d:(d.eta,d.vehicle,d.link))
            invalid = [d for d in requests if not 0<=d.link<len(state) or d.outgoing is None]
            for demand in invalid:
                self.emit('priority_rejected',tls=tls,vehicle=demand.vehicle,reason='invalid controlled link or missing receiving lane')
            requests = [d for d in requests if 0<=d.link<len(state) and d.outgoing is not None]
            eligible = [d for d in requests if any(p.state[d.link]=='G' for p in logic.phases)]
            if not eligible:
                if memory.active_vehicles:
                    self.emit('priority_released',tls=tls,vehicles=','.join(sorted(memory.active_vehicles)))
                    memory.recovery_until = now+self.recovery_s
                memory.active_vehicles.clear()
                memory.first_priority = None
                memory.service_started = None
                memory.reservation=None
                continue
            if now < memory.recovery_until:
                continue
            authorized=[d for d in eligible if d.permitted]
            if memory.first_priority is None and not authorized:
                continue
            if memory.first_priority is None:
                memory.first_priority = now
            if memory.service_started is None and any(state[d.link]=='G' for d in authorized):
                memory.service_started=now
            exhausted = (now-memory.service_started>=self.max_priority_s if memory.service_started is not None
                         else now-memory.first_priority>=self.max_preparation_s)
            if exhausted:
                memory.recovery_until = now+self.recovery_s
                memory.first_priority = None
                memory.service_started = None
                memory.active_vehicles.clear()
                memory.reservation=None
                self.emit('priority_budget_exhausted',tls=tls)
                continue
            if not authorized:
                # A blocked follower is still a pending owner, not a completed
                # emergency. Keep its membership without extending unsafe green.
                memory.active_vehicles.intersection_update(d.vehicle for d in eligible)
                if memory.reservation:
                    matching=next((d for d in eligible if d.link==memory.reservation.link),None)
                    if matching:memory.reservation=matching
                continue
            winner = authorized[0]
            if not self.receiving_clear(winner):
                self.emit('priority_rejected',tls=tls,vehicle=winner.vehicle,reason='receiving capacity changed')
                continue
            memory.reservation=winner
            # All requests served by this same protected phase may share the hold.
            compatible = [d for d in eligible if state[d.link]=='G']
            if len({d.link for d in eligible})>1:
                self.emit('arbitration',tls=tls,winner=winner.vehicle,requests=len(eligible))
            memory.active_vehicles = {d.vehicle for d in compatible}
            if is_clearance(state):
                continue
            # Never shorten an imported phase serving pedestrian crossings. Waiting
            # pedestrians retain ordinary cycling; occupied crossings also block holds.
            pedestrian_phase = any(state[i] in 'Gg' for i in self.pedestrian_links[tls])
            people = self.c.trafficlight.getServedPersonCount(tls,phase)
            if pedestrian_phase or people:
                continue
            spent = self.c.trafficlight.getSpentDuration(tls)
            minimum = max(8.0,current.minDur if current.minDur >= 0 else 0)
            if state[winner.link]=='G':
                remaining = snapshot[self.tc.TL_NEXT_SWITCH]-now
                if remaining < 1.5:
                    self.c.trafficlight.setPhaseDuration(tls,2)
                    self.emit('priority_hold',tls=tls,vehicle=winner.vehicle,phase=phase)
            elif spent >= minimum and memory.accelerated_phase != (phase,memory.first_priority):
                remaining = snapshot[self.tc.TL_NEXT_SWITCH]-now
                if remaining > 0.11:
                    self.c.trafficlight.setPhaseDuration(tls,0.1)
                    memory.accelerated_phase = (phase,memory.first_priority)
                    self.emit('priority_advance',tls=tls,vehicle=winner.vehicle,phase=phase)


def install_fixed_programs(connection):
    """Same geometry/phase masks and clearance durations, static timing only."""
    for tls in connection.trafficlight.getIDList():
        original = next(p for p in connection.trafficlight.getAllProgramLogics(tls)
                        if p.programID == connection.trafficlight.getProgram(tls))
        phases=[]
        for p in original.phases:
            phase=connection.trafficlight.Phase(p.duration,p.state)
            phase.next=p.next
            phases.append(phase)
        fixed = connection.trafficlight.Logic('zelvo-fixed',0,0,phases)
        vehicle_indices,_,_=classify_links(connection,tls)
        Supervisor.validate(fixed,vehicle_indices)
        connection.trafficlight.setProgramLogic(tls,fixed)
        connection.trafficlight.setProgram(tls,'zelvo-fixed')

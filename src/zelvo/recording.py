"""Common, controller-independent measurement zones and censored outcomes."""
from collections import defaultdict
import xml.etree.ElementTree as ET
from zelvo.contracts import JourneyResult


class Recorder:
    def __init__(self,expected,approach_distance,emit):
        self.expected = {j.vehicle_id:j for j in expected}
        self.approach_distance = approach_distance
        self.emit = emit
        self.departures = {}
        self.arrivals = {}
        self.stopped = defaultdict(float)
        self.stops = defaultdict(int)
        self.was_stopped = defaultdict(bool)
        self.has_moved = defaultdict(bool)
        self.approaches = {}
        self.archived_approaches=[]
        self.last_time_loss = {}
        self.last_person_wait = {}
        self.inserted = set()
        self.arrived = set()
        self.current_person_lanes = set()
        self.lane_lengths={}
        self.spillback_lane_seconds=0
        self.last_congestion_time=0
        self.maximum_slow_extent=0
        self.pedestrian_stopped_seconds=0

    def route_changed(self,vehicle):
        for key in list(self.approaches):
            if key[0]==vehicle:
                record=self.approaches.pop(key)
                record['cancelled_by_reroute']=record['crossed_s'] is None
                self.archived_approaches.append(record)

    def update(self,c,now,dt,snapshots):
        import traci.constants as tc
        for vid in c.simulation.getDepartedIDList():
            self.inserted.add(vid)
            if vid in self.expected:
                self.departures[vid] = c.vehicle.getDeparture(vid)
                self.emit('ambulance_departed',vehicle=vid,departure_s=self.departures[vid])
        for vid in c.simulation.getArrivedIDList():
            self.arrived.add(vid)
            if vid in self.expected:
                self.arrivals[vid] = now
                self.emit('ambulance_arrived',vehicle=vid)
        for vid,snapshot in snapshots.items():
            if tc.VAR_TIMELOSS in snapshot:
                self.last_time_loss[vid] = max(0,snapshot[tc.VAR_TIMELOSS])
            if vid not in self.expected:
                continue
            stopped = snapshot[tc.VAR_SPEED]<.1
            if stopped:
                self.stopped[vid] += dt
            if snapshot[tc.VAR_SPEED]>=1:
                self.has_moved[vid] = True
            if stopped and not self.was_stopped[vid] and self.has_moved[vid]:
                self.stops[vid] += 1
            self.was_stopped[vid] = stopped
            next_tls = c.vehicle.getNextTLS(vid)
            for tls,link,distance,state in next_tls:
                if distance>self.approach_distance:
                    continue
                key = (vid,tls,link)
                if key not in self.approaches:
                    links = c.trafficlight.getControlledLinks(tls)[link]
                    self.approaches[key] = {'vehicle':vid,'tls':tls,'link':link,
                        'detected_s':now,'first_green_s':None,'crossed_s':None,
                        'stopped_on_red_s':0.0,
                        'candidate_exit_edges':[c.lane.getEdgeID(outgoing) for _,outgoing,_ in links],
                        'candidate_via_edges':[c.lane.getEdgeID(via) for _,_,via in links if via]}
                    self.emit('approach_detected',vehicle=vid,tls=tls,link=link,distance_m=distance)
                record = self.approaches[key]
                if next_tls and (tls,link)==next_tls[0][:2] and stopped and state in 'rR':
                    record['stopped_on_red_s'] += dt
                if state in 'Gg' and record['first_green_s'] is None:
                    record['first_green_s'] = now
                    self.emit('approach_green',vehicle=vid,tls=tls,link=link)
            upcoming = {(tls,link) for tls,link,_,_ in next_tls}
            road = snapshot[tc.VAR_ROAD_ID]
            for (v,tls,link),record in self.approaches.items():
                if v==vid and record['crossed_s'] is None and (tls,link) not in upcoming:
                    if road in record['candidate_exit_edges']+record['candidate_via_edges']:
                        record['crossed_s'] = now
                        self.emit('stopline_crossed',vehicle=vid,tls=tls,link=link)
        self.current_person_lanes = set()
        for person in c.person.getIDList():
            self.last_person_wait[person] = max(self.last_person_wait.get(person,0),c.person.getWaitingTime(person))
            self.current_person_lanes.add(c.person.getLaneID(person))
            if c.person.getSpeed(person)<.1:self.pedestrian_stopped_seconds+=dt

    def congestion(self,c,snapshots,now):
        import traci.constants as tc
        queues=defaultdict(list)
        for data in snapshots.values():
            lane=data[tc.VAR_LANE_ID]
            if lane and not lane.startswith(':') and data[tc.VAR_SPEED]<2:
                queues[lane].append(data)
        blocked=0
        maximum=0
        slow_vehicles=0
        for lane,vehicles in queues.items():
            if lane not in self.lane_lengths:self.lane_lengths[lane]=c.lane.getLength(lane)
            length=self.lane_lengths[lane]
            extent=min(length,max(length-v[tc.VAR_LANEPOSITION]+v[tc.VAR_LENGTH] for v in vehicles))
            maximum=max(maximum,extent)
            slow_vehicles+=len(vehicles)
            if extent>=length-10 and len(vehicles)>=2:blocked+=1
        self.spillback_lane_seconds+=blocked*(now-self.last_congestion_time)
        self.last_congestion_time=now
        self.maximum_slow_extent=max(self.maximum_slow_extent,maximum)
        return {'slow_vehicles':slow_vehicles,'lanes_with_slow_vehicles':len(queues),
                'potential_spillback_lanes':blocked,'maximum_slow_vehicle_extent_m':maximum}

    def journeys(self):
        results=[]
        for vid,expected in self.expected.items():
            departure = self.departures.get(vid)
            arrival = self.arrivals.get(vid)
            results.append(JourneyResult(vehicle_id=vid,scheduled_departure_s=expected.scheduled_departure_s,
                actual_departure_s=departure,arrival_s=arrival,completed=arrival is not None,
                departure_delay_s=None if departure is None else departure-expected.scheduled_departure_s,
                journey_time_s=None if arrival is None else arrival-departure,
                scheduled_start_to_arrival_s=None if arrival is None else arrival-expected.scheduled_departure_s,
                stopped_time_s=None if departure is None else self.stopped[vid],
                stops=None if departure is None else self.stops[vid]))
        return tuple(results)

    def metrics(self,tripinfo: str,now: float):
        from zelvo.metrics import distribution
        trips = ET.parse(tripinfo).getroot().findall('tripinfo')
        for trip in trips:
            vid=trip.attrib['id']
            if vid in self.expected:
                self.departures[vid]=float(trip.attrib['depart'])
                if float(trip.attrib['arrival'])>=0:
                    self.arrivals[vid]=float(trip.attrib['arrival'])
            if float(trip.attrib['arrival'])>=0:
                self.arrived.add(vid)
        ordinary = [t for t in trips if t.attrib['id'] not in self.expected]
        approaches = []
        for record in [*self.archived_approaches,*self.approaches.values()]:
            record = dict(record)
            record['signal_response_s'] = (None if record['first_green_s'] is None else
                                          record['first_green_s']-record['detected_s'])
            record['passage_wait_s'] = (None if record['crossed_s'] is None else
                                       record['crossed_s']-record['detected_s'])
            approaches.append(record)
        return {'arrival_source':'SUMO tripinfo; approach/crossing timestamps are step observations',
            'network_congestion':{'potential_spillback_lane_seconds':self.spillback_lane_seconds,
                                  'maximum_slow_vehicle_extent_m':self.maximum_slow_extent,
                                  'definition':'1s sampling; vehicles below 2m/s; extent is not a calibrated contiguous queue'},
            'approaches':approaches,'ordinary':{
            'inserted':len([v for v in self.inserted if v not in self.expected]),
            'arrived':len([v for v in self.arrived if v not in self.expected]),
            'unfinished_inserted':len([v for v in self.inserted-self.arrived if v not in self.expected]),
            'observed_time_loss_s':sum(float(t.attrib['timeLoss']) for t in ordinary),
            'time_loss_distribution_s':distribution(float(t.attrib['timeLoss']) for t in ordinary),
            'waiting_distribution_s':distribution(float(t.attrib['waitingTime']) for t in ordinary),
            'waiting_time_s':sum(float(t.attrib['waitingTime']) for t in ordinary),
            'insertion_delay_s':sum(float(t.attrib.get('departDelay',0)) for t in ordinary),
            'throughput_vehicles_per_hour':3600*len([v for v in self.arrived if v not in self.expected])/max(.1,now)},
            'pedestrian':{'observed_people':len(self.last_person_wait),
                          'observed_stopped_person_seconds':self.pedestrian_stopped_seconds if self.last_person_wait else None,
                          'maximum_observed_continuous_wait_s':max(self.last_person_wait.values(),default=None)}}

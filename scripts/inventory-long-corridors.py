"""Geometry-only hospital routes; exclude short receiving links without changing roads."""
import argparse
from collections import defaultdict
import heapq
import json
from pathlib import Path
import sumolib

from zelvo.simulation.smoke import sha256


def distances(target, incoming, lengths):
    costs={target:lengths[target]}
    successor={}
    pending=[(lengths[target],target)]
    while pending:
        cost,edge=heapq.heappop(pending)
        if cost!=costs[edge]:continue
        for previous in incoming.get(edge,()):
            candidate=cost+lengths[previous]
            if candidate<costs.get(previous,float('inf')):
                costs[previous]=candidate
                successor[previous]=edge
                heapq.heappush(pending,(candidate,previous))
    return costs,successor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,default=Path('scenarios/bengaluru'))
    parser.add_argument('--min-receiving-m',type=float,default=30)
    parser.add_argument('--min-approach-m',type=float,default=150)
    parser.add_argument('--output',type=Path,default=Path('reports/long-corridor-inventory.json'))
    args=parser.parse_args()
    directory=args.directory
    reg=json.loads((directory/'registry.json').read_text())
    net=sumolib.net.readNet(str(directory/'district.net.xml'))
    edges={e.getID():e for e in net.getEdges() if e.allows('passenger')}
    lengths={key:e.getLength() for key,e in edges.items()}
    movements=defaultdict(list)
    for m in reg['movements']:
        if m['from_edge'] in edges and m['to_edge'] in edges:
            movements[(m['from_edge'],m['to_edge'])].append(m)
    graph=defaultdict(set)
    constrained=defaultdict(set)
    for key,edge in edges.items():
        for following,connections in edge.getOutgoing().items():
            end=following.getID()
            if end not in edges or not any(c.getFromLane().allows('passenger') and c.getToLane().allows('passenger') for c in connections):continue
            graph[end].add(key)
            ms=movements.get((key,end),[])
            if not ms or min(m['length_m'] for m in ms)>=args.min_receiving_m:
                constrained[end].add(key)
    target='190144809#2'
    unconstrained,_=distances(target,graph,lengths)
    costs,successors=distances(target,constrained,lengths)
    arterial={'highway.primary','highway.secondary','highway.tertiary','highway.trunk',
              'highway.primary_link','highway.secondary_link','highway.tertiary_link','highway.trunk_link'}
    candidates=[]
    for origin,cost in costs.items():
        if cost<3000 or edges[origin].getType() not in arterial:continue
        stretch=cost/unconstrained[origin]
        if stretch>1.5:continue
        route=[origin]
        while route[-1]!=target:route.append(successors[route[-1]])
        ordered=[]
        approach_distance=0
        for a,b in zip(route,route[1:]):
            approach_distance+=lengths[a]
            ms=movements.get((a,b),[])
            if ms:
                ordered.append({'tls':ms[0]['tls'],'from_edge':a,'to_edge':b,
                    'incoming_edge_length_m':lengths[a],
                    'approach_path_length_m':approach_distance,
                    'minimum_receiving_lane_m':min(m['length_m'] for m in ms),
                    'protected_links':sorted({m['index'] for m in ms if m['protected_phases']})})
                approach_distance=0
        controllers={m['tls'] for m in ordered}
        long_controllers={m['tls'] for m in ordered if m['approach_path_length_m']>=args.min_approach_m and m['protected_links']}
        candidates.append({'origin':origin,'route_edges':route,'length_m':cost,
            'shortest_route_stretch':stretch,'controllers':len(controllers),
            'long_approach_controllers':len(long_controllers),'movements':ordered})
    candidates.sort(key=lambda c:(c['long_approach_controllers'],c['controllers'],c['length_m']),reverse=True)
    report={'target_baseline_journey_s':[1800,2100],
        'selection':'Geometry-only shortest legal connected routes avoiding receiving lanes below threshold; maximum 1.5x unconstrained shortest path. No forced loops, extra red time or vehicle slowdowns.',
        'network_sha256':sha256(directory/'district.net.xml'),
        'minimum_receiving_m':args.min_receiving_m,'long_approach_threshold_m':args.min_approach_m,
        'candidate_count':len(candidates),'candidates':candidates[:20],
        'baseline_duration_measured':False,'note':'Geometric eligibility is not proof of a 30–35 minute trip, safe import geometry, or a treatment benefit.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'candidates':len(candidates),'best':{k:v for k,v in candidates[0].items() if k not in ('route_edges','movements')} if candidates else None}))


if __name__=='__main__':main()

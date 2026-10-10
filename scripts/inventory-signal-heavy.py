"""Rank legal hospital routes by signal-delay opportunity, before paired trials."""
from collections import defaultdict
import heapq
import json
from pathlib import Path
import sumolib
from zelvo.simulation.smoke import sha256

directory=Path('scenarios/bengaluru')
reg=json.loads((directory/'registry.json').read_text())
net=sumolib.net.readNet(str(directory/'district.net.xml'),withInternal=True)
edges={e.getID():e for e in net.getEdges() if e.allows('passenger') and not e.getID().startswith(':')}
movements=defaultdict(list)
for m in reg['movements']:movements[m['from_edge'],m['to_edge']].append(m)
incoming=defaultdict(list)
for key,e in edges.items():
    for end,connections in e.getOutgoing().items():
        if end.getID() not in edges:continue
        legal=[c for c in connections if c.getFromLane().allows('passenger') and c.getToLane().allows('passenger')]
        if not legal:continue
        ms=movements.get((key,end.getID()),[])
        if ms and (min(m['length_m'] for m in ms)<10 or not any(m['protected_phases'] for m in ms)):continue
        via=net.getInternalPath(legal,fastest=True)[1] if any(c.getViaLaneID() for c in legal) else 0
        incoming[end.getID()].append((key,via))
times={k:e.getLength()/min(16.67,e.getSpeed()) for k,e in edges.items()}
target='190144809#2'
costs={target:times[target]};successors={};pending=[(times[target],target)]
while pending:
    cost,key=heapq.heappop(pending)
    if cost!=costs[key]:continue
    for before,via in incoming[key]:
        new=cost+times[before]+via
        if new<costs.get(before,float('inf')):
            costs[before]=new;successors[before]=key;heapq.heappush(pending,(new,before))
candidates=[]
for origin,cost in costs.items():
    if cost>600 or cost<90:continue
    route=[origin]
    while route[-1]!=target:route.append(successors[route[-1]])
    length=sum(edges[e].getLength() for e in route)
    if length<1800:continue
    ordered=[];seen=set();nominal_wait=0
    for a,b in zip(route,route[1:]):
        ms=movements.get((a,b),[])
        if not ms:continue
        m=next(m for m in ms if m['protected_phases'])
        if (m['tls'],m['index']) in seen:continue
        seen.add((m['tls'],m['index']))
        phases=reg['controllers'][m['tls']]['phases']
        cycle=sum(float(p['duration']) for p in phases)
        red=sum(float(p['duration']) for p in phases if p['state'][m['index']] not in 'Gg')
        nominal_wait+=red*red/(2*cycle)
        ordered.append({'tls':m['tls'],'link':m['index'],'from_edge':a,'to_edge':b,
                        'receiving_m':m['length_m'],'nominal_cycle_s':cycle,'nominal_red_s':red})
    visits=[]
    for m in ordered:
        if not visits or visits[-1]!=m['tls']:visits.append(m['tls'])
    if len(visits)!=len(set(visits)):continue
    controllers=len({m['tls'] for m in ordered})
    if controllers<6:continue
    candidates.append({'origin':origin,'route_edges':route,'length_m':length,'controllers':controllers,
                       'freeflow_with_internal_s':cost,'external_freeflow_s':sum(times[e] for e in route),'nominal_signal_wait_s':nominal_wait,
                       'opportunity_ratio':nominal_wait/(cost+nominal_wait),'movements':ordered})
candidates.sort(key=lambda c:c['opportunity_ratio'],reverse=True)
# Similar starts on the same path are one corridor, not independent candidates.
selected=[]
for c in candidates:
    ids={m['tls'] for m in c['movements']}
    if any(len(ids & {m['tls'] for m in s['movements']})/max(len(ids),s['controllers'])>.8 for s in selected):continue
    selected.append(c)
    if len(selected)==12:break
report={'selection':'Fastest legal hospital routes including internal-junction travel, receiving lanes >=10m and protected phases; >=1.8km and >=6 unique controllers; nonconsecutive controller reentry excluded; ranked by nominal uniform-arrival red-delay opportunity. Actuated outcomes must be measured; estimates exclude queues and acceleration.',
        'network_sha256':sha256(directory/'district.net.xml'),'candidate_count':len(candidates),'candidates':selected}
Path('reports/signal-heavy-inventory-v3.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps([{k:v for k,v in c.items() if k not in ('route_edges','movements')} for c in selected],indent=2))

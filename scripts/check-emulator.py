"""Reviewable controller integration lifecycle; never connects to hardware."""
import json
from pathlib import Path
from zelvo.contracts import PriorityRequest
from zelvo.integration import EmulatedAuthority,service_verified

request=PriorityRequest(request_id='demo-request',journey_id='ambulance-0',intersection_id='demo-tls',
    movement_id='straight',route_version=0,requested_at_s=0,arrival_earliest_s=10,
    arrival_latest_s=20,expires_at_s=30)
authority=EmulatedAuthority(acknowledgement_lost=True)
receipts=[authority.submit(request,0),authority.reconcile(request.request_id,1),authority.reconcile(request.request_id,6)]
blocked=service_verified(receipts[-1],now=6,observed_at=6,movement_green=True,receiving_space_m=0)
clear=service_verified(receipts[-1],now=6,observed_at=6,movement_green=True,receiving_space_m=20)
receipts.append(authority.confirm_passage(request.request_id,12))
report={'adapter':'deterministic emulator; no hardware connection',
        'receipts':[{'request_id':r.request_id,'status':r.status.value,'observed_at_s':r.observed_at_s,'reason':r.reason} for r in receipts],
        'service_verified_while_blocked':blocked,'service_verified_when_clear':clear}
output=Path('results/emulator-check.json')
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))

"""Explicit authority adapter contract and deterministic fault emulator.

No production protocol, hardware connection, or credential-based access is
implied. An accepted request is not proof of active green or receiving space.
"""
from dataclasses import dataclass
from typing import Protocol

from zelvo.contracts import PriorityRequest, RequestStatus


@dataclass(frozen=True)
class Receipt:
    request_id: str
    status: RequestStatus
    observed_at_s: float
    reason: str = ''
    revision: int = 0


class ControllerAdapter(Protocol):
    def submit(self,request: PriorityRequest,now: float) -> Receipt: ...
    def reconcile(self,request_id: str,now: float) -> Receipt: ...
    def cancel(self,request_id: str,now: float) -> Receipt: ...


def service_verified(receipt: Receipt, *, now: float, observed_at: float,
                     movement_green: bool, receiving_space_m: float, max_age_s=2) -> bool:
    return (receipt.status==RequestStatus.ACTIVE and 0<=now-receipt.observed_at_s<=max_age_s
            and 0<=now-observed_at<=max_age_s and movement_green and receiving_space_m>=10)


class EmulatedAuthority:
    def __init__(self, *, acknowledgement_lost=False, disconnected=False,
                 activation_delay_s=5, stale_status_s=0):
        self.acknowledgement_lost = acknowledgement_lost
        self.disconnected = disconnected
        self.activation_delay_s = activation_delay_s
        self.stale_status_s = stale_status_s
        self.requests = {}
        self.receipts = {}
        self.history = {}

    def submit(self,request: PriorityRequest,now: float) -> Receipt:
        if self.disconnected:
            return Receipt(request.request_id,RequestStatus.UNKNOWN,now,'disconnected')
        previous = self.requests.get(request.request_id)
        if previous is not None and previous != request:
            return Receipt(request.request_id,RequestStatus.REJECTED,now,'request ID reused with different payload')
        if previous is None:
            if request.expires_at_s<=now:
                return Receipt(request.request_id,RequestStatus.EXPIRED,now)
            self.requests[request.request_id] = request
            self.receipts[request.request_id] = Receipt(request.request_id,RequestStatus.ACCEPTED,now)
            self.history[request.request_id]=[self.receipts[request.request_id]]
        if self.acknowledgement_lost:
            return Receipt(request.request_id,RequestStatus.UNKNOWN,now,'acknowledgement lost; reconcile')
        return self.reconcile(request.request_id,now)

    def reconcile(self,request_id: str,now: float) -> Receipt:
        if self.disconnected or request_id not in self.requests:
            return Receipt(request_id,RequestStatus.UNKNOWN,now,'status unavailable')
        request = self.requests[request_id]
        receipt = self.receipts[request_id]
        if receipt.status not in (RequestStatus.CANCELLED,RequestStatus.COMPLETED,RequestStatus.EXPIRED):
            activation=max(self.history[request_id][0].observed_at_s,request.requested_at_s)+self.activation_delay_s
            if receipt.status==RequestStatus.ACCEPTED and activation<=now and activation<request.expires_at_s:
                receipt=Receipt(request_id,RequestStatus.ACTIVE,activation,revision=receipt.revision+1)
                self.history[request_id].append(receipt)
            if now>=request.expires_at_s:
                receipt=Receipt(request_id,RequestStatus.EXPIRED,request.expires_at_s,revision=receipt.revision+1)
                self.history[request_id].append(receipt)
            self.receipts[request_id]=receipt
        observed=max(0,now-self.stale_status_s)
        snapshots=[r for r in self.history[request_id] if r.observed_at_s<=observed]
        if not snapshots:return Receipt(request_id,RequestStatus.UNKNOWN,observed,'status predates request')
        historical=snapshots[-1]
        return Receipt(request_id,historical.status,observed,'stale status' if self.stale_status_s else '',historical.revision)

    def confirm_passage(self,request_id: str,now: float) -> Receipt:
        receipt = self.reconcile(request_id,now)
        actual=self.receipts.get(request_id)
        if receipt.status!=RequestStatus.ACTIVE or actual is None or actual.status!=RequestStatus.ACTIVE:
            return receipt
        receipt = Receipt(request_id,RequestStatus.COMPLETED,now,revision=receipt.revision+1)
        self.receipts[request_id] = receipt
        self.history[request_id].append(receipt)
        return receipt

    def cancel(self,request_id: str,now: float) -> Receipt:
        receipt = self.reconcile(request_id,now)
        if receipt.status==RequestStatus.UNKNOWN or receipt.status in (
            RequestStatus.COMPLETED,RequestStatus.EXPIRED,RequestStatus.CANCELLED):
            return receipt
        receipt=self.receipts[request_id]
        if receipt.status in (RequestStatus.COMPLETED,RequestStatus.EXPIRED,RequestStatus.CANCELLED):
            return self.reconcile(request_id,now)
        receipt = Receipt(request_id,RequestStatus.CANCELLED,now,revision=receipt.revision+1)
        self.receipts[request_id] = receipt
        self.history[request_id].append(receipt)
        return receipt

    def restart(self, *, preserve_state=True):
        self.disconnected = False
        if not preserve_state:
            self.requests.clear()
            self.receipts.clear()
            self.history.clear()

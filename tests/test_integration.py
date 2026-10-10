from zelvo.contracts import PriorityRequest,RequestStatus as S
from zelvo.integration import EmulatedAuthority


def request(**kw):
    return PriorityRequest(**(dict(request_id='request-1',journey_id='ambulance',intersection_id='tls',
        movement_id='movement',route_version=0,requested_at_s=0,arrival_earliest_s=10,
        arrival_latest_s=20,expires_at_s=30)|kw))


def test_lost_ack_is_ambiguous_and_idempotent_reconciliation():
    authority=EmulatedAuthority(acknowledgement_lost=True)
    assert authority.submit(request(),0).status==S.UNKNOWN
    assert authority.submit(request(),1).status==S.UNKNOWN
    assert len(authority.requests)==1
    assert authority.reconcile('request-1',1).status==S.ACCEPTED
    assert authority.reconcile('request-1',6).status==S.ACTIVE
    assert authority.confirm_passage('request-1',7).status==S.COMPLETED
    assert authority.cancel('request-1',8).status==S.COMPLETED


def test_conflicting_duplicate_expiry_cancel_restart_and_disconnect():
    authority=EmulatedAuthority()
    authority.submit(request(),0)
    assert authority.submit(request(route_version=1),1).status==S.REJECTED
    assert authority.reconcile('request-1',31).status==S.EXPIRED
    other=request(request_id='other')
    authority.submit(other,1)
    assert authority.cancel('other',2).status==S.CANCELLED
    authority.disconnected=True
    assert authority.reconcile('other',3).status==S.UNKNOWN
    authority.restart()
    assert authority.reconcile('other',3).status==S.CANCELLED
    authority.restart(preserve_state=False)
    assert authority.reconcile('other',3).status==S.UNKNOWN


def test_stale_receipt_keeps_timestamp_and_not_active_proof():
    authority=EmulatedAuthority(stale_status_s=10)
    authority.submit(request(),0)
    receipt=authority.reconcile('request-1',20)
    assert receipt.status==S.ACTIVE
    assert receipt.observed_at_s==10


def test_fresh_reconciliation_refreshes_observation_age_without_new_revision():
    authority=EmulatedAuthority()
    authority.submit(request(),0)
    first=authority.reconcile('request-1',6)
    second=authority.reconcile('request-1',10)
    assert first.status==second.status==S.ACTIVE
    assert first.revision==second.revision
    assert second.observed_at_s==10


def test_late_passage_cannot_overwrite_expired_authority_state_with_stale_active():
    authority=EmulatedAuthority(stale_status_s=10)
    authority.submit(request(),0)
    receipt=authority.confirm_passage('request-1',35)
    assert receipt.status==S.ACTIVE  # Historical view, timestamp 25.
    authority.stale_status_s=0
    assert authority.reconcile('request-1',35).status==S.EXPIRED


def test_acknowledgement_does_not_prove_clear_physical_service():
    from zelvo.integration import service_verified,Receipt
    receipt=Receipt('request-1',S.ACTIVE,10)
    assert not service_verified(receipt,now=10,observed_at=10,movement_green=True,receiving_space_m=0)
    assert not service_verified(receipt,now=20,observed_at=20,movement_green=True,receiving_space_m=100)
    assert service_verified(receipt,now=11,observed_at=11,movement_green=True,receiving_space_m=100)

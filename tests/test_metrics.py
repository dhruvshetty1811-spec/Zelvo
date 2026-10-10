import pytest
from zelvo.metrics import distribution


def test_empty_is_unknown_and_percentiles_include_all_observed_trips():
    assert distribution([])['p95'] is None
    summary=distribution([0,10,20,None])
    assert summary['count']==3
    assert summary['mean']==10
    assert summary['p50']==10
    assert summary['p95']==pytest.approx(19)
    with pytest.raises(ValueError):distribution([float('nan')])

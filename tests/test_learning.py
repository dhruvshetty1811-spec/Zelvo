import json
from pathlib import Path
import pytest
from zelvo.planning import Observation,FEATURES
from zelvo.learning import train,Predictor


def test_real_estimators_group_splits_hash_and_fallback(tmp_path):
    pytest.importorskip('sklearn')
    # Constructed data verifies the pipeline only; it is never demo evidence.
    rows=[]
    for seed in range(10):
        for n in range(30):
            o=Observation(time=n,vehicle='ev',tls='tls',link=0,incoming='in',outgoing='out',
                distance_m=50+n*5,speed_mps=5,queue_ahead=n%6,downstream_queue=n%4,
                queue_extent_m=(n%6)*7.5,entry_space_m=100-(n%4)*7.5,
                lane_length_m=100,green=float(n%2),action_hold=float(n%2))
            rows.append({'episode':f'seed-{seed}','seed':seed,'features':o.features(),
                         'eta_residual':float(n%6)*2+seed*.1,'queue_10s':n%4,
                         'censored':False})
    data=tmp_path/'training.jsonl'
    data.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    output=tmp_path/'model.joblib'
    report=train([data],output)
    groups=report['groups']
    assert not set(groups['train'])&set(groups['test'])
    assert not set(groups['validation'])&set(groups['test'])
    assert report['metrics']['test']['eta_learned_mae_s']>=0
    predictor=Predictor(output)
    assert predictor.predict(o) is not None
    o.distance_m=100000
    assert predictor.predict(o) is None
    output.write_bytes(output.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='hash'):
        Predictor(output)


def test_censored_targets_do_not_become_zero_labels(tmp_path):
    pytest.importorskip('sklearn')
    data=tmp_path/'training.jsonl'
    data.write_text(json.dumps({'seed':1,'eta_residual':None,'queue_10s':4,'censored':True,'features':[0]*len(FEATURES)})+'\n')
    with pytest.raises(ValueError,match='independent seeds'):
        train([data],tmp_path/'model.joblib')

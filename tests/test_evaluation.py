import json
import pytest
from zelvo.evaluation import compare


def results(tmp_path):
    paths=[]
    for i in range(2):
        config=tmp_path/f'config-{i}.json'
        config.write_text(json.dumps({'seed':42,'step_length_s':.1,'horizon_s':100,
                                     'network_file':'net.xml','route_files':['route.xml']}))
        result={'artifacts':{'config':str(config)},'input_hashes':{
            'net.xml':'network','route.xml':'routes','engine_source_sha256':'code'},
            'journeys':[{'vehicle_id':'ev','completed':False,'journey_time_s':None,
                         'stopped_time_s':2,'stops':1}],
            'run_id':f'run-{i}','status':'incomplete','controller':['actuated','zelvo_ai'][i],
            'collision_events':0,'teleport_events':0,'metrics':{}}
        path=tmp_path/f'result-{i}.json'
        path.write_text(json.dumps(result))
        paths.append(path)
    return paths


def test_pair_keeps_censored_journeys_unknown(tmp_path):
    report=compare(*results(tmp_path))
    assert report['journeys'][0]['saved_s'] is None
    assert not report['journeys'][0]['paired_completed']


def test_pair_rejects_changed_inputs(tmp_path):
    a,b=results(tmp_path)
    data=json.loads(b.read_text())
    data['input_hashes']['route.xml']='different'
    b.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='Unmatched route'):
        compare(a,b)

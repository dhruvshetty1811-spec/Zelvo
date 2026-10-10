import json
from pathlib import Path
import pytest
from zelvo.network import registry


def test_missing_controlled_link_is_not_silently_ignored(tmp_path):
    p=tmp_path/'bad.xml'
    p.write_text('<net><connection from="a" to="b" fromLane="0" toLane="0" tl="missing" linkIndex="0"/></net>')
    with pytest.raises(ValueError,match='absent signal'):
        registry(p)


def test_saved_district_lane_mapping_and_provenance():
    directory=Path('scenarios/bengaluru')
    if not (directory/'registry.json').is_file():pytest.skip('OSM district not downloaded')
    data=json.loads((directory/'registry.json').read_text(encoding='utf-8'))
    assert data['counts']['controllers']>30
    assert data['counts']['movements']>100
    assert all(m['incoming'] and m['outgoing'] and m['index']>=0 for m in data['movements'])
    import hashlib
    assert data['network_sha256']==hashlib.sha256((directory/'district.net.xml').read_bytes()).hexdigest()
    source=json.loads((directory/'source.json').read_text(encoding='utf-8'))
    assert source['sha256']==hashlib.sha256((directory/'district.osm.xml').read_bytes()).hexdigest()

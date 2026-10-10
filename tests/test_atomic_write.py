from pathlib import Path
import pytest
from zelvo.simulation.smoke import atomic_json
from zelvo.simulation.runner import archive_input


def test_transient_lock_retries_without_exposing_partial_document(tmp_path,monkeypatch):
    target=tmp_path/'status.json';target.write_text('old-complete')
    original=Path.replace
    calls=[]
    def locked(source,destination):
        calls.append(source)
        assert target.read_text()=='old-complete'
        if len(calls)<3:raise PermissionError('transient reader lock')
        return original(source,destination)
    monkeypatch.setattr(Path,'replace',locked)
    monkeypatch.setattr('zelvo.simulation.smoke.time.sleep',lambda _:None)
    atomic_json(target,'new-complete')
    assert target.read_text()=='new-complete\n' and len(calls)==3
    assert not list(tmp_path.glob('*.tmp'))


def test_persistent_lock_preserves_old_document_and_failure(tmp_path,monkeypatch):
    target=tmp_path/'status.json';target.write_text('old-complete')
    calls=[]
    def locked(source,destination):
        calls.append(source);raise PermissionError('persistent lock')
    monkeypatch.setattr(Path,'replace',locked)
    monkeypatch.setattr('zelvo.simulation.smoke.time.sleep',lambda _:None)
    with pytest.raises(PermissionError,match='persistent'):atomic_json(target,'new-complete')
    assert target.read_text()=='old-complete' and len(calls)==8
    assert len(list(tmp_path.glob('*.tmp')))==1


def test_concurrent_input_publication_is_immutable_and_detects_corruption(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    source=tmp_path/'net.xml';source.write_bytes(b'network-content'*20000)
    store=tmp_path/'inputs'
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths=list(pool.map(lambda _:archive_input(source,store),range(8)))
    assert len(set(paths))==1 and paths[0].read_bytes()==source.read_bytes()
    assert not list(store.glob('*.tmp'))
    paths[0].write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='hash mismatch'):archive_input(source,store)

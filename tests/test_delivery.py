import hashlib
import json
from pathlib import Path
import runpy
import zipfile

import pytest

write_zip = runpy.run_path(str(Path(__file__).parents[1]/'scripts/package-backend.py'))['write_verified_zip']


def test_portable_archive_preserves_evidence_and_refuses_overwrite(tmp_path):
    source=tmp_path/'raw.xml';source.write_bytes(b'<tripinfo duration="76.6"/>')
    target=tmp_path/'bundle.zip'
    measured=write_zip(target,{'evidence/raw.xml':source},{'README.md':b'Reproduction'})
    with zipfile.ZipFile(target) as archive:
        manifest=json.loads(archive.read('bundle-manifest.json'))
        for name,digest in manifest['sha256'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest
        assert archive.read('evidence/raw.xml')==source.read_bytes()
    assert measured['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='overwrite'):write_zip(target,{}, {})


@pytest.mark.parametrize('name',['../escape','/absolute','C:/absolute','a\\escape','bundle-manifest.json'])
def test_archive_rejects_unsafe_or_reserved_members(tmp_path,name):
    with pytest.raises(ValueError,match='Unsafe'):
        write_zip(tmp_path/'bundle.zip',{}, {name:b'invalid'})
    assert not (tmp_path/'bundle.zip').exists()

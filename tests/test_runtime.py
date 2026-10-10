import os

import pytest

from zelvo.runtime import RuntimeInfo, installed_sumo_environment


def test_launch_environment_restores_parent_even_on_failure(tmp_path, monkeypatch):
    (tmp_path / "data/xsd").mkdir(parents=True)
    monkeypatch.setenv("SUMO_HOME", "incorrect-installer.msi")
    runtime = RuntimeInfo(sumo_binary=tmp_path / "bin/sumo.exe",
                          netconvert_binary=tmp_path / "bin/netconvert.exe",
                          versions={}, diagnostics=(), libsumo_available=False)
    with pytest.raises(RuntimeError):
        with installed_sumo_environment(runtime):
            assert os.environ["SUMO_HOME"] == str(tmp_path)
            raise RuntimeError("simulated launch failure")
    assert os.environ["SUMO_HOME"] == "incorrect-installer.msi"

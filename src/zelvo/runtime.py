"""Discover installed SUMO tools without trusting an invalid SUMO_HOME."""

from contextlib import contextmanager
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

from pydantic import BaseModel


class RuntimeInfo(BaseModel):
    sumo_binary: Path
    netconvert_binary: Path
    versions: dict[str, str]
    diagnostics: tuple[str, ...]
    libsumo_available: bool


def child_environment(runtime: RuntimeInfo) -> dict[str, str]:
    environment = os.environ.copy()
    root = runtime.sumo_binary.parent.parent
    if (root / "data" / "xsd").is_dir():
        environment["SUMO_HOME"] = str(root)
    return environment


@contextmanager
def installed_sumo_environment(runtime: RuntimeInfo):
    """TraCI spawns with inherited env; scope the correction to process launch.

    Each simulation worker owns its process and connection; this context is not
    intended for concurrent launches from multiple threads in one process.
    """
    previous = os.environ.get("SUMO_HOME")
    effective = child_environment(runtime).get("SUMO_HOME")
    if effective is not None:
        os.environ["SUMO_HOME"] = effective
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SUMO_HOME", None)
        else:
            os.environ["SUMO_HOME"] = previous


def discover_tools() -> RuntimeInfo:
    diagnostics: list[str] = []
    roots: list[Path] = []
    if home := os.environ.get("SUMO_HOME"):
        root = Path(home)
        if root.is_dir():
            roots.append(root)
        else:
            diagnostics.append("Ignored SUMO_HOME: it is not an existing directory.")
    roots.append(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Eclipse/Sumo")
    binaries: dict[str, Path] = {}
    for name in ("sumo", "netconvert"):
        explicit = os.environ.get(f"ZELVO_{name.upper()}_BINARY")
        if explicit:
            candidate = Path(explicit)
            if not candidate.is_file():
                raise RuntimeError(f"ZELVO_{name.upper()}_BINARY does not name an existing file")
        elif found := shutil.which(name):
            candidate = Path(found)
        else:
            suffix = ".exe" if os.name == "nt" else ""
            candidate = next((r / "bin" / (name + suffix) for r in roots
                              if (r / "bin" / (name + suffix)).is_file()), None)
            if candidate is None:
                raise RuntimeError(f"Cannot find {name}; install SUMO or set ZELVO_{name.upper()}_BINARY")
        binaries[name] = candidate.resolve()
    versions = {"python": platform.python_version()}
    for name, executable in binaries.items():
        result = subprocess.run([str(executable), "--version"], capture_output=True,
                                text=True, timeout=45, check=True)
        match = re.search(r"(?:sumo|netconvert)\s+(\d+\.\d+\.\d+)", result.stdout, re.I)
        if match is None:
            raise RuntimeError(f"Unrecognised {name} version output")
        versions[name] = match.group(1)
    for package in ("traci", "sumolib", "pydantic"):
        versions[package] = importlib.metadata.version(package)
    if len({versions[name] for name in ("sumo", "netconvert", "traci", "sumolib")}) != 1:
        raise RuntimeError("SUMO, netconvert, traci and sumolib versions must match: " + str(versions))
    return RuntimeInfo(sumo_binary=binaries["sumo"], netconvert_binary=binaries["netconvert"],
                       versions=versions, diagnostics=tuple(diagnostics),
                       libsumo_available=importlib.util.find_spec("libsumo") is not None)

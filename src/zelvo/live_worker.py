"""Fresh process per controller. Preload native SUMO before other DLL consumers."""
import libsumo  # noqa: F401; Windows DLL import order is deliberate.
import json
import os
from pathlib import Path
import sys

from zelvo.live import LiveTelemetry
from zelvo.simulation.runner import run_episode
from zelvo.simulation.smoke import atomic_json


def main():
    config,work,policy,model,dispatch = sys.argv[1:]
    work = Path(work)
    with (work/'frames.jsonl').open('w',encoding='utf-8') as stream:
        telemetry = LiveTelemetry(stream,json.loads((work/'signals.json').read_text()),float(dispatch),
                                  interval_s=float(os.environ.get('ZELVO_FRAME_INTERVAL_S','.2')))
        result = run_episode(Path(config),work,controller=policy,backend='libsumo',
                             model_path=Path(model) if policy=='zelvo_ai' else None,telemetry=telemetry)
        telemetry.finalize(result)
    atomic_json(work/'result.json',result.model_dump_json(indent=2))


if __name__=='__main__':
    main()

"""Load configurations relative to their own file, not the shell directory."""

from pathlib import Path

from zelvo.contracts import NetworkBuild, ScenarioConfig


def load_scenario(config_path: Path) -> ScenarioConfig:
    config_path = config_path.resolve()
    config = ScenarioConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    resolve = lambda path: (base / path).resolve()
    build = None
    if config.build:
        build = NetworkBuild(
            nodes_file=resolve(config.build.nodes_file),
            edges_file=resolve(config.build.edges_file),
        )
    config = config.model_copy(update={
        "network_file": resolve(config.network_file),
        "route_files": tuple(resolve(path) for path in config.route_files),
        "build": build,
    })
    required = list(config.route_files)
    required += [build.nodes_file, build.edges_file] if build else [config.network_file]
    for path in required:
        if not path.is_file():
            raise ValueError(f"Scenario input does not exist: {path}")
    return config

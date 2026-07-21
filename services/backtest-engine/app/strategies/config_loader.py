from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def strategy_dir(name: str) -> Path:
    return Path(__file__).resolve().parent / name

def load_json_file(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))

def load_strategy_config(name: str) -> dict[str, Any]:
    return load_json_file(strategy_dir(name) / "config.json", {})

def load_strategy_regimes(name: str) -> dict[str, Any]:
    return load_json_file(strategy_dir(name) / "regimes.json", {})

def load_strategy_version(name: str) -> dict[str, Any]:
    return load_json_file(strategy_dir(name) / "version.json", {})

def default_parameters(config: dict[str, Any]) -> dict[str, Any]:
    params = config.get("parameters", {}) or {}
    return {k: v.get("default") for k, v in params.items() if isinstance(v, dict) and "default" in v}

def merge_config_defaults(strategy_name: str, run_config: dict[str, Any] | None = None) -> dict[str, Any]:
    base = load_strategy_config(strategy_name)
    merged = default_parameters(base)
    merged.update(run_config or {})
    return merged

def metadata_payload(name: str) -> dict[str, Any]:
    cfg = load_strategy_config(name)
    return {"config": cfg, "regimes": load_strategy_regimes(name), "version": load_strategy_version(name), "default_parameters": default_parameters(cfg)}

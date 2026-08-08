from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


PRODUCTION_ROOT = Path(os.getenv("BACKTEST_PRODUCTION_SOURCE_ROOT", "/app/production"))
PRODUCTION_PARITY_RUNTIME_VERSION = "production_source_runtime_v1"


def _service_dir(service: str) -> Path:
    path = PRODUCTION_ROOT / service
    if not path.is_dir():
        raise RuntimeError(f"production_reference_missing:{service}:{path}")
    value = str(path)
    if value not in sys.path:
        sys.path.append(value)
    return path


@lru_cache(maxsize=None)
def load_production_module(service: str, module_name: str) -> ModuleType:
    directory = _service_dir(service)
    source = directory / f"{module_name}.py"
    if not source.is_file():
        raise RuntimeError(f"production_module_missing:{service}:{module_name}")

    alias = f"tradetower_production_{service}_{module_name}".replace("-", "_")
    existing = sys.modules.get(alias)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(alias, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"production_module_load_failed:{service}:{module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def production_runtime_contract() -> dict:
    return {
        "version": PRODUCTION_PARITY_RUNTIME_VERSION,
        "root": str(PRODUCTION_ROOT),
        "policy": "exact production source copied into backtest image; production services remain untouched",
        "services": [
            "feature_factory",
            "candidate_filter",
            "strategy_engine",
            "risk_engine",
            "trade_guardian",
        ],
    }

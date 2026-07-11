import json
import re

from api_clients import fetch_market_instrument
from config import (
    MARKET_DATA_MARKET,
    MARKET_DATA_PROVIDER,
    MARKET_SYMBOL_VALIDATION_ENABLED,
    SYMBOL_UNIVERSE_PATH,
)


_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def _base_rejection(item: dict, reason: str) -> dict:
    return {
        "symbol": item.get("symbol"),
        "normalized_symbol": (
            normalize_symbol(item.get("symbol", ""))
            if item.get("symbol")
            else None
        ),
        "enabled": bool(item.get("enabled", False)),
        "priority": item.get("priority"),
        "reason": reason,
    }


def _load_raw_universe() -> dict:
    with open(SYMBOL_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_symbol_universe_report() -> dict:
    payload = _load_raw_universe()

    enabled = []
    rejected = []
    seen = set()

    for item in payload.get("symbols", []):
        if not item.get("enabled", False):
            rejected.append(_base_rejection(item, "disabled"))
            continue

        raw_symbol = item.get("symbol")
        if not raw_symbol:
            rejected.append(_base_rejection(item, "missing_symbol"))
            continue

        symbol = normalize_symbol(raw_symbol)

        if not _SYMBOL_RE.match(symbol):
            rejected.append({
                **_base_rejection(item, "invalid_internal_symbol"),
                "normalized_symbol": symbol,
            })
            continue

        if symbol in seen:
            rejected.append({
                **_base_rejection(item, "duplicate_symbol"),
                "normalized_symbol": symbol,
            })
            continue

        seen.add(symbol)

        normalized_item = {
            "symbol": symbol,
            "enabled": True,
            "priority": int(item.get("priority", 999)),
            "metadata": {},
        }

        if MARKET_SYMBOL_VALIDATION_ENABLED:
            instrument, error = fetch_market_instrument(symbol)
            if error:
                rejected.append({
                    **normalized_item,
                    "reason": error,
                })
                continue

            normalized_item["provider"] = MARKET_DATA_PROVIDER
            normalized_item["market"] = MARKET_DATA_MARKET
            normalized_item["provider_symbol"] = instrument.get(
                "provider_symbol"
            )
            normalized_item["metadata"] = instrument
        else:
            normalized_item["provider"] = MARKET_DATA_PROVIDER
            normalized_item["market"] = MARKET_DATA_MARKET
            normalized_item["provider_symbol"] = None

        enabled.append(normalized_item)

    enabled.sort(key=lambda x: (x.get("priority", 999), x["symbol"]))

    return {
        "schema_version": payload.get("schema_version", "symbol_universe_v1"),
        "provider_neutral": bool(payload.get("provider_neutral", False)),
        "provider": MARKET_DATA_PROVIDER,
        "market": MARKET_DATA_MARKET,
        "validation_enabled": MARKET_SYMBOL_VALIDATION_ENABLED,
        "enabled": enabled,
        "rejected": rejected,
        "enabled_symbols": [item["symbol"] for item in enabled],
        "enabled_count": len(enabled),
        "rejected_count": len(rejected),
    }


def load_symbol_universe():
    return load_symbol_universe_report()["enabled_symbols"]

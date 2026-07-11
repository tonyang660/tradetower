from pathlib import Path
import json

from config import API_GATEWAY_BASE_URL, MARKET_DATA_PROVIDER, SYMBOL_UNIVERSE_PATH
from http_client import get_json


def normalize_symbol(symbol: str) -> str:
    return str(symbol).upper().strip().replace("/", "").replace("-", "")


def load_symbol_universe_config():
    path = Path(SYMBOL_UNIVERSE_PATH)

    if not path.exists():
        return {
            "ok": False,
            "error": "symbol_universe_not_found",
            "path": str(path),
        }

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        return {
            "ok": False,
            "error": "symbol_universe_read_failed",
            "details": str(e),
            "path": str(path),
        }

    enabled_symbols = []
    for item in payload.get("symbols", []):
        symbol = normalize_symbol(item.get("symbol", ""))
        if symbol and bool(item.get("enabled", False)):
            enabled_symbols.append(symbol)

    return {
        "ok": True,
        "path": str(path),
        "raw": payload,
        "enabled_symbols": enabled_symbols,
    }


def save_symbol_universe_config(symbols: list[str]):
    path = Path(SYMBOL_UNIVERSE_PATH)

    normalized = []
    seen = set()

    for symbol in symbols:
        value = normalize_symbol(symbol)
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    if not normalized:
        return {
            "ok": False,
            "error": "empty_symbol_universe_not_allowed",
        }

    payload = {
        "schema_version": "symbol_universe_v2",
        "provider_neutral": True,
        "market": "usdt_perp",
        "quote_currency": "USDT",
        "symbols": [
            {
                "symbol": symbol,
                "enabled": True,
                "priority": 1,
            }
            for symbol in normalized
        ],
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
    except Exception as e:
        return {
            "ok": False,
            "error": "symbol_universe_write_failed",
            "details": str(e),
            "path": str(path),
        }

    return {
        "ok": True,
        "saved": True,
        "path": str(path),
        "enabled_symbols": normalized,
        "count": len(normalized),
    }


def validate_symbol_via_api_gateway(symbol: str):
    normalized = normalize_symbol(symbol)

    if not normalized:
        return {
            "ok": False,
            "valid": False,
            "error": "empty_symbol",
            "symbol": normalized,
        }, 400

    payload, status_code, error = get_json(
        f"{API_GATEWAY_BASE_URL}/market/instruments",
        params={
            "symbol": normalized,
            "provider": MARKET_DATA_PROVIDER,
        },
        timeout=10,
    )

    if error:
        return {
            "ok": False,
            "valid": False,
            "symbol": normalized,
            "provider": MARKET_DATA_PROVIDER,
            "error": error,
        }, 500

    if status_code != 200 or not payload or not payload.get("ok"):
        return {
            "ok": False,
            "valid": False,
            "symbol": normalized,
            "provider": MARKET_DATA_PROVIDER,
            "error": (
                payload.get("error", "symbol_not_found")
                if isinstance(payload, dict)
                else "symbol_not_found"
            ),
        }, 400

    instruments = payload.get("instruments", [])
    live_instruments = [
        item for item in instruments
        if str(item.get("state", "")).lower() == "live"
    ]

    if not live_instruments:
        return {
            "ok": False,
            "valid": False,
            "symbol": normalized,
            "provider": MARKET_DATA_PROVIDER,
            "error": "instrument_not_found_or_not_live",
            "instruments": instruments,
        }, 400

    return {
        "ok": True,
        "valid": True,
        "symbol": normalized,
        "provider": MARKET_DATA_PROVIDER,
        "message": "Symbol validated successfully.",
        "instrument": live_instruments[0],
    }, 200

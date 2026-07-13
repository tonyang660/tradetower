from pathlib import Path
import json

from config import API_GATEWAY_BASE_URL, MARKET_DATA_PROVIDER, SYMBOL_UNIVERSE_PATH
from http_client import get_json


DEFAULT_CORRELATION_GROUP = "independent"

DEFAULT_SYMBOL_CORRELATION_GROUPS = {
    "BTCUSDT": "btc_followers",
    "LTCUSDT": "btc_followers",
    "ETHUSDT": "major_alts",
    "XRPUSDT": "major_alts",
    "XLMUSDT": "major_alts",
    "BNBUSDT": "major_alts",
    "SOLUSDT": "layer1",
    "ADAUSDT": "layer1",
    "DOTUSDT": "layer1",
    "SUIUSDT": "layer1",
    "SEIUSDT": "layer1",
    "LINKUSDT": "defi",
    "ARBUSDT": "defi",
    "HBARUSDT": "independent",
    "DOGEUSDT": "meme",
    "PEPEUSDT": "meme",
    "ZECUSDT": "privacy",
    "XMRUSDT": "privacy",
    "TAOUSDT": "ai_sector",
    "HYPEUSDT": "independent",
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol).upper().strip().replace("/", "").replace("-", "")


def normalize_correlation_group(value: str | None) -> str:
    value = str(value or "").strip().lower()
    return value or DEFAULT_CORRELATION_GROUP


def default_correlation_group_for_symbol(symbol: str) -> str:
    return DEFAULT_SYMBOL_CORRELATION_GROUPS.get(
        normalize_symbol(symbol),
        DEFAULT_CORRELATION_GROUP,
    )


def normalize_symbol_item(item) -> dict | None:
    if isinstance(item, str):
        symbol = normalize_symbol(item)
        if not symbol:
            return None
        return {
            "symbol": symbol,
            "enabled": True,
            "priority": 1,
            "correlation_group": default_correlation_group_for_symbol(symbol),
        }

    if not isinstance(item, dict):
        return None

    symbol = normalize_symbol(item.get("symbol", ""))
    if not symbol:
        return None

    return {
        "symbol": symbol,
        "enabled": bool(item.get("enabled", True)),
        "priority": int(item.get("priority", 1)),
        "correlation_group": normalize_correlation_group(
            item.get("correlation_group")
            or default_correlation_group_for_symbol(symbol)
        ),
    }


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

    symbols = []
    enabled_symbols = []

    for raw_item in payload.get("symbols", []):
        item = normalize_symbol_item(raw_item)
        if not item:
            continue
        symbols.append(item)
        if item["enabled"]:
            enabled_symbols.append(item["symbol"])

    return {
        "ok": True,
        "path": str(path),
        "raw": payload,
        "symbols": symbols,
        "enabled_symbols": enabled_symbols,
        "correlation_groups": sorted({
            item["correlation_group"]
            for item in symbols
        }),
    }


def save_symbol_universe_config(symbols: list):
    path = Path(SYMBOL_UNIVERSE_PATH)

    normalized = []
    seen = set()

    for raw_item in symbols:
        item = normalize_symbol_item(raw_item)
        if not item:
            continue
        symbol = item["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(item)

    if not normalized:
        return {
            "ok": False,
            "error": "empty_symbol_universe_not_allowed",
        }

    payload = {
        "schema_version": "symbol_universe_v3",
        "provider_neutral": True,
        "market": "usdt_perp",
        "quote_currency": "USDT",
        "notes": [
            "Symbols are TradeTower internal symbols, e.g. BTCUSDT.",
            "Provider-specific symbols such as BTC-USDT are resolved by api-gateway.",
            "correlation_group is user-editable and consumed by Risk Engine Step 7.",
        ],
        "symbols": normalized,
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
        "symbols": normalized,
        "enabled_symbols": [
            item["symbol"]
            for item in normalized
            if item["enabled"]
        ],
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
        "default_correlation_group": default_correlation_group_for_symbol(normalized),
    }, 200

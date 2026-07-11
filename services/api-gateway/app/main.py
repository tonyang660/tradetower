from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os
import urllib.parse

import requests


SERVICE_NAME = "api-gateway"
PORT = int(os.getenv("PORT", "8080"))

DEFAULT_MARKET_PROVIDER = os.getenv(
    "DEFAULT_MARKET_PROVIDER",
    "blofin",
).lower()

BLOFIN_REST_BASE_URL = os.getenv(
    "BLOFIN_REST_BASE_URL",
    "https://openapi.blofin.com",
)

BITGET_PRODUCT_TYPE = "USDT-FUTURES"

# Internal timeframe names -> provider bar names.
TIMEFRAME_MAP = {
    "1m": {
        "bitget": "1m",
        "blofin": "1m",
    },
    "3m": {
        "blofin": "3m",
    },
    "5m": {
        "bitget": "5m",
        "blofin": "5m",
    },
    "15m": {
        "bitget": "15m",
        "blofin": "15m",
    },
    "30m": {
        "blofin": "30m",
    },
    "1h": {
        "bitget": "1H",
        "blofin": "1H",
    },
    "2h": {
        "blofin": "2H",
    },
    "4h": {
        "bitget": "4H",
        "blofin": "4H",
    },
    "6h": {
        "blofin": "6H",
    },
    "8h": {
        "blofin": "8H",
    },
    "12h": {
        "blofin": "12H",
    },
    "1d": {
        "blofin": "1D",
    },
}


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ms_to_iso8601_utc(ms_str: str) -> str:
    dt = datetime.fromtimestamp(int(ms_str) / 1000, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _json_get(url: str, params: dict | None = None, timeout: int = 10):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }

    response = requests.get(
        url,
        params=params or {},
        headers=headers,
        timeout=timeout,
    )

    response.raise_for_status()
    return response.json()


def normalize_internal_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("/", "").replace("-", "")


def to_blofin_inst_id(symbol: str) -> str:
    value = str(symbol).strip().upper().replace("/", "-")

    if "-" in value:
        return value

    if value.endswith("USDT"):
        return f"{value[:-4]}-USDT"

    return value


def to_bitget_symbol(symbol: str) -> str:
    return normalize_internal_symbol(symbol)


def provider_timeframe(timeframe: str, provider: str):
    config = TIMEFRAME_MAP.get(str(timeframe).lower())
    if not config:
        return None
    return config.get(provider)


def normalize_bitget_candle(raw_candle: list) -> dict:
    """
    Bitget futures candle response format:
    [timestamp_ms, open, high, low, close, volume_base, volume_quote]
    """
    return {
        "timestamp": ms_to_iso8601_utc(raw_candle[0]),
        "open": float(raw_candle[1]),
        "high": float(raw_candle[2]),
        "low": float(raw_candle[3]),
        "close": float(raw_candle[4]),
        "volume": float(raw_candle[5]),
        "volume_contracts": None,
        "volume_base": float(raw_candle[5]),
        "volume_quote": float(raw_candle[6]) if len(raw_candle) > 6 else None,
        "confirm": None,
        "provider_ts": str(raw_candle[0]),
    }


def fetch_bitget_candles(symbol: str, timeframe: str, limit: int):
    granularity = provider_timeframe(timeframe, "bitget")
    if granularity is None:
        return None, "invalid_timeframe"

    if limit <= 0:
        return None, "invalid_limit"

    params = {
        "symbol": to_bitget_symbol(symbol),
        "productType": BITGET_PRODUCT_TYPE,
        "granularity": granularity,
        "limit": limit,
    }

    url = "https://api.bitget.com/api/v2/mix/market/candles"

    try:
        payload = _json_get(url, params=params, timeout=10)
    except Exception:
        return None, "request_failed"

    code = payload.get("code")
    data = payload.get("data")

    if code != "00000":
        return None, "provider_error"

    if not data:
        return None, "no_data"

    candles = []
    for raw in data:
        try:
            candles.append(normalize_bitget_candle(raw))
        except Exception:
            continue

    if not candles:
        return None, "normalization_failed"

    candles.sort(key=lambda c: c["timestamp"])

    return candles, None


def fetch_bitget_ticker(symbol: str):
    bitget_symbol = to_bitget_symbol(symbol)

    try:
        response = requests.get(
            "https://api.bitget.com/api/v2/mix/market/ticker",
            params={
                "symbol": bitget_symbol,
                "productType": BITGET_PRODUCT_TYPE,
            },
            timeout=10,
        )
        payload = response.json()
    except Exception as e:
        return None, f"bitget_request_failed: {str(e)}"

    if payload.get("code") != "00000":
        return None, payload.get("msg", "bitget_error")

    data = payload.get("data", [])
    if not data:
        return None, "empty_ticker_response"

    item = data[0]

    return {
        "symbol": normalize_internal_symbol(symbol),
        "provider_symbol": item.get("symbol", bitget_symbol),
        "last_price": float(item["lastPr"]),
        "mark_price": (
            float(item["markPrice"])
            if item.get("markPrice") is not None
            else None
        ),
        "bid_price": (
            float(item["bidPr"])
            if item.get("bidPr") is not None
            else None
        ),
        "ask_price": (
            float(item["askPr"])
            if item.get("askPr") is not None
            else None
        ),
        "high_24h": None,
        "low_24h": None,
        "open_24h": None,
        "volume_24h": None,
        "volume_base_24h": None,
        "provider_ts": item.get("ts"),
        "timestamp": (
            ms_to_iso8601_utc(item["ts"])
            if item.get("ts")
            else None
        ),
    }, None


def normalize_blofin_candle(raw_candle: list) -> dict:
    """
    BloFin candle format:
    [
      ts,
      open,
      high,
      low,
      close,
      vol,
      volCurrency,
      volCurrencyQuote,
      confirm
    ]
    """
    return {
        "timestamp": ms_to_iso8601_utc(raw_candle[0]),
        "open": float(raw_candle[1]),
        "high": float(raw_candle[2]),
        "low": float(raw_candle[3]),
        "close": float(raw_candle[4]),
        "volume": float(raw_candle[6]) if len(raw_candle) > 6 else float(raw_candle[5]),
        "volume_contracts": float(raw_candle[5]) if len(raw_candle) > 5 else None,
        "volume_base": float(raw_candle[6]) if len(raw_candle) > 6 else None,
        "volume_quote": float(raw_candle[7]) if len(raw_candle) > 7 else None,
        "confirm": str(raw_candle[8]) if len(raw_candle) > 8 else None,
        "provider_ts": str(raw_candle[0]),
    }


def fetch_blofin_candles(symbol: str, timeframe: str, limit: int):
    bar = provider_timeframe(timeframe, "blofin")
    if bar is None:
        return None, "invalid_timeframe"

    if limit <= 0 or limit > 1440:
        return None, "invalid_limit"

    inst_id = to_blofin_inst_id(symbol)

    try:
        payload = _json_get(
            f"{BLOFIN_REST_BASE_URL}/api/v1/market/candles",
            params={
                "instId": inst_id,
                "bar": bar,
                "limit": limit,
            },
            timeout=10,
        )
    except Exception as e:
        return None, f"blofin_request_failed: {str(e)}"

    if payload.get("code") != "0":
        return None, payload.get("msg", "blofin_error")

    data = payload.get("data", [])
    if not data:
        return None, "no_data"

    candles = []
    for raw in data:
        try:
            candles.append(normalize_blofin_candle(raw))
        except Exception:
            continue

    if not candles:
        return None, "normalization_failed"

    # BloFin returns newest first. TradeTower internal contract is oldest first.
    candles.sort(key=lambda c: c["timestamp"])

    return candles, None


def fetch_blofin_ticker(symbol: str):
    inst_id = to_blofin_inst_id(symbol)

    try:
        payload = _json_get(
            f"{BLOFIN_REST_BASE_URL}/api/v1/market/tickers",
            params={
                "instId": inst_id,
            },
            timeout=10,
        )
    except Exception as e:
        return None, f"blofin_request_failed: {str(e)}"

    if payload.get("code") != "0":
        return None, payload.get("msg", "blofin_error")

    data = payload.get("data", [])
    if not data:
        return None, "empty_ticker_response"

    item = data[0]

    return {
        "symbol": normalize_internal_symbol(symbol),
        "provider_symbol": item.get("instId", inst_id),
        "last_price": float(item["last"]),
        "mark_price": None,
        "bid_price": (
            float(item["bidPrice"])
            if item.get("bidPrice") is not None
            else None
        ),
        "ask_price": (
            float(item["askPrice"])
            if item.get("askPrice") is not None
            else None
        ),
        "high_24h": (
            float(item["high24h"])
            if item.get("high24h") is not None
            else None
        ),
        "low_24h": (
            float(item["low24h"])
            if item.get("low24h") is not None
            else None
        ),
        "open_24h": (
            float(item["open24h"])
            if item.get("open24h") is not None
            else None
        ),
        "volume_24h": (
            float(item["vol24h"])
            if item.get("vol24h") is not None
            else None
        ),
        "volume_base_24h": (
            float(item["volCurrency24h"])
            if item.get("volCurrency24h") is not None
            else None
        ),
        "provider_ts": item.get("ts"),
        "timestamp": (
            ms_to_iso8601_utc(item["ts"])
            if item.get("ts")
            else None
        ),
    }, None


def fetch_blofin_instruments(symbol: str | None = None):
    params = {}
    if symbol:
        params["instId"] = to_blofin_inst_id(symbol)

    try:
        payload = _json_get(
            f"{BLOFIN_REST_BASE_URL}/api/v1/market/instruments",
            params=params,
            timeout=10,
        )
    except Exception as e:
        return None, f"blofin_request_failed: {str(e)}"

    if payload.get("code") != "0":
        return None, payload.get("msg", "blofin_error")

    items = []
    for item in payload.get("data", []):
        try:
            items.append({
                "symbol": normalize_internal_symbol(item["instId"]),
                "provider_symbol": item["instId"],
                "base_currency": item.get("baseCurrency"),
                "quote_currency": item.get("quoteCurrency"),
                "settle_currency": item.get("settleCurrency"),
                "contract_value": (
                    float(item["contractValue"])
                    if item.get("contractValue") is not None
                    else None
                ),
                "min_size": (
                    float(item["minSize"])
                    if item.get("minSize") is not None
                    else None
                ),
                "lot_size": (
                    float(item["lotSize"])
                    if item.get("lotSize") is not None
                    else None
                ),
                "tick_size": (
                    float(item["tickSize"])
                    if item.get("tickSize") is not None
                    else None
                ),
                "max_leverage": (
                    float(item["maxLeverage"])
                    if item.get("maxLeverage") is not None
                    else None
                ),
                "instrument_type": item.get("instType"),
                "contract_type": item.get("contractType"),
                "state": item.get("state"),
                "raw": item,
            })
        except Exception:
            continue

    return items, None


def resolve_market_provider(query: dict):
    return query.get("provider", [DEFAULT_MARKET_PROVIDER])[0].lower()


def fetch_market_candles(provider: str, symbol: str, timeframe: str, limit: int):
    if provider == "blofin":
        return fetch_blofin_candles(symbol, timeframe, limit)
    if provider == "bitget":
        return fetch_bitget_candles(symbol, timeframe, limit)
    return None, "unsupported_provider"


def fetch_market_ticker(provider: str, symbol: str):
    if provider == "blofin":
        return fetch_blofin_ticker(symbol)
    if provider == "bitget":
        return fetch_bitget_ticker(symbol)
    return None, "unsupported_provider"


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._send_json({
            "ok": False,
            "error": "not_found",
            "path": self.path,
        }, status=404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json({
                "ok": True,
                "service": SERVICE_NAME,
                "default_market_provider": DEFAULT_MARKET_PROVIDER,
                "blofin_rest_base_url": BLOFIN_REST_BASE_URL,
                "timestamp": iso_now(),
            })
            return

        if parsed.path in (
            "/market/candles",
            "/providers/blofin/candles",
            "/providers/bitget/candles",
        ):
            provider = resolve_market_provider(query)
            if parsed.path.startswith("/providers/blofin"):
                provider = "blofin"
            if parsed.path.startswith("/providers/bitget"):
                provider = "bitget"

            symbol = query.get("symbol", [None])[0]
            timeframe = query.get("timeframe", [None])[0]

            try:
                limit = int(query.get("limit", [50])[0])
            except ValueError:
                self._send_json({
                    "ok": False,
                    "error": "invalid_limit",
                }, status=400)
                return

            if not symbol or not timeframe:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol", "timeframe"],
                }, status=400)
                return

            candles, error = fetch_market_candles(
                provider,
                symbol,
                timeframe,
                limit,
            )

            if error:
                self._send_json({
                    "ok": False,
                    "provider": provider,
                    "error": error,
                    "symbol": normalize_internal_symbol(symbol),
                    "timeframe": timeframe,
                    "limit": limit,
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "provider": provider,
                "market": "usdt_perp",
                "symbol": normalize_internal_symbol(symbol),
                "provider_symbol": (
                    to_blofin_inst_id(symbol)
                    if provider == "blofin"
                    else to_bitget_symbol(symbol)
                ),
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles,
            })
            return

        if parsed.path in (
            "/market/ticker",
            "/providers/blofin/ticker",
            "/providers/bitget/ticker",
        ):
            provider = resolve_market_provider(query)
            if parsed.path.startswith("/providers/blofin"):
                provider = "blofin"
            if parsed.path.startswith("/providers/bitget"):
                provider = "bitget"

            symbol = query.get("symbol", [None])[0]

            if not symbol:
                self._send_json({
                    "ok": False,
                    "error": "missing_parameters",
                    "required": ["symbol"],
                }, status=400)
                return

            ticker, error = fetch_market_ticker(provider, symbol)

            if error:
                self._send_json({
                    "ok": False,
                    "provider": provider,
                    "error": error,
                    "symbol": normalize_internal_symbol(symbol),
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "provider": provider,
                "market": "usdt_perp",
                **ticker,
            })
            return

        if parsed.path in (
            "/market/instruments",
            "/providers/blofin/instruments",
        ):
            symbol = query.get("symbol", [None])[0]
            instruments, error = fetch_blofin_instruments(symbol)

            if error:
                self._send_json({
                    "ok": False,
                    "provider": "blofin",
                    "error": error,
                    "symbol": (
                        normalize_internal_symbol(symbol)
                        if symbol
                        else None
                    ),
                }, status=400)
                return

            self._send_json({
                "ok": True,
                "provider": "blofin",
                "market": "usdt_perp",
                "symbol": (
                    normalize_internal_symbol(symbol)
                    if symbol
                    else None
                ),
                "count": len(instruments),
                "instruments": instruments,
            })
            return

        self._not_found()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"{SERVICE_NAME} listening on {PORT}")
    server.serve_forever()

from api_clients import fetch_candles_from_api_gateway, ingest_candles_to_data_hub
from config import TIMEFRAMES, REFRESH_LIMIT


def refresh_symbol_candles(symbol: str):
    results = []

    for timeframe in TIMEFRAMES:
        api_payload = fetch_candles_from_api_gateway(symbol, timeframe, REFRESH_LIMIT)
        if not api_payload.get("ok"):
            results.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "ok": False,
                "stage": "api_gateway",
                "error": api_payload.get("error", "unknown_error"),
            })
            continue

        ingest_result = ingest_candles_to_data_hub(api_payload)
        if not ingest_result.get("ok"):
            results.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "ok": False,
                "stage": "data_hub",
                "error": ingest_result.get("error", "unknown_error"),
            })
            continue

        results.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "ok": True,
            "stored_rows": ingest_result.get("stored_rows"),
        })

    return results

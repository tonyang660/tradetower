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

        metadata = ingest_result.get("metadata", {})
        status = metadata.get("status", {})

        results.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "ok": True,
            "provider": ingest_result.get("provider"),
            "market": ingest_result.get("market"),
            "stored_rows": ingest_result.get("stored_rows"),
            "last_timestamp": metadata.get("last_timestamp"),
            "market_data_healthy": status.get("healthy"),
            "market_data_reason_codes": status.get("reason_codes", []),
            "market_data_last_age_seconds": status.get("last_age_seconds"),
            "market_data_gap_count": status.get("gap_count"),
        })

    return results

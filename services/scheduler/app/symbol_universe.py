import json

from config import SYMBOL_UNIVERSE_PATH


def load_symbol_universe():
    with open(SYMBOL_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    symbols = []
    for item in payload.get("symbols", []):
        if item.get("enabled", False):
            symbols.append(item["symbol"].upper())

    return symbols

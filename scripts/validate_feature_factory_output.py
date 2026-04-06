import json
import sys
from pathlib import Path
import urllib.request

from jsonschema import validate


SCHEMA_PATH = Path("schemas/market_snapshot_schema_v2.json")
FEATURE_FACTORY_URL = "http://10.0.0.40:8102/snapshot?symbol=BTCUSDT"


def main():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)

    with urllib.request.urlopen(FEATURE_FACTORY_URL) as response:
        payload = json.loads(response.read().decode("utf-8"))

    validate(instance=payload, schema=schema)
    print("OK: feature-factory live output matches market snapshot schema")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Validation failed: {e}")
        sys.exit(1)
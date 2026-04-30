from datetime import datetime, timezone


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

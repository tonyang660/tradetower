import json


def json_dumps(value):
    return json.dumps(value if value is not None else [])


def safe_float(value, default=0.0):
    if value is None:
        return default
    return float(value)


def percentile_sorted(values: list[float], q: float):
    if not values:
        return None
    if len(values) == 1:
        return values[0]

    idx = (len(values) - 1) * q
    lower = int(idx)
    upper = min(lower + 1, len(values) - 1)
    weight = idx - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def session_name_from_hour(hour_utc: int):
    # simple UTC session mapping for v1
    # Asia: 00-07
    # London: 08-12
    # New York: 13-20
    # Late/Other: 21-23
    if 0 <= hour_utc <= 7:
        return "Asia"
    if 8 <= hour_utc <= 12:
        return "London"
    if 13 <= hour_utc <= 20:
        return "New York"
    return "Late"

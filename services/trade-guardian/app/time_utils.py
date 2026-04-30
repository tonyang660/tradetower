from datetime import datetime, timezone, timedelta


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now():
    return datetime.now(timezone.utc)


def start_of_today_utc() -> datetime:
    now = utc_now()
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_week_utc() -> datetime:
    now = utc_now()
    monday = now.date() - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def next_monday_utc() -> datetime:
    sow = start_of_week_utc()
    return sow + timedelta(days=7)


def sunday_end_utc() -> datetime:
    return next_monday_utc() - timedelta(seconds=1)

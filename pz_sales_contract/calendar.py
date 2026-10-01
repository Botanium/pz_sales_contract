"""Accumulated open hours; no inferred calendar, time zone or grace unit."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def schedule(doc, holidays):
    try:
        zone = ZoneInfo(doc.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError('Enter an actual IANA business time zone') from exc
    names = [s.strip() for s in doc.business_days.split(',')]
    if not names or any(s not in DAYS for s in names) or len(names) != len(set(names)):
        raise ValueError('Business days must be distinct English weekday names separated by commas')
    # MariaDB Time values arrive as timedelta (e.g. "9:00:00") after reload.
    def as_time(value):
        hour, separator, rest = str(value).partition(':')
        return time.fromisoformat(hour.zfill(2)+separator+rest)
    opening = as_time(doc.opens_at)
    closing = as_time(doc.closes_at)
    if opening >= closing:
        raise ValueError('Opening must precede closing; split overnight schedules before using this version')
    return zone, {DAYS.index(s) for s in names}, opening, closing, set(holidays)


def add_open_hours(timestamp, hours, doc, holidays, valid_from, valid_to):
    instant = datetime.fromisoformat(timestamp)
    if instant.tzinfo is None:
        raise ValueError('Event timestamps must include an explicit UTC offset')
    zone, days, opening, closing, excluded = schedule(doc, holidays)
    current = instant.astimezone(zone)
    remaining = float(hours) * 3600
    for _ in range(370):
        day = current.date()
        if not valid_from <= day <= valid_to:
            raise ValueError('Agreed holiday calendar must cover the entire deadline calculation')
        start = datetime.combine(day, opening, zone)
        end = datetime.combine(day, closing, zone)
        if day.weekday() in days and day not in excluded:
            for boundary in [start,end]:
                roundtrip = datetime.fromtimestamp(boundary.timestamp(),zone)
                if roundtrip.replace(tzinfo=None) != boundary.replace(tzinfo=None):
                    raise ValueError('Business opening/closing falls in a nonexistent DST time; agree a valid schedule')
            # Same-ZoneInfo comparisons use wall time and ignore DST fold.
            current = current if current.timestamp() >= start.timestamp() else start
            available = max(0, end.timestamp() - current.timestamp())
            if remaining <= available:
                return datetime.fromtimestamp(current.timestamp() + remaining, zone).isoformat()
            remaining -= available
        current = datetime.combine(day + timedelta(days=1), time.min, zone)
    raise ValueError('Unable to resolve deadline inside one year of agreed business hours')

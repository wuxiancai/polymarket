from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from .config import Config
from .models import Predicate

ET = ZoneInfo("America/New_York")
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


@dataclass(frozen=True)
class ParsedMarket:
    kind: str
    threshold: Optional[int]
    period: str
    start: datetime
    end: datetime
    duration_minutes: int

    def to_predicate(self) -> Predicate:
        return Predicate(
            kind=self.kind,
            threshold=self.threshold,
            period=self.period,
            start=self.start,
            end=self.end,
            duration_minutes=self.duration_minutes,
        )


def parse_market(
    question: str,
    end_date: str,
    now: Optional[datetime] = None,
    config: Optional[Config] = None,
    asset_name: str = "Bitcoin",
) -> Optional[ParsedMarket]:
    cfg = config or Config()
    now_utc = _ensure_utc(now or datetime.now(timezone.utc))
    end = _parse_iso(end_date)
    if end is None:
        return None

    parsed = _parse_updown(question, end, asset_name)
    if parsed is None:
        parsed = _parse_threshold(question, end, now_utc, cfg, asset_name)
    if parsed is None:
        return None
    if parsed.duration_minutes < cfg.min_interval_minutes:
        return None
    return parsed


def _parse_updown(question: str, end: datetime, asset_name: str) -> Optional[ParsedMarket]:
    asset = re.escape(asset_name)
    if f"{asset_name} Up or Down" not in question:
        return None
    range_match = re.search(
        rf"{asset} Up or Down - ([A-Za-z]+) (\d{{1,2}}), "
        r"(\d{1,2})(?::(\d{2}))?([AP]M)-(\d{1,2})(?::(\d{2}))?([AP]M) ET",
        question,
    )
    if range_match:
        month_name, day, h1, m1, ap1, h2, m2, ap2 = range_match.groups()
        year = end.astimezone(ET).year
        start_et = _et_datetime(year, month_name, int(day), h1, m1, ap1)
        end_et = _et_datetime(year, month_name, int(day), h2, m2, ap2)
        if end_et <= start_et:
            end_et += timedelta(days=1)
        return _parsed("updown", None, "intraday", start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc))

    hourly_match = re.search(rf"{asset} Up or Down - ([A-Za-z]+) (\d{{1,2}}), (\d{{1,2}})([AP]M) ET", question)
    if hourly_match:
        month_name, day, hour, ap = hourly_match.groups()
        year = end.astimezone(ET).year
        start_et = _et_datetime(year, month_name, int(day), hour, None, ap)
        return _parsed("updown", None, "hour", start_et.astimezone(timezone.utc), end)
    return None


def _parse_threshold(
    question: str,
    end: datetime,
    now: datetime,
    cfg: Config,
    asset_name: str,
) -> Optional[ParsedMarket]:
    kind = None
    amount = None
    asset = re.escape(asset_name)
    reach = re.search(rf"Will {asset} (?:reach|hit) \$([0-9,]+|[0-9]+k) ", question, re.IGNORECASE)
    dip = re.search(rf"Will {asset} dip to \$([0-9,]+|[0-9]+k) ", question, re.IGNORECASE)
    if reach:
        kind = "reach"
        amount = _parse_amount(reach.group(1))
    elif dip:
        kind = "dip"
        amount = _parse_amount(dip.group(1))
    else:
        return None

    week_match = re.search(r"([A-Za-z]+) (\d{1,2})-(\d{1,2})\?", question)
    if week_match:
        month_name, start_day, end_day = week_match.groups()
        year = end.astimezone(ET).year
        start = _et_midnight(year, month_name, int(start_day)).astimezone(timezone.utc)
        finish = (_et_midnight(year, month_name, int(end_day)) + timedelta(days=1)).astimezone(timezone.utc)
        return _parsed(kind, amount, "week", start, finish)

    month_match = re.search(r"in ([A-Za-z]+)\?", question)
    if month_match:
        month_name = month_match.group(1)
        if cfg.allow_current_month_only and MONTHS[month_name.lower()] != now.astimezone(ET).month:
            return None
        year = now.astimezone(ET).year
        start = _et_midnight(year, month_name, 1)
        finish = _add_one_month(start)
        return _parsed(kind, amount, "month", start.astimezone(timezone.utc), finish.astimezone(timezone.utc))

    by_month = re.search(r"by ([A-Za-z]+) (\d{1,2})(?:, (\d{4}))?\?", question)
    if by_month:
        month_name, day, explicit_year = by_month.groups()
        now_et = now.astimezone(ET)
        year = int(explicit_year) if explicit_year else now_et.year
        month_number = MONTHS.get(month_name.lower())
        if month_number is None:
            return None
        if cfg.allow_current_month_only and (year != now_et.year or month_number != now_et.month):
            return None
        start = _et_midnight(year, month_name, 1)
        finish = (_et_midnight(year, month_name, int(day)) + timedelta(days=1)).astimezone(timezone.utc)
        period = "month" if int(day) >= 28 else "day"
        return _parsed(kind, amount, period, start.astimezone(timezone.utc), finish)

    return None


def _parsed(kind: str, threshold: Optional[int], period: str, start: datetime, end: datetime) -> ParsedMarket:
    start = _ensure_utc(start)
    end = _ensure_utc(end)
    duration = int((end - start).total_seconds() // 60)
    return ParsedMarket(kind=kind, threshold=threshold, period=period, start=start, end=end, duration_minutes=duration)


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return _ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _parse_amount(value: str) -> int:
    text = value.replace(",", "")
    if text.lower().endswith("k"):
        return int(float(text[:-1]) * 1000)
    return int(text)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _et_datetime(year: int, month_name: str, day: int, hour: str, minute: Optional[str], am_pm: str) -> datetime:
    h = int(hour) % 12
    if am_pm == "PM":
        h += 12
    return datetime(year, MONTHS[month_name.lower()], day, h, int(minute or 0), tzinfo=ET)


def _et_midnight(year: int, month_name: str, day: int) -> datetime:
    return datetime(year, MONTHS[month_name.lower()], day, 0, 0, tzinfo=ET)


def _add_one_month(value: datetime) -> datetime:
    month = value.month + 1
    year = value.year
    if month == 13:
        month = 1
        year += 1
    return datetime(year, month, 1, tzinfo=value.tzinfo)

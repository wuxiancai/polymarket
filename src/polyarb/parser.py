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
    threshold: Optional[float]
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
        parsed = _parse_threshold(question, end, now_utc, asset_name)
    if parsed is None:
        return None
    if not _accepts_market(parsed, now_utc, cfg):
        return None
    return parsed


def _parse_updown(question: str, end: datetime, asset_name: str) -> Optional[ParsedMarket]:
    asset = re.escape(asset_name)
    if f"{asset_name} Up or Down" not in question:
        return None
    daily_match = re.search(
        rf"{asset} Up or Down on ([A-Za-z]+) (\d{{1,2}})(?:, (\d{{4}}))?\?",
        question,
    )
    if daily_match:
        month_name, day, explicit_year = daily_match.groups()
        year = _year_for_question(end, month_name, int(day), explicit_year)
        start_et = _et_midnight(year, month_name, int(day))
        return _parsed("updown", None, "day", start_et.astimezone(timezone.utc), end)

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
    asset_name: str,
) -> Optional[ParsedMarket]:
    kind = None
    amount = None
    asset = re.escape(asset_name)
    amount_pattern = r"([0-9][0-9,]*(?:\.[0-9]+)?k?)"
    daily_price_match = re.search(
        rf"Will the price of {asset} be (above|below) \${amount_pattern} on "
        r"([A-Za-z]+) (\d{1,2})(?:, (\d{4}))?\?",
        question,
        re.IGNORECASE,
    )
    if daily_price_match:
        direction, amount_text, month_name, day, explicit_year = daily_price_match.groups()
        kind = "above" if direction == "above" else "below"
        amount = _parse_amount(amount_text)
        year = _year_for_question(end, month_name, int(day), explicit_year)
        start = _et_midnight(year, month_name, int(day))
        return _parsed(kind, amount, "day", start.astimezone(timezone.utc), end)

    daily_range_match = re.search(
        rf"Will the price of {asset} be between \${amount_pattern} and "
        rf"\${amount_pattern} on ([A-Za-z]+) (\d{{1,2}})(?:, (\d{{4}}))?\?",
        question,
        re.IGNORECASE,
    )
    if daily_range_match:
        low_text, _high_text, month_name, day, explicit_year = daily_range_match.groups()
        amount = _parse_amount(low_text)
        year = _year_for_question(end, month_name, int(day), explicit_year)
        start = _et_midnight(year, month_name, int(day))
        return _parsed("range", amount, "day", start.astimezone(timezone.utc), end)

    daily_hit_match = re.search(
        rf"Will {asset} (?:reach|hit) \${amount_pattern} on "
        r"([A-Za-z]+) (\d{1,2})(?:, (\d{4}))?\?",
        question,
        re.IGNORECASE,
    )
    if daily_hit_match:
        amount_text, month_name, day, explicit_year = daily_hit_match.groups()
        amount = _parse_amount(amount_text)
        year = _year_for_question(end, month_name, int(day), explicit_year)
        start = _et_midnight(year, month_name, int(day))
        return _parsed("reach", amount, "day", start.astimezone(timezone.utc), end)

    daily_dip_match = re.search(
        rf"Will {asset} dip to \${amount_pattern} on "
        r"([A-Za-z]+) (\d{1,2})(?:, (\d{4}))?\?",
        question,
        re.IGNORECASE,
    )
    if daily_dip_match:
        amount_text, month_name, day, explicit_year = daily_dip_match.groups()
        amount = _parse_amount(amount_text)
        year = _year_for_question(end, month_name, int(day), explicit_year)
        start = _et_midnight(year, month_name, int(day))
        return _parsed("dip", amount, "day", start.astimezone(timezone.utc), end)

    reach = re.search(rf"Will {asset} (?:reach|hit) \${amount_pattern} ", question, re.IGNORECASE)
    dip = re.search(rf"Will {asset} dip to \${amount_pattern} ", question, re.IGNORECASE)
    if reach:
        kind = "reach"
        amount = _parse_amount(reach.group(1))
    elif dip:
        kind = "dip"
        amount = _parse_amount(dip.group(1))
    else:
        return None

    week_match = re.search(r"([A-Za-z]+) (\d{1,2})-([A-Za-z]+) (\d{1,2})\?", question)
    if week_match:
        start_month, start_day, end_month, end_day = week_match.groups()
        year = _year_for_question(end, start_month, int(start_day))
        end_year = year + 1 if MONTHS[start_month.lower()] == 12 and MONTHS[end_month.lower()] == 1 else year
        start = _et_midnight(year, start_month, int(start_day)).astimezone(timezone.utc)
        finish = (_et_midnight(end_year, end_month, int(end_day)) + timedelta(days=1)).astimezone(timezone.utc)
        return _parsed(kind, amount, "week", start, finish)

    week_match = re.search(r"([A-Za-z]+) (\d{1,2})-(\d{1,2})\?", question)
    if week_match:
        month_name, start_day, end_day = week_match.groups()
        year = _year_for_question(end, month_name, int(start_day))
        start = _et_midnight(year, month_name, int(start_day)).astimezone(timezone.utc)
        finish = (_et_midnight(year, month_name, int(end_day)) + timedelta(days=1)).astimezone(timezone.utc)
        return _parsed(kind, amount, "week", start, finish)

    if re.search(r"in ([A-Za-z]+)\?", question):
        return None

    by_month = re.search(r"by ([A-Za-z]+) (\d{1,2})(?:, (\d{4}))?\?", question)
    if by_month:
        month_name, day, explicit_year = by_month.groups()
        now_et = now.astimezone(ET)
        year = int(explicit_year) if explicit_year else now_et.year
        month_number = MONTHS.get(month_name.lower())
        if month_number is None:
            return None
        start = _et_midnight(year, month_name, 1)
        finish = (_et_midnight(year, month_name, int(day)) + timedelta(days=1)).astimezone(timezone.utc)
        period = _by_period(month_name, int(day))
        return _parsed(kind, amount, period, start.astimezone(timezone.utc), finish)

    return None


def _accepts_market(parsed: ParsedMarket, now: datetime, cfg: Config) -> bool:
    if parsed.end <= now:
        return False
    if parsed.period in {"day", "week"}:
        return True
    if parsed.period == "month":
        return False
    if parsed.period in {"quarter", "year"}:
        if not cfg.allow_near_expiry_long_periods:
            return False
        return (parsed.end - now) < timedelta(days=cfg.near_expiry_days)
    return False


def _by_period(month_name: str, day: int) -> str:
    month_number = MONTHS[month_name.lower()]
    if month_number == 12:
        return "year"
    if (month_number, day) in {(3, 31), (6, 30), (9, 30)}:
        return "quarter"
    return "month" if day >= 28 else "day"


def _year_for_question(
    end: datetime,
    month_name: str,
    day: int,
    explicit_year: Optional[str] = None,
) -> int:
    if explicit_year:
        return int(explicit_year)
    end_et = end.astimezone(ET)
    year = end_et.year
    month_number = MONTHS[month_name.lower()]
    if month_number == 12 and end_et.month == 1:
        year -= 1
    return year


def _parsed(kind: str, threshold: Optional[float], period: str, start: datetime, end: datetime) -> ParsedMarket:
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


def _parse_amount(value: str) -> float:
    text = value.replace(",", "").lower()
    if text.endswith("k"):
        return float(text[:-1]) * 1000
    return float(text)


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

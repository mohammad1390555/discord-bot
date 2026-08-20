from __future__ import annotations

import re
from datetime import timedelta

DURATION_RE = re.compile(r"(?P<amount>\d+)\s*(?P<unit>s|sec|m|min|h|d|w)", re.I)
UNITS = {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(value: str, *, minimum: int = 1, maximum: int = 28 * 86400) -> timedelta:
    """Parse compact durations such as 30m, 2h or 1d12h."""
    value = value.replace(",", " ").strip()
    matches = list(DURATION_RE.finditer(value))
    if not matches or "".join(match.group(0) for match in matches).replace(" ", "") != value.replace(" ", ""):
        raise ValueError("Use a duration such as `30m`, `2h`, or `1d 6h`.")
    seconds = sum(int(match.group("amount")) * UNITS[match.group("unit").lower()] for match in matches)
    if not minimum <= seconds <= maximum:
        raise ValueError(f"Duration must be between {minimum} seconds and {maximum // 86400} days.")
    return timedelta(seconds=seconds)


def human_duration(seconds: int) -> str:
    parts = []
    for suffix, size in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{suffix}")
    return " ".join(parts) or "0s"

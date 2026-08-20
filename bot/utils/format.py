"""Safe user-template formatting (welcome, leave, level-up, etc.)."""
from __future__ import annotations


class _Safe(dict):
    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return "{" + key + "}"


def safe_format(template: str, **kwargs: object) -> str:
    """format() that leaves unknown ``{placeholders}`` intact instead of raising."""
    try:
        return str(template).format_map(_Safe(kwargs))
    except (ValueError, IndexError):
        return str(template)

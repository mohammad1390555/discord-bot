from __future__ import annotations

import pytest

from bot.cogs.admin import Admin
from bot.cogs.leveling import Leveling
from bot.utils.cache import LRUCache
from bot.utils.format import safe_format
from bot.utils.time import human_duration, parse_duration


def test_parse_duration_compact() -> None:
    assert parse_duration("30m").total_seconds() == 1800
    assert parse_duration("1d 6h").total_seconds() == 108000
    assert parse_duration("2h").total_seconds() == 7200


def test_parse_duration_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_duration("tomorrow")
    with pytest.raises(ValueError):
        parse_duration("0s")


def test_human_duration() -> None:
    assert human_duration(0) == "0s"
    assert human_duration(3661) == "1h 1m 1s"


def test_safe_format_keeps_unknown_placeholders() -> None:
    assert safe_format("Welcome {user} to {server}!", user="@a", server="Guild") == "Welcome @a to Guild!"
    assert safe_format("Hi {user} {unknown}", user="Sam") == "Hi Sam {unknown}"
    assert safe_format("100%") == "100%"


def test_level_formula() -> None:
    assert Leveling.level_for_xp(0) == 0
    assert Leveling.level_for_xp(100) == 1
    assert Leveling.level_for_xp(400) == 2
    assert Leveling.next_level_xp(1) == 400


def test_safe_eval_blocks_calls() -> None:
    with pytest.raises(ValueError):
        Admin._safe_expression("__import__('os')")
    with pytest.raises(ValueError):
        Admin._safe_expression("foo.bar")
    tree = Admin._safe_expression("1 + 2 * 3")
    assert eval(compile(tree, "<t>", "eval"), {"__builtins__": {}}, {}) == 7


def test_lru_evicts_oldest() -> None:
    cache: LRUCache[int, str] = LRUCache(2)
    cache[1] = "a"
    cache[2] = "b"
    cache[3] = "c"
    assert 1 not in cache
    assert cache[2] == "b"
    assert cache[3] == "c"

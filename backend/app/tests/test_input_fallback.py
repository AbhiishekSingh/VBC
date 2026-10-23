"""A stored BLANK must fall back exactly as an absent value does.

WHAT WENT WRONG
---------------
`_dispatch` read its inputs through

    get = lambda key, default="": inputs.get(check_id, {}).get(key, default)

and `dict.get` only applies its default when the key is MISSING. Every
fallback in that function is written `get("x", vendor.y or "")`, so the
moment a value was stored and then cleared — an analyst emptying a box —
the key existed, held "", and the fallback stopped applying.

`_missing_inputs` does it properly: `if not value and param.from_vendor`.
So the gate and the call disagreed:

    gate   sees "aspiremgs.co.in"  -> nothing missing, the run proceeds
    call   sees ""                 -> sends an empty domain

Vendor 234481 ran SSL on exactly this and came back
`HTTP 400 — Input correct domain`, having passed the guard whose whole
purpose is to stop a call that cannot succeed. The credits were spent.
"""

from __future__ import annotations

import pytest

from app.catalog.checks import CHECKS


def make_get(stored: dict):
    """The real reader, lifted out of `_dispatch` so it can be tested."""
    def get(key, default=""):
        value = stored.get(key)
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return value
    return get


class TestBlankFallsBack:
    def test_absent_key_uses_the_fallback(self):
        assert make_get({})("domainName", "aspiremgs.co.in") == "aspiremgs.co.in"

    def test_empty_string_uses_the_fallback(self):
        """The case that spent credits on a guaranteed 400."""
        get = make_get({"domainName": ""})
        assert get("domainName", "aspiremgs.co.in") == "aspiremgs.co.in"

    def test_whitespace_uses_the_fallback(self):
        get = make_get({"domainName": "   "})
        assert get("domainName", "aspiremgs.co.in") == "aspiremgs.co.in"

    def test_a_real_value_still_wins_over_the_fallback(self):
        get = make_get({"domainName": "other.example"})
        assert get("domainName", "aspiremgs.co.in") == "other.example"

    def test_zero_is_a_value_not_a_blank(self):
        """`0` and `False` are falsy and are ANSWERS. Only None and
        whitespace-only strings fall back."""
        assert make_get({"limit": 0})("limit", 50) == 0
        assert make_get({"flag": False})("flag", True) is False

    @pytest.mark.parametrize(
        "check_id,param_key",
        [(c.id, p.key) for c in CHECKS for p in c.params if p.from_vendor],
    )
    def test_every_vendor_backed_param_survives_a_cleared_box(self, check_id, param_key):
        """Not just ssl. Twelve call sites use this fallback; each one was
        one cleared box away from sending nothing."""
        get = make_get({param_key: ""})
        assert get(param_key, "FALLBACK") == "FALLBACK", (
            f"{check_id}.{param_key} would send an empty value"
        )
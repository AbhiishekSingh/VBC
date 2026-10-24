"""/api/providers and /health must not contradict each other.

They did. `/health` reported finagg as "sandbox" — correctly, from
`finagg_is_sandbox` — while `/api/providers` reported the same settings
as `"sandbox": false` with the note "Live. Prepaid wallet.", because the
new row simply never consulted the property.

That is the one mistake this platform exists to prevent, made by the
platform itself: a source that cannot produce real data presented as one
that can. A green run against a sandbox host is not evidence the live
path works, and an analyst reading "Live" on the selection screen has no
way to know otherwise.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _rows(settings: Settings) -> dict[str, dict]:
    """The /providers payload, built without standing up the app."""
    from app.api import routes

    # Called directly, not through FastAPI: the Depends default is a
    # marker object, so the session is passed explicitly.
    rows = routes.provider_status(session=_NoOutages())
    return {row["provider"]: row for row in rows}


class _NoOutages:
    """A session stand-in for the one query the endpoint makes."""

    def scalars(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


@pytest.fixture
def as_settings(monkeypatch):
    def apply(**over):
        from app.api import routes

        base = {
            "filesure_api_key": "fsk_live_x",
            "whoisxml_api_key": "w",
            "ecourts_api_key": "e",
            "finagg_api_key": "f",
        }
        base.update(over)
        settings = Settings(**base)
        monkeypatch.setattr(routes, "get_settings", lambda: settings)
        return settings

    return apply


class TestSandboxIsNeverCalledLive:
    def test_a_sandbox_finagg_host_is_reported_as_sandbox(self, as_settings):
        as_settings(finagg_base_url="https://sandbox.finagg.in/api")
        finagg = _rows(None)["finagg"]

        assert finagg["sandbox"] is True
        assert "Live" not in finagg["note"]
        assert "not evidence" in finagg["note"].lower()

    def test_a_live_finagg_host_is_reported_as_live(self, as_settings):
        as_settings(finagg_base_url="https://api.finagg.in/api")
        finagg = _rows(None)["finagg"]

        assert finagg["sandbox"] is False
        assert finagg["note"].startswith("Live")

    def test_a_sandbox_filesure_key_is_reported_as_sandbox(self, as_settings):
        as_settings(filesure_api_key="fsk_test_x")
        filesure = _rows(None)["filesure"]

        assert filesure["sandbox"] is True
        assert "Sandbox key" in filesure["note"]

    @pytest.mark.parametrize(
        "base_url,expected",
        [
            ("https://sandbox.finagg.in/api", "sandbox"),
            ("https://api.finagg.in/api", "live"),
        ],
    )
    def test_health_and_providers_agree_about_finagg(
        self, as_settings, monkeypatch, base_url, expected
    ):
        """The regression this file exists for.

        Two endpoints, one question — "can this source produce real
        data" — and they answered it differently for the same config.
        """
        settings = as_settings(finagg_base_url=base_url)
        health_says = (
            "sandbox"
            if settings.finagg_configured and settings.finagg_is_sandbox
            else "live"
        )
        providers_says = "sandbox" if _rows(None)["finagg"]["sandbox"] else "live"

        assert health_says == providers_says == expected


class TestEveryPaidAccountIsListed:
    def test_the_four_prepaid_accounts_all_appear(self, as_settings):
        """ecourts and finagg were missing from this endpoint entirely.

        Two live paid accounts that no screen could ask about — so no
        screen could show them as blocked either, which is the whole
        point of the outage work.
        """
        as_settings()
        assert {"filesure", "whoisxml", "ecourts", "finagg"} <= set(_rows(None))

    def test_nothing_is_blocked_when_there_are_no_outages(self, as_settings):
        as_settings()
        for name, row in _rows(None).items():
            assert row.get("blocked", False) is False, name
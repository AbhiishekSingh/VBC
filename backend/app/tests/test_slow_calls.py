"""The two eCourts calls that are documented as slow get a longer ceiling.

THE BUG THIS CLOSES. One global `http_timeout_seconds = 30.0` covered
every provider call. eCourts publishes the figures for two of its
endpoints: `order-ai` takes 10–60 seconds and `order-md` up to 300,
because each renders a document before it answers.

Giving up at thirty seconds would have been merely annoying if the
money followed the answer. It does not — eCourts bills on accepting the
request. So the charge landed, the document was discarded, and the run
recorded a timeout that reads as the provider being slow rather than us
hanging up on a call we had already paid for.

Asserted on the kwargs that reach the HTTP layer, because the defect
was never about behaviour under load: it was a number that was never
passed at all.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.providers.ecourts import EcourtsProvider


def _capture():
    """A provider that records the timeout of every request it makes."""
    seen: list[tuple[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.extensions.get("timeout")))
        return httpx.Response(200, json={"data": {
            "markdownContent": "ORDER TEXT", "pdfBase64": "", "aiAnalysis": {},
        }})

    provider = EcourtsProvider(
        settings=Settings(ecourts_api_key="eci_live_x", allow_paid_calls=True,
                          ecourts_order_paisa=150,
                          http_max_retries=1, http_backoff_base_seconds=0.001),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return provider, seen


SLOW = Settings().http_slow_timeout_seconds
NORMAL = Settings().http_timeout_seconds


class TestTheSlowCallsGetRoom:
    def test_order_md_gets_the_long_ceiling(self):
        """Documented at up to 300 seconds."""
        provider, seen = _capture()
        provider.order_markdown("MHAH010012342020", "order-1.pdf")
        url, timeout = seen[-1]
        assert "order-md" in url
        assert timeout and timeout.get("read") == SLOW

    def test_order_ai_gets_it_too(self):
        """Documented at 10–60 seconds — the top of that range is
        already past the 30s default."""
        provider, seen = _capture()
        provider.order_ai("MHAH010012342020", "order-1.pdf")
        url, timeout = seen[-1]
        assert "order-ai" in url
        assert timeout and timeout.get("read") == SLOW

    def test_the_ceiling_clears_the_documented_maximum(self):
        """310, not 300: the published figure is how long the work can
        take, so expiring at exactly the limit turns the slowest
        successful call into a failure."""
        assert SLOW > 300
        assert SLOW > NORMAL


class TestEverythingElseIsUnchanged:
    def test_an_ordinary_call_does_NOT_get_the_long_ceiling(self):
        """The long ceiling is for two endpoints, not a blanket raise.

        A provider that has genuinely stopped answering should fail
        fast; waiting five minutes on a lookup that normally takes two
        seconds would hold a synchronous run open for no reason.

        `enums` sets an even shorter ceiling of its own, which is right
        for a free reference call — the assertion is that it is nowhere
        near the slow one, not that it equals the global default.
        """
        provider, seen = _capture()
        provider.enums()
        _, timeout = seen[-1]
        read = timeout.get("read") if timeout else NORMAL
        assert read < NORMAL <= SLOW

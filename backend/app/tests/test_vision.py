"""OCR — reading text off an order that was filed as a scan.

Two eCourts orders in three come back with `markdown: null`, and the
finding read "3 order(s) retrieved · 2 could not be converted to text":
honest, and useless. The orders were in the report and unreadable.

Almost every test here is about ONE distinction, because it is the only
thing that can go badly wrong:

    text AS FILED is what the court wrote.
    text FROM OCR is a machine's reading of a picture of what the court wrote.

OCR misreads digits and names. If a report states a figure or a party name
that came from OCR, without saying so, then an audit product has asserted
something no court ever filed. So the label travels with the text from the
provider, through the runner, into the facts, onto the screen — and every
link in that chain is tested.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.config import Settings
from app.providers import factsets as fx
from app.providers.base import NotConfigured, PaidCallRefused, ProviderRejected
from app.providers.vision import PAISA_PER_PAGE, SYNC_PAGE_LIMIT, VisionProvider

PDF = b"%PDF-1.4 a scanned order\n%%EOF"


def page(text: str, *, language: str | None = None) -> dict:
    annotation: dict = {"text": text}
    if language:
        annotation["pages"] = [{"property": {"detectedLanguages": [
            {"languageCode": language, "confidence": 0.97}]}}]
    return {"fullTextAnnotation": annotation}


def provider(pages: list[dict] | None = None, *, status: int = 200,
             body: dict | None = None, paid: bool = True,
             key: str = "test-key", **extra):
    """A VisionProvider wired to a canned Vision response."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(status, json=body if body is not None
                              else {"responses": [{"responses": pages or []}]})

    settings = Settings(google_vision_api_key=key, allow_paid_calls=paid,
                        http_max_retries=1, **extra)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = VisionProvider(settings, client=client)
    p.captured = captured          # type: ignore[attr-defined]
    return p


# =====================================================================
# 1 · Reading a page
# =====================================================================

class TestReading:
    def test_the_text_comes_back(self):
        result = provider([page("IN THE HIGH COURT OF JUDICATURE AT BOMBAY")]) \
            .read_pdf(PDF)
        assert result["text"].startswith("IN THE HIGH COURT")

    def test_pages_are_joined_in_order(self):
        result = provider([page("page one"), page("page two")]).read_pdf(PDF)
        assert result["text"] == "page one\n\npage two"

    def test_the_detected_language_is_reported(self):
        """A Marathi order read correctly is still a Marathi order, and an
        English-only reader must not be handed it as though it were an
        English judgment."""
        result = provider([page("आदेश", language="mr")]).read_pdf(PDF)
        assert result["language"] == "mr"

    def test_a_page_with_no_text_is_an_answer_not_a_failure(self):
        """A signature sheet or a blank verso. Retrying it as though the
        call had failed would spend money to be told the same thing."""
        result = provider([page("")]).read_pdf(PDF)
        assert result["empty"] is True
        assert result["text"] == ""

    def test_the_pdf_is_sent_as_base64(self):
        p = provider([page("x")])
        p.read_pdf(PDF)
        sent = p.captured["json"]["requests"][0]["inputConfig"]  # type: ignore
        assert base64.b64decode(sent["content"]) == PDF
        assert sent["mimeType"] == "application/pdf"

    def test_it_asks_for_document_text_detection(self):
        """Not TEXT_DETECTION, which is tuned for a photo of a sign rather
        than a page of a judgment."""
        p = provider([page("x")])
        p.read_pdf(PDF)
        features = p.captured["json"]["requests"][0]["features"]  # type: ignore
        assert features == [{"type": "DOCUMENT_TEXT_DETECTION"}]


# =====================================================================
# 2 · Spending
# =====================================================================

class TestCost:
    def test_paid_calls_disabled_refuses_before_the_request(self):
        p = provider([page("x")], paid=False)
        with pytest.raises(PaidCallRefused):
            p.read_pdf(PDF)
        assert p.captured == {}          # nothing was sent

    def test_no_key_is_a_coverage_gap_not_an_error(self):
        """Reported as not_configured, which is NOT the same as an order
        with nothing in it."""
        with pytest.raises(NotConfigured, match="VBC_GOOGLE_VISION_API_KEY"):
            provider([page("x")], key="").read_pdf(PDF)

    def test_the_page_count_is_sent_explicitly(self):
        """Without it Vision reads the first five and bills for five,
        whatever we intended to spend."""
        p = provider([page("x")], vision_max_pages_per_document=2)
        p.read_pdf(PDF)
        assert p.captured["json"]["requests"][0]["pages"] == [1, 2]  # type: ignore

    def test_google_s_own_ceiling_is_never_exceeded(self):
        p = provider([page("x")], vision_max_pages_per_document=40)
        p.read_pdf(PDF)
        pages = p.captured["json"]["requests"][0]["pages"]  # type: ignore
        assert len(pages) == SYNC_PAGE_LIMIT

    def test_the_spend_is_recorded(self):
        p = provider([page("a"), page("b")])
        p.read_pdf(PDF)
        assert p.spend.paisa == 2 * PAISA_PER_PAGE

    def test_hitting_the_page_limit_is_reported(self):
        """So the reader is told the text stops partway through the order
        rather than assuming it is the whole thing."""
        p = provider([page("a"), page("b")], vision_max_pages_per_document=2)
        assert p.read_pdf(PDF)["truncated"] is True


# =====================================================================
# 3 · When Google says no
# =====================================================================

class TestFailure:
    def test_an_error_nested_in_a_200_is_still_an_error(self):
        """Vision reports a bad PDF this way. Reading only the status code
        would record a successful call that returned nothing — which is the
        exact shape of every parse defect in this codebase."""
        p = provider(body={"responses": [{"error": {"code": 3,
                                                    "message": "Bad image data"}}]})
        with pytest.raises(ProviderRejected, match="Bad image data"):
            p.read_pdf(PDF)

    def test_an_empty_response_array_is_reported(self):
        with pytest.raises(Exception, match="no `responses`"):
            provider(body={"responses": []}).read_pdf(PDF)

    def test_an_empty_document_is_never_sent(self):
        with pytest.raises(ValueError, match="empty"):
            provider([page("x")]).read_pdf(b"")


# =====================================================================
# 4 · The label, all the way to the screen
# =====================================================================

class TestOcrIsLabelled:
    FILED = [{"filename": "order-3.pdf", "pdf_base64": "JVBERi0K",
              "markdown": "IN THE HIGH COURT", "text_source": "filed",
              "href": "/api/documents/" + "c" * 64}]
    SCANNED = [{"filename": "order-1.pdf", "pdf_base64": "JVBERi0K",
                "markdown": "IN THE HIGH COURT", "text_source": "ocr",
                "ocr_language": "mr",
                "href": "/api/documents/" + "a" * 64}]

    def titles(self, fetched):
        return [d["title"] for d in fx.orders("X", fetched)["documents"]]

    def test_filed_text_is_called_readable_text(self):
        assert "order-3 — readable text" in self.titles(self.FILED)

    def test_ocr_text_says_it_came_off_a_scan(self):
        assert "order-1 — text read from the scan (OCR)" in self.titles(self.SCANNED)

    def test_ocr_raises_a_flag_and_names_the_risk(self):
        """Not a status. OCR quality is a fact about the EVIDENCE, and a
        parser does not get to decide a vendor is adverse because a scan
        was blurry."""
        flags = fx.orders("X", self.SCANNED)["flags"]
        flag = next(f for f in flags if "OCR" in f["label"])
        assert flag["level"] == "warn"
        assert "misreads digits and names" in flag["detail"]
        assert "quote the PDF" in flag["detail"]

    def test_the_flag_names_the_language_it_read(self):
        flag = next(f for f in fx.orders("X", self.SCANNED)["flags"]
                    if "OCR" in f["label"])
        assert "detected mr" in flag["detail"]

    def test_filed_text_raises_no_such_flag(self):
        """The guard must stay quiet on the orders that arrived as text, or
        every order in the system carries an OCR warning and the warning
        stops meaning anything."""
        assert not (fx.orders("X", self.FILED).get("flags") or [])

    def test_a_truncated_read_says_the_text_stops_partway(self):
        cut = [dict(self.SCANNED[0], ocr_truncated=True)]
        labels = [f["label"] for f in fx.orders("X", cut)["flags"]]
        assert "Only the first pages were read" in labels

    def test_an_order_ocr_could_not_read_explains_itself(self):
        blank = [{"filename": "order-2.pdf", "pdf_base64": "JVBERi0K",
                  "markdown": None,
                  "ocr_note": "read, but no text on any page — a signature "
                              "sheet or a blank page."}]
        doc = next(d for d in fx.orders("X", blank)["documents"]
                   if d["kind"] == "text")
        assert "signature sheet" in doc["excerpt"]


# =====================================================================
# 5 · The runner never loses a finding over a reading aid
# =====================================================================

class TestOcrNeverBreaksTheCheck:
    def test_ocr_is_off_unless_switched_on(self):
        """A dependency appearing must not start spending money."""
        assert Settings().vision_ocr_orders is False

    def test_the_default_page_cap_is_the_documented_ceiling(self):
        assert Settings().vision_max_pages_per_document <= SYNC_PAGE_LIMIT
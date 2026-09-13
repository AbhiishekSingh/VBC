"""Google Cloud Vision adapter — reading text off a scanned court order.

WHY THIS EXISTS
---------------
eCourts returns each order twice: as a signed PDF, and as markdown. For
roughly two orders in three the markdown comes back `null` — the order was
filed as a SCAN, and their converter had nothing to work with. The finding
then said "3 order(s) retrieved · 2 could not be converted to text", which
is honest and useless: the orders are there, in the report, unreadable.

`DOCUMENT_TEXT_DETECTION` is built for exactly that page. At $1.50 per 1,000
pages — about 13 paise — recovering an order costs a fraction of the ₹5 to
₹330 that fetching it did.

WHAT COMES BACK IS NOT WHAT THE COURT FILED
-------------------------------------------
This is the whole reason the adapter is careful. OCR output is DERIVED: a
machine's reading of an image, with the machine's mistakes in it. A digit
misread in an amount, a name misread in a party, and the report states
something no court ever wrote.

So every caller must carry that distinction through to the screen, exactly
as `courtorderai` already does for provider-generated analysis. The PDF
remains the evidence. This is a reading aid, and it is labelled as one.

WHAT THIS ADAPTER DELIBERATELY DOES NOT DO
------------------------------------------
* It does not interpret, summarise or answer questions about the text. That
  is the LLM path this project turned down on purpose: an answer that looks
  like a fact but cannot be reproduced from the stored bytes.
* It does not retry an empty result as though it were a failure. A page
  that yields no text is usually a blank page or a signature sheet, and
  saying so is a real answer.
"""

from __future__ import annotations

import base64
import logging

from app.config import Settings
from app.providers.base import (
    HttpProvider,
    NotConfigured,
    ProviderRejected,
    ProviderUnavailable,
    Spend,
)

logger = logging.getLogger(__name__)

#: The synchronous endpoint. There is an async one for large documents that
#: writes to a GCS bucket; it is not used, because it would mean standing up
#: a bucket, its lifecycle policy and its IAM to read a six-page order.
FILES_ANNOTATE_URL = "https://vision.googleapis.com/v1/files:annotate"

#: Google's own ceiling on the synchronous endpoint. Not ours to raise.
SYNC_PAGE_LIMIT = 5

#: $1.50 per 1,000 pages. Held in paisa like every other price in this
#: codebase so the spend log has one unit. At ~₹88/$ this is 13.2 paisa;
#: rounded UP, because a cost estimate that flatters itself is worse than
#: one that does not.
PAISA_PER_PAGE = 14


class VisionProvider(HttpProvider):
    """Text off an image. Nothing else."""

    name = "vision"

    def __init__(self, settings: Settings | None = None, client=None,
                 spend: Spend | None = None):
        super().__init__(settings, client)
        self.spend = spend or Spend()

    def _require_key(self) -> None:
        if not self.settings.vision_configured:
            raise NotConfigured(
                "Google Vision has no API key configured. Set "
                "VBC_GOOGLE_VISION_API_KEY. Until then a scanned order keeps "
                "its PDF and reports that no text was available — which is "
                "true, and is not the same as an order with nothing in it."
            )

    # -----------------------------------------------------------------

    def read_pdf(self, content: bytes, *, pages: int | None = None) -> dict:
        """OCR the first few pages of a PDF.

        Returns ``{"text", "pages_read", "pages_billed", "language", "empty"}``.

        `pages` caps how far in to read. The default comes from settings
        rather than this function, because "how much of a 40-page order do
        we pay to read" is a spending decision, not a parsing one.
        """
        self._require_key()
        if not content:
            raise ValueError("refusing to OCR an empty document")

        limit = min(
            pages or self.settings.vision_max_pages_per_document,
            SYNC_PAGE_LIMIT,
        )
        if limit < 1:
            raise ValueError("page limit must be at least 1")

        # Billed per page SENT, whether or not that page holds any text —
        # so the guard runs against the pages requested, before the call.
        self.guard_paid(f"vision:files:annotate ({limit}p)", limit * PAISA_PER_PAGE)

        response = self.request(
            "POST", FILES_ANNOTATE_URL,
            params={"key": self.settings.google_vision_api_key},
            json={
                "requests": [{
                    "inputConfig": {
                        "content": base64.b64encode(content).decode("ascii"),
                        "mimeType": "application/pdf",
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    # 1-indexed, and explicit: without it Vision reads the
                    # first five and bills for five regardless of what we
                    # intended to spend.
                    "pages": list(range(1, limit + 1)),
                }],
            },
        )

        payload = response.payload if isinstance(response.payload, dict) else {}
        responses = payload.get("responses") or []
        if not responses:
            raise ProviderUnavailable(
                "vision: the API answered with no `responses` array at all."
            )

        first = responses[0] if isinstance(responses[0], dict) else {}
        # A per-request error nested inside an HTTP 200. Vision reports a
        # bad PDF this way, and reading only the status code would record a
        # successful call that returned nothing.
        if isinstance(first.get("error"), dict) and first["error"].get("message"):
            raise ProviderRejected(
                f"vision: {first['error'].get('code', '?')}: "
                f"{first['error']['message']}"
            )

        pages_out = [p for p in (first.get("responses") or []) if isinstance(p, dict)]
        chunks, language = [], None
        for page in pages_out:
            annotation = page.get("fullTextAnnotation") or {}
            text = str(annotation.get("text") or "").strip()
            if text:
                chunks.append(text)
            if language is None:
                language = _language_of(annotation)

        billed = len(pages_out) or limit
        self.spend.record(f"vision:files:annotate ({billed}p)",
                          paisa=billed * PAISA_PER_PAGE)

        joined = "\n\n".join(chunks).strip()
        if not joined:
            # Not an error. A signature page, a blank verso, a stamp sheet.
            logger.info("vision: %d page(s) read, no text on any of them", billed)

        return {
            "text": joined,
            "pages_read": len(pages_out),
            "pages_billed": billed,
            "paisa": billed * PAISA_PER_PAGE,
            "language": language,
            "empty": not joined,
            "truncated": len(pages_out) >= limit,
        }


def _language_of(annotation: dict) -> str | None:
    """The dominant language Vision detected, when it is confident enough.

    Worth surfacing: a Marathi or Hindi order read correctly is still a
    Marathi order, and an English-only reader must not be shown it as
    though it were the same thing as an English judgment.
    """
    for page in annotation.get("pages") or []:
        detected = ((page.get("property") or {}).get("detectedLanguages") or [])
        for entry in detected:
            if (entry.get("confidence") or 0) >= 0.5 and entry.get("languageCode"):
                return str(entry["languageCode"])
    return None
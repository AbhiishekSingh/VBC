"""The document store — where the PDFs behind a finding actually live.

`download` and `courtorders` fetch real documents and used to record a size
and a digest and discard the bytes, so a report read "order retrieved" with
nothing to open.

Two constraints shape every test here:

* **The disk is shared.** Frappe/ERPNext, gridlines, diacare, abgip and
  steelx sit on the same volume, at ~86% of 97 GB. A missing PDF is a
  nuisance; a full disk is six other people's sites going down. So the store
  refuses before it risks that, and a refusal must never fail the check —
  the provider answered, the call was paid for, and the finding is still
  true.
* **The digest is the filename.** That is what makes storage idempotent,
  tampering self-evident, and the evidence and the pointer to it the same
  value.
"""

from __future__ import annotations

import hashlib

import pytest

from app.config import Settings
from app.services import documents as docs


@pytest.fixture
def store(tmp_path):
    return Settings(document_root=str(tmp_path))


PDF = b"%PDF-1.4 a small but entirely real document\n%%EOF"


# =====================================================================
# Writing
# =====================================================================

class TestStoring:
    def test_a_document_is_written_and_addressable(self, store, tmp_path):
        result = docs.store(PDF, settings=store)
        assert result.sha256 == hashlib.sha256(PDF).hexdigest()
        assert result.bytes == len(PDF)
        assert docs.path_for(result.sha256, store).read_bytes() == PDF

    def test_the_url_is_relative(self, store):
        """So it survives the box moving, or finally getting a domain."""
        assert docs.store(PDF, settings=store).url.startswith("/api/documents/")

    def test_the_same_bytes_are_stored_once(self, store, tmp_path):
        """Content-addressed. Re-running a check on a vendor costs no disk."""
        first = docs.store(PDF, settings=store)
        second = docs.store(PDF, settings=store)
        assert first.sha256 == second.sha256
        assert second.deduplicated is True
        assert len(list(tmp_path.rglob("*.pdf"))) == 1

    def test_different_bytes_get_different_files(self, store, tmp_path):
        docs.store(PDF, settings=store)
        docs.store(PDF + b" v2", settings=store)
        assert len(list(tmp_path.rglob("*.pdf"))) == 2

    def test_files_fan_out_rather_than_piling_into_one_directory(self, store, tmp_path):
        """A flat directory of a hundred thousand files is slow to list and
        unpleasant to back up."""
        result = docs.store(PDF, settings=store)
        assert (tmp_path / result.sha256[:2] / f"{result.sha256}.pdf").is_file()

    def test_no_partial_file_is_left_at_a_complete_name(self, store, tmp_path):
        """Written to a temp name and renamed. A crash mid-write must never
        leave a truncated file sitting at a digest that promises complete
        content — the digest would then be a lie about its own bytes."""
        docs.store(PDF, settings=store)
        assert not list(tmp_path.rglob("*.part"))


class TestRefusing:
    def test_a_full_disk_is_refused_before_the_write(self, store):
        settings = Settings(document_root=store.document_root,
                            document_min_free_bytes=10 ** 18)
        with pytest.raises(docs.DocumentStoreFull) as exc:
            docs.store(PDF, settings=settings)
        assert "free" in str(exc.value).lower()

    def test_the_refusal_says_the_finding_is_still_intact(self, store):
        settings = Settings(document_root=store.document_root,
                            document_min_free_bytes=10 ** 18)
        with pytest.raises(docs.DocumentStoreFull) as exc:
            docs.store(PDF, settings=settings)
        assert "digest and size" in str(exc.value)

    def test_nothing_is_written_when_refused(self, store, tmp_path):
        settings = Settings(document_root=store.document_root,
                            document_min_free_bytes=10 ** 18)
        with pytest.raises(docs.DocumentStoreFull):
            docs.store(PDF, settings=settings)
        assert not list(tmp_path.rglob("*.pdf"))

    def test_an_oversized_document_is_refused(self, store):
        settings = Settings(document_root=store.document_root,
                            document_max_bytes=10)
        with pytest.raises(ValueError, match="above the"):
            docs.store(PDF, settings=settings)

    def test_an_empty_document_is_never_stored(self, store):
        """An empty body is a failed fetch, not a document. Storing it would
        make a missing file look retrieved."""
        with pytest.raises(ValueError, match="empty"):
            docs.store(b"", settings=store)


# =====================================================================
# Reading back
# =====================================================================

class TestLookup:
    @pytest.mark.parametrize("evil", [
        "../../../../etc/passwd",
        "..%2f..%2fetc",
        "a" * 63,                      # too short
        "a" * 65,                      # too long
        "z" * 64,                      # right length, not hex
        "",
        None,
    ])
    def test_a_digest_that_is_not_a_digest_finds_nothing(self, evil, store):
        """The digest arrives from a URL, and `../` in a path segment is the
        oldest trick there is. Validated as 64 hex characters BEFORE it
        touches the filesystem."""
        assert docs.path_for(evil, store) is None

    def test_an_unknown_digest_finds_nothing(self, store):
        assert docs.path_for("0" * 64, store) is None

    def test_case_does_not_matter(self, store):
        result = docs.store(PDF, settings=store)
        assert docs.path_for(result.sha256.upper(), store) is not None


# =====================================================================
# What the reader actually gets
#
# Storing the bytes is half the job. A court order reached the screen as a
# 232 KB wall of base64 with a status line above it — the document was
# there, retrieved, paid for, and unreadable. Two things fix that: a link
# to the PDF, and the order as TEXT, which is the half most people want.
# =====================================================================

from app.providers import factsets as fx

ORDERS = [
    {"filename": "order-1.pdf", "markdown": None, "pdf_base64": "JVBERi0K" * 100,
     "href": "/api/documents/" + "a" * 64},
    {"filename": "order-3.pdf", "pdf_base64": "JVBERi0K" * 100,
     "markdown": "IN THE HIGH COURT OF JUDICATURE AT BOMBAY\n\n1. At the outset, "
                 "learned counsel for the petitioner seeks leave to amend.",
     "href": "/api/documents/" + "c" * 64,
     "text_href": "/api/documents/" + "d" * 64},
]


def titles(blob, kind):
    return [d["title"] for d in blob["documents"] if d["kind"] == kind]


class TestOrdersReachTheReader:
    def test_each_order_offers_its_pdf(self):
        blob = fx.orders("HCBM010380062022", ORDERS)
        assert titles(blob, "pdf") == ["order-1.pdf", "order-3.pdf"]

    def test_the_pdf_is_linked_not_inlined(self):
        """The base64 stays in `raw_response` as evidence. What the panel
        gets is a URL — 50 KB of base64 per order in the facts blob would
        arrive in the browser as unreadable text inside an already-large
        response."""
        doc = fx.orders("X", ORDERS)["documents"][0]
        assert doc["href"].startswith("/api/documents/")
        assert "JVBERi0K" not in str(doc)

    def test_the_readable_text_is_its_own_document(self):
        """Not an excerpt. Excerpts are capped at 400 characters and a court
        order is not 400 characters — a paragraph with a trailing ellipsis
        presented as "the order" is a finding that looks answered when it
        has only been sampled."""
        blob = fx.orders("X", ORDERS)
        assert "order-3 — readable text" in titles(blob, "text")
        text = next(d for d in blob["documents"]
                    if d["title"] == "order-3 — readable text")
        assert text["href"].endswith("d" * 64)

    def test_an_order_with_no_text_says_so_rather_than_going_quiet(self):
        """Two of the three orders on this case are scans the provider could
        not convert. Silence there reads as "nothing to see"; it is in fact
        "there is a PDF and you will have to open it"."""
        blob = fx.orders("X", ORDERS)
        assert "order-1 — no text available" in titles(blob, "text")
        note = next(d for d in blob["documents"]
                    if d["title"] == "order-1 — no text available")
        assert "Open the PDF above" in note["excerpt"]
        assert "href" not in note

    def test_the_extension_is_not_repeated_in_the_text_title(self):
        """The badge already says TEXT. "order-3.pdf — readable text" reads
        like a PDF that is somehow also text."""
        assert all(".pdf" not in t for t in titles(fx.orders("X", ORDERS), "text"))

    def test_an_unstored_pdf_still_appears_without_a_link(self):
        """A full disk loses the file, never the finding. The order was
        retrieved and that stays true — it just cannot be opened here."""
        blob = fx.orders("X", [{"filename": "order-9.pdf",
                                "pdf_base64": "JVBERi0K" * 10,
                                "store_note": "the disk is too close to full."}])
        pdf = blob["documents"][0]
        assert pdf["title"] == "order-9.pdf" and "href" not in pdf
        assert blob["flags"][0]["label"] == "Some orders were not retained"


class TestStoreLocation:
    def test_the_store_is_outside_the_web_root(self):
        """nginx serves `frontend/dist` directly. Documents are MCA filings
        and court orders about a named company, reached through the
        authenticated API — never by guessing a URL."""
        # The declared DEFAULT, not a live instance — the test suite
        # redirects the store to a temp directory, which would otherwise
        # make this assertion pass for the wrong reason.
        root = str(Settings.model_fields["document_root"].default).replace("\\", "/")
        assert "frontend/dist" not in root
        assert root.endswith("storage/documents")
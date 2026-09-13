"""Document storage — the PDFs behind a finding, kept rather than counted.

`download` and `courtorders` fetch real documents: filing PDFs from MCA, order
PDFs from the courts. Both used to record a size and a digest and then throw
the bytes away, so a report said "order retrieved" with nothing to open.

WHY A DIRECTORY AND NOT THE DATABASE
------------------------------------
An order PDF is ~50 KB, a filing rather more, and a busy vendor has dozens.
JSONB is the wrong home for them: every row would be read whole on any query
touching it, and `raw_response` is already the largest column in the schema.
Files go on disk; the database keeps the index.

CONTENT-ADDRESSED, AND THAT IS THE POINT
----------------------------------------
The path is the SHA-256 of the bytes. Three consequences, all of them the
ones an audit product wants:

  * The same document fetched twice is stored once. Re-running a check on a
    vendor costs no additional disk.
  * A stored file cannot be edited in place without changing its own name,
    so tampering is self-evident.
  * The digest already recorded against the finding IS the retrieval key —
    the evidence and the pointer to it are the same value.

DISK IS SHARED, AND NEARLY FULL
-------------------------------
This server also runs Frappe/ERPNext, gridlines, diacare, abgip and steelx,
and sits at ~86% of 97 GB. Filling it takes down six other people's sites,
not just this one. So every write checks free space first and refuses
rather than risking that — a missing PDF is a nuisance, a full disk on a
shared box is an outage.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: What each producer sends. Kept small and boring on purpose.
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "image": "image/jpeg",
    "text": "text/plain",
}


class DocumentStoreFull(RuntimeError):
    """Refused a write because the disk is too close to full.

    Deliberately not a ProviderError: nothing is wrong with the provider or
    the vendor. It is our own housekeeping, and it must read that way in the
    finding rather than as an adverse result.
    """


@dataclass(frozen=True)
class StoredDocument:
    sha256: str
    bytes: int
    path: str
    #: What the API serves it at. Relative so it survives a domain change.
    url: str
    deduplicated: bool = False


def _root(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return Path(settings.document_root).expanduser()


def free_bytes(settings: Settings | None = None) -> int:
    """Free space on the volume holding the store, creating it if needed."""
    root = _root(settings)
    root.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(root).free


def store(
    content: bytes, *, kind: str = "pdf", settings: Settings | None = None,
) -> StoredDocument:
    """Write bytes to the store and return how to find them again.

    Raises ``DocumentStoreFull`` rather than writing when space is short,
    and ``ValueError`` for an empty document — which is a failed fetch, not
    a document, and storing it would make a missing file look retrieved.
    """
    settings = settings or get_settings()
    if not content:
        raise ValueError("refusing to store an empty document")

    size = len(content)
    if size > settings.document_max_bytes:
        raise ValueError(
            f"document is {size:,} bytes, above the {settings.document_max_bytes:,} "
            f"limit. Raise VBC_DOCUMENT_MAX_BYTES deliberately if this is expected."
        )

    root = _root(settings)
    root.mkdir(parents=True, exist_ok=True)

    # Checked BEFORE the write, and against the file's own size, so a large
    # document cannot be the thing that tips a shared box over.
    free = shutil.disk_usage(root).free
    if free - size < settings.document_min_free_bytes:
        raise DocumentStoreFull(
            f"Not storing this document: {free / 1e9:.1f} GB free and the "
            f"floor is {settings.document_min_free_bytes / 1e9:.1f} GB. The "
            f"finding still records the document's digest and size — only "
            f"the file itself is missing. Free space or raise "
            f"VBC_DOCUMENT_MIN_FREE_BYTES."
        )

    digest = hashlib.sha256(content).hexdigest()
    # Two levels of fan-out: a flat directory of a hundred thousand files is
    # slow to list and unpleasant to back up.
    target = root / digest[:2] / f"{digest}.{kind}"
    if target.exists():
        # Same bytes, already on file. Nothing to write — and nothing lost,
        # because identical content is identical evidence.
        return StoredDocument(digest, size, str(target),
                              f"/api/documents/{digest}", deduplicated=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Written to a temporary name and renamed, so a crash mid-write can
    # never leave a truncated file sitting at a digest that promises
    # complete content.
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

    logger.info("stored document %s (%d bytes)", digest[:12], size)
    return StoredDocument(digest, size, str(target), f"/api/documents/{digest}")


def path_for(digest: str, settings: Settings | None = None) -> Path | None:
    """Locate a stored document by digest, or None.

    The digest is validated as hex before it touches the filesystem: it
    arrives from a URL, and ``../`` in a path segment is the oldest trick
    there is.
    """
    clean = str(digest or "").strip().lower()
    if len(clean) != 64 or any(c not in "0123456789abcdef" for c in clean):
        return None
    folder = _root(settings) / clean[:2]
    if not folder.is_dir():
        return None
    for candidate in folder.glob(f"{clean}.*"):
        if candidate.is_file():
            return candidate
    return None

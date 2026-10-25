"""Upload validation, text extraction, sanitization, and session-directory cleanup.

Handles reference-file intake only. Never logs file contents;
logging is limited to session id, filename hash, size, and extraction status.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from validation import FileError, SafetyRefusal, refusal_message, scan_texts

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
REFERENCES_DIR = BASE_DIR / "data" / "references"
UPLOADS_DIR = REFERENCES_DIR / "uploads"

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_FILES_PER_REQUEST = 5
MAX_TOTAL_BYTES = 25 * 1024 * 1024  # 25 MB per request
MAX_EXTRACTED_CHARS = 20_000
DEFAULT_RETENTION_HOURS = 24

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"  # .docx is a zip container


def retention_hours() -> int:
    raw = os.environ.get("SESSION_RETENTION_HOURS", str(DEFAULT_RETENTION_HOURS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_HOURS
    return value if value > 0 else DEFAULT_RETENTION_HOURS


def new_session_id() -> str:
    return uuid.uuid4().hex


def session_dir(session_id: str) -> Path:
    return UPLOADS_DIR / session_id


def _filename_hash(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8", errors="replace")).hexdigest()[:12]


def ensure_reference_dirs() -> None:
    """Create data/references (MCP root) and the uploads directory if missing."""
    REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_expired_sessions() -> int:
    """Delete upload session dirs older than the retention window. Returns count."""
    if not UPLOADS_DIR.is_dir():
        return 0
    cutoff = time.time() - retention_hours() * 3600
    removed = 0
    for entry in UPLOADS_DIR.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
                logger.info("expired upload session removed: %s", entry.name)
        except OSError:
            continue
    return removed


def delete_session(session_id: str) -> None:
    """Delete one upload session directory (used after refusals)."""
    target = session_dir(session_id)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        logger.info("upload session deleted: %s", session_id)


def _sanitize_text(text: str) -> str:
    """Strip null bytes and control characters except newline and tab."""
    return "".join(
        ch for ch in text if ch in "\n\t" or (ord(ch) >= 32 and not (0x80 <= ord(ch) <= 0x9F))
    )


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text(path: Path) -> tuple[str, bool]:
    """Extract text from a stored upload. Returns (text, truncated)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw = _extract_pdf(path)
    elif suffix == ".docx":
        raw = _extract_docx(path)
    else:
        raw = path.read_text(encoding="utf-8", errors="replace")
    text = _sanitize_text(raw)
    if len(text) > MAX_EXTRACTED_CHARS:
        return text[:MAX_EXTRACTED_CHARS], True
    return text, False


def _magic_matches(ext: str, head: bytes) -> bool:
    if ext == ".pdf":
        return head.startswith(_PDF_MAGIC)
    if ext == ".docx":
        return head.startswith(_ZIP_MAGIC)
    return True  # .txt/.md are validated by decoding


def save_and_extract_files(files: list, session_id: str) -> tuple[str, list[dict], list[str]]:
    """Validate, store, extract, and safety-scan uploaded reference files.

    ``files`` is the list of Werkzeug FileStorage parts from the request. Returns
    ``(session_id, extracted, warnings)`` where each extracted entry is
    ``{"label", "path", "text", "original_name"}``. Raises FileError on intake
    violations and SafetyRefusal (after deleting the session) on content violations.
    """
    warnings: list[str] = []
    # Browsers never send unselected file inputs, but empty parts can appear; drop them.
    files = [f for f in files if (getattr(f, "filename", "") or "").strip()]
    if not files:
        return session_id, [], warnings

    if len(files) > MAX_FILES_PER_REQUEST:
        raise FileError(
            f"Too many files: {len(files)} uploaded; at most {MAX_FILES_PER_REQUEST} "
            "are allowed per request."
        )

    ensure_reference_dirs()
    directory = session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    extracted: list[dict] = []
    try:
        for storage in files:
            original_name = os.path.basename(storage.filename or "upload")
            ext = os.path.splitext(original_name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise FileError(
                    f"File type '{ext or 'unknown'}' is not allowed. Upload only "
                    ".pdf, .docx, .txt or .md curriculum reference material."
                )
            storage.seek(0, os.SEEK_END)
            size = storage.tell()
            storage.seek(0)
            if size == 0:
                raise FileError(f"File '{original_name}' is empty.")
            if size > MAX_FILE_BYTES:
                raise FileError(
                    f"File '{original_name}' is larger than the {MAX_FILE_BYTES // (1024 * 1024)} "
                    "MB per-file limit."
                )
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise FileError("The uploaded files exceed the 25 MB total limit.")

            head = storage.read(8)
            storage.seek(0)
            if not _magic_matches(ext, head):
                raise FileError(
                    f"File '{original_name}' does not match its declared type."
                )

            stored = directory / f"{uuid.uuid4().hex}{ext}"
            storage.save(stored)
            logger.info(
                "upload stored session=%s name_hash=%s size=%d",
                session_id,
                _filename_hash(original_name),
                size,
            )

            try:
                text, truncated = extract_text(stored)
            except Exception:
                logger.info(
                    "extraction failed session=%s name_hash=%s",
                    session_id,
                    _filename_hash(original_name),
                )
                raise FileError(f"Could not read '{original_name}'. The file may be corrupted.")

            if truncated:
                warnings.append(
                    f"Text extracted from '{original_name}' was truncated at "
                    f"{MAX_EXTRACTED_CHARS} characters."
                )
            extracted.append(
                {
                    "label": f"upload:{original_name}",
                    "path": str(stored),
                    "original_name": original_name,
                    "text": text,
                }
            )
    except (FileError, SafetyRefusal):
        delete_session(session_id)
        raise
    except Exception as exc:  # defensive: never leave files behind on unexpected failure
        logger.info("upload error session=%s type=%s", session_id, type(exc).__name__)
        delete_session(session_id)
        raise FileError("Uploaded files could not be processed.") from exc

    # Safety + PII scan over extracted text; refuse (category only) and delete on hit.
    category = scan_texts(*(entry["text"] for entry in extracted))
    if category:
        delete_session(session_id)
        raise SafetyRefusal(refusal_message(category), details={"category": category})

    return session_id, extracted, warnings


def reference_text(extracted: list[dict]) -> str:
    """Concatenate extracted texts with source labels for the untrusted block."""
    parts = []
    for entry in extracted:
        parts.append(f"[{entry['label']}]\n{entry['text']}")
    return "\n\n".join(parts)

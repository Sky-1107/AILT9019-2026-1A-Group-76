"""Tests for files.py: allowlist, size limits, extraction, sanitization, PII scan."""

from __future__ import annotations

import io
import shutil

import pytest

import files
from validation import FileError, SafetyRefusal


class FakeStorage:
    """Minimal stand-in for werkzeug FileStorage."""

    def __init__(self, name: str, data: bytes):
        self.filename = name
        self._stream = io.BytesIO(data)

    def seek(self, offset, whence=0):
        return self._stream.seek(offset, whence)

    def tell(self):
        return self._stream.tell()

    def read(self, size=-1):
        return self._stream.read(size)

    def save(self, target):
        self._stream.seek(0)
        with open(target, "wb") as handle:
            shutil.copyfileobj(self._stream, handle)


def storage(name: str, data: bytes) -> FakeStorage:
    return FakeStorage(name, data)


@pytest.fixture()
def session():
    return files.new_session_id()


class TestAllowlist:
    def test_reject_exe(self, session):
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("tool.exe", b"MZ\x90\x00")], session)

    def test_reject_no_extension(self, session):
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("README", b"text")], session)

    def test_accept_txt(self, session):
        _sid, extracted, warnings = files.save_and_extract_files(
            [storage("notes.txt", b"Pure text reference.")], session
        )
        assert extracted[0]["text"] == "Pure text reference."
        assert extracted[0]["label"] == "upload:notes.txt"
        files.delete_session(session)

    def test_accept_md(self, session):
        _sid, extracted, _w = files.save_and_extract_files(
            [storage("ref.md", b"# Heading\nBody text.")], session
        )
        assert "Heading" in extracted[0]["text"]
        files.delete_session(session)

    def test_reject_empty_file(self, session):
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("empty.txt", b"")], session)

    def test_reject_oversized_file(self, session, monkeypatch):
        monkeypatch.setattr(files, "MAX_FILE_BYTES", 10)
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("big.txt", b"x" * 11)], session)

    def test_reject_too_many_files(self, session):
        storages = [storage(f"f{i}.txt", b"ok") for i in range(6)]
        with pytest.raises(FileError):
            files.save_and_extract_files(storages, session)

    def test_reject_mismatched_magic_bytes_pdf(self, session):
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("fake.pdf", b"NOT A PDF AT ALL")], session)

    def test_reject_mismatched_magic_bytes_docx(self, session):
        with pytest.raises(FileError):
            files.save_and_extract_files([storage("fake.docx", b"plain text not zip")], session)


class TestSanitization:
    def test_strips_null_and_control_chars(self):
        text = "clean\x00\x01\x02text\n\tkept"
        assert files._sanitize_text(text) == "cleantext\n\tkept"

    def test_truncates_at_cap(self, session, monkeypatch):
        monkeypatch.setattr(files, "MAX_EXTRACTED_CHARS", 10)
        _sid, extracted, warnings = files.save_and_extract_files(
            [storage("long.txt", b"x" * 50)], session
        )
        assert len(extracted[0]["text"]) == 10
        assert any("truncated" in w.lower() for w in warnings)
        files.delete_session(session)


class TestContentScan:
    def test_student_id_in_extracted_text_refuses(self, session):
        with pytest.raises(SafetyRefusal):
            files.save_and_extract_files(
                [storage("list.txt", b"student ID 01234567 for each learner")], session
            )
        assert not files.session_dir(session).exists()

    def test_roster_refuses_and_deletes(self, session):
        with pytest.raises(SafetyRefusal):
            files.save_and_extract_files(
                [storage("list.txt", b"full roster of the class")], session
            )
        assert not files.session_dir(session).exists()

    def test_refusal_message_has_no_matched_text(self, session):
        secret = "student ID 01234567"
        with pytest.raises(SafetyRefusal) as exc_info:
            files.save_and_extract_files([storage("list.txt", secret.encode())], session)
        assert secret not in exc_info.value.message


class TestCleanup:
    def test_expired_session_removed(self, session, monkeypatch):
        files.ensure_reference_dirs()
        directory = files.session_dir(session)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "f.txt").write_text("x")
        old = __import__("time").time() - 48 * 3600
        __import__("os").utime(directory, (old, old))
        removed = files.cleanup_expired_sessions()
        assert removed >= 1
        assert not directory.exists()

    def test_fresh_session_kept(self, session):
        files.ensure_reference_dirs()
        directory = files.session_dir(session)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            assert files.cleanup_expired_sessions() >= 0
            assert directory.exists()
        finally:
            files.delete_session(session)
        assert not directory.exists()

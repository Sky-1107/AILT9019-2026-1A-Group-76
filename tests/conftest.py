"""Shared fixtures. MOCK_MODE must be set before importing app.

The module-level pin makes the default suite run on the offline mock path. Live
(MOCK_MODE=0) tests opt in through the live_env fixture, which points the
provider at the in-process fake OpenAI endpoint in fake_openai_server.py — so
the live path is covered without network access or an API key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Pin the mock path via monkeypatching before app import.
_mock_patcher = pytest.MonkeyPatch()
_mock_patcher.setenv("MOCK_MODE", "1")
_mock_patcher.delenv("API_KEY", raising=False)
_mock_patcher.setenv("MCP_ENABLED", "1")

from app import app as flask_app  # noqa: E402  (import after env pinning)


@pytest.fixture()
def app():
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


BASE_PAYLOAD = {
    "topic": "Fraud detection with decision trees",
    "duration": "50 mins",
    "target_level": "1st Year Undergrad",
    "brief": (
        "Learners compare two rule-based ways to flag suspicious transactions and practise "
        "on a worked example."
    ),
}


@pytest.fixture()
def base_payload():
    return dict(BASE_PAYLOAD)


@pytest.fixture(scope="module")
def fake_provider():
    """In-process fake OpenAI-compatible SSE endpoint (loopback, ephemeral port)."""
    from tests.fake_openai_server import reset_stats, serve_in_thread

    server = serve_in_thread()
    host, port = server.server_address[:2]
    reset_stats()
    yield f"http://{host}:{port}"
    server.shutdown()


@pytest.fixture()
def live_env(monkeypatch, fake_provider):
    """Switch the app onto the live path against the fake provider.

    MCP is disabled by default to keep live tests fast (no curriculum-server
    subprocess); tests that need it re-enable it before the request.
    """
    from tests.fake_openai_server import reset_stats

    reset_stats()
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("PROVIDER", "completions")
    monkeypatch.setenv("API_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BASE_URL", f"{fake_provider}/v1")
    monkeypatch.setenv("TEMPERATURE", "0.25")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("MCP_ENABLED", "0")
    monkeypatch.setenv("MCP_REQUIRED", "0")
    monkeypatch.setenv("TIMEOUT_SECONDS", "20")
    return fake_provider

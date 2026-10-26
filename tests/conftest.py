"""Shared fixtures. MOCK_MODE must be set before importing app)."""

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

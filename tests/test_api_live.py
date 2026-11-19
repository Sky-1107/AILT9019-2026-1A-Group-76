"""Live-path (MOCK_MODE=0) API tests against the in-process fake OpenAI endpoint.

These exercise the real agent_service/pi_python code — provider construction,
SSE streaming, .pi injection, post-processing, retry, and output re-scan — with
no network access and no API key: the "provider" is tests/fake_openai_server.py
on loopback. Run them with plain `pytest -q`; they are part of the offline suite.
"""

from __future__ import annotations

import io


def payload(**overrides):
    data = {
        "topic": "Fraud detection with decision trees",
        "duration": "50",
        "target_level": "1st Year Undergrad",
        "brief": (
            "Learners compare two rule-based ways to flag suspicious transactions "
            "and practise on a worked example."
        ),
    }
    data.update(overrides)
    return data


class TestLiveHealth:
    def test_default_provider_matches_documented_configuration(
        self, live_env, monkeypatch
    ):
        from agent_service import AgentRunner

        monkeypatch.delenv("PROVIDER")
        assert AgentRunner().provider_kind == "responses"

    def test_reports_live_mode(self, client, live_env):
        body = client.get("/api/health").get_json()
        assert body["status"] == "ok"
        assert body["mode"] == "live"
        assert body["model"] == "gpt-4o-mini"
        assert body["temperature"] == 0.25
        assert body["timeout_seconds"] == 20
        assert body["max_output_tokens"] == 512
        assert "api_key" not in body
        assert "base_url" not in body


class TestLiveGeneration:
    def test_responses_provider_receives_credentials_and_custom_header(
        self, client, live_env, monkeypatch
    ):
        monkeypatch.setenv("PROVIDER", "responses")
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-header")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "ok"
        assert body["meta"]["provider"] == "openai-responses"

    def test_completions_provider_sends_custom_api_key_header(
        self, client, live_env, monkeypatch
    ):
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-header")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        assert response.get_json()["meta"]["provider"] == "openai-completions"

    def test_success_shape(self, client, live_env):
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "ok"
        plan = body["plan"]
        assert 2 <= len(plan["objectives"]) <= 5
        assert len(plan["blocks"]) == 4
        assert sum(b["minutes"] for b in plan["blocks"]) == plan["usable_minutes"]
        assert len(plan["check_questions"]) >= 4
        assert all(1 <= len(b["check_questions"]) <= 3 for b in plan["blocks"])
        assert plan["disclaimer"] in body["draft"]

    def test_meta_reports_live_provider(self, client, live_env):
        body = client.post("/api/generate", json=payload()).get_json()
        meta = body["meta"]
        assert meta["mode"] == "live"
        assert meta["provider"] == "openai-completions"
        assert meta["model"] == "gpt-4o-mini"
        assert meta["elapsed_ms"] > 0
        assert meta["mcp_connected"] is False  # live_env disables MCP for speed

    def test_gates_run_before_any_api_call(self, client, live_env, fake_provider):
        from tests.fake_openai_server import reset_stats

        reset_stats()
        safety = client.post(
            "/api/generate", json=payload(brief="Summarise student grades please.")
        )
        assert safety.status_code == 400
        assert safety.get_json()["error"]["code"] == "safety_refusal"
        feasibility = client.post(
            "/api/generate",
            json=payload(duration="15", brief="Cover 10 learning objectives."),
        )
        assert feasibility.status_code == 422
        missing = client.post("/api/generate", json={"topic": "X"})
        assert missing.status_code == 400
        # None of the refused requests may have reached the provider.
        import urllib.request, json as _json

        with urllib.request.urlopen(f"{fake_provider}/stats", timeout=5) as handle:
            counts = _json.loads(handle.read())
        assert counts == {}


class TestLiveMcp:
    def test_mcp_reader_starts_and_connects(self, client, live_env, monkeypatch):
        monkeypatch.setenv("MCP_ENABLED", "1")
        body = client.post("/api/generate", json=payload()).get_json()
        assert body["status"] == "ok"
        assert body["meta"]["mcp_connected"] is True

    def test_mcp_failure_warns_and_continues(self, client, live_env, monkeypatch):
        monkeypatch.setenv("MCP_ENABLED", "1")
        monkeypatch.setenv("MCP_REQUIRED", "0")
        # Point the config at a command that cannot exist: the reader fails to
        # start, generation must still succeed with a warning.
        import json
        from pathlib import Path

        cfg = Path(".pi/mcp.json")
        original = cfg.read_text(encoding="utf-8")
        broken = json.loads(original)
        broken["mcpServers"]["local-curriculum-reader"]["command"] = (
            "no-such-command-xyz"
        )
        cfg.write_text(json.dumps(broken), encoding="utf-8")
        try:
            response = client.post("/api/generate", json=payload())
            assert response.status_code == 200
            body = response.get_json()
            assert body["meta"]["mcp_connected"] is False
            assert any("curriculum reader" in w for w in body["warnings"])
        finally:
            cfg.write_text(original, encoding="utf-8")


class TestLiveRetryAndRescan:
    def test_corrective_retry_on_malformed_output(self, client, live_env, monkeypatch):
        from tests.fake_openai_server import reset_stats

        reset_stats()
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-retry")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "ok"
        # The first (malformed) reply plus the corrected one == two provider calls.
        import urllib.request, json as _json

        with urllib.request.urlopen(f"{live_env}/stats", timeout=5) as handle:
            counts = _json.loads(handle.read())
        assert counts.get("retry") == 2
        plan = body["plan"]
        assert len(plan["blocks"]) == 4
        assert sum(b["minutes"] for b in plan["blocks"]) == plan["usable_minutes"]

    def test_non_schema_draft_is_retried_when_questions_miss_blocks(
        self, client, live_env, monkeypatch
    ):
        # Salvage the custom headings and inline durations, then retry because
        # two questions cannot cover all four blocks as the active skill requires.
        import urllib.request, json as _json

        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-freestyle")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        body = response.get_json()
        plan = body["plan"]
        assert plan.get("parse_fallback") is not True
        assert len(plan["blocks"]) >= 3
        assert sum(b["minutes"] for b in plan["blocks"]) == plan["usable_minutes"]
        assert 2 <= len(plan["objectives"]) <= 5
        assert all(1 <= len(b["check_questions"]) <= 3 for b in plan["blocks"])
        assert plan["disclaimer"] in body["draft"]
        with urllib.request.urlopen(f"{live_env}/stats", timeout=5) as handle:
            counts = _json.loads(handle.read())
        assert counts.get("freestyle") == 2

    def test_output_rescan_refuses_boundary_crossing_draft(
        self, client, live_env, monkeypatch
    ):
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-bad")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 400
        error = response.get_json()["error"]
        assert error["code"] == "safety_refusal"
        assert error["details"].get("stage") == "generated_output"
        assert error["details"].get("category") == "accreditation"
        # The message is the fixed boundary template; it must not echo the
        # model's own draft wording. ("accredited curriculum" appears only in
        # the standing refusal sentence, never the offending draft text.)
        assert "needs no tutor review" not in error["message"]

    def test_topic_vocabulary_in_draft_is_not_refused(self, client, live_env, monkeypatch):
        # A lesson whose SUBJECT is handling student/personal data must generate
        # fine: the output re-scan flags only hard violations, not topic words.
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-topic")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"


class TestLiveUploads:
    def test_upload_wrapped_and_cited(self, client, live_env):
        response = client.post(
            "/api/generate",
            data={
                **payload(),
                "files": (io.BytesIO(b"# Week 1\nBloom verbs note."), "ref.md"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        body = response.get_json()
        labels = [source["label"] for source in body["sources"]]
        assert "upload:ref.md" in labels


class TestLiveProviderFailure:
    def test_unreachable_provider_maps_to_502(self, client, live_env, monkeypatch):
        # Port 1 on loopback refuses connections immediately (no hang).
        monkeypatch.setenv("BASE_URL", "http://127.0.0.1:1/v1")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 502
        error = response.get_json()["error"]
        assert error["code"] == "provider_error"
        assert "test-key-not-a-secret" not in error["message"]

    def test_rejected_api_key_explains_the_key_not_incomplete(
        self, client, live_env, monkeypatch
    ):
        # A provider 401 must surface as an authentication message that points at
        # API_KEY/BASE_URL, not the misleading "incomplete response" wording.
        monkeypatch.setenv("BASE_URL", f"{live_env}/v1-auth")
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 502
        error = response.get_json()["error"]
        assert error["code"] == "provider_error"
        assert "401" in error["message"]
        assert "API_KEY" in error["message"]
        assert error["details"].get("reason") == "authentication"
        assert error["details"].get("http_status") == 401
        assert "incomplete" not in error["message"].lower()
        assert "test-key-not-a-secret" not in error["message"]

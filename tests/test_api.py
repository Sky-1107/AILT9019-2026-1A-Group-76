"""API contract tests in mock mode: health, generation, refusals, uploads."""

from __future__ import annotations

import io


def payload(**overrides):
    data = {
        "topic": "Fraud detection with decision trees",
        "duration": "50 mins",
        "target_level": "1st Year Undergrad",
        "brief": (
            "Learners compare two rule-based ways to flag suspicious transactions and "
            "practise on a worked example."
        ),
    }
    data.update(overrides)
    return data


class TestHealth:
    def test_reports_mock_mode(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "ok"
        assert body["mode"] == "mock"
        assert "mcp_enabled" in body
        assert not {
            "model",
            "temperature",
            "timeout_seconds",
            "max_output_tokens",
            "api_key",
            "base_url",
        } & body.keys()


class TestPositiveGeneration:
    def test_mock_shape_and_plan(self, client):
        response = client.post("/api/generate", json=payload())
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "mock"
        assert "draft" in body and "plan" in body
        assert "sources" in body and "warnings" in body and "meta" in body

        plan = body["plan"]
        assert 2 <= len(plan["objectives"]) <= 5
        assert plan["duration_minutes"] == 50
        assert plan["usable_minutes"] == plan["duration_minutes"] - plan["buffer_minutes"]
        assert sum(b["minutes"] for b in plan["blocks"]) == plan["usable_minutes"]
        assert len(plan["blocks"]) == 4
        assert len(plan["check_questions"]) >= 4
        assert all(1 <= len(b["check_questions"]) <= 3 for b in plan["blocks"])
        assert plan["disclaimer"] == "Preliminary, non-accredited draft; tutor review required."
        assert plan["disclaimer"] in body["draft"]
        assert body["meta"]["mode"] == "mock"
        assert body["meta"]["model"] == "mock"

    def test_buffer_auto_math(self, client):
        response = client.post("/api/generate", json=payload(duration="60 mins"))
        plan = response.get_json()["plan"]
        assert plan["buffer_minutes"] == 10
        assert plan["usable_minutes"] == 50

    def test_explicit_buffer(self, client):
        response = client.post(
            "/api/generate", json=payload(buffer_preference="15")
        )
        plan = response.get_json()["plan"]
        assert plan["buffer_minutes"] == 15
        assert plan["usable_minutes"] == 35

    def test_json_and_multipart_agree(self, client):
        as_json = client.post("/api/generate", json=payload()).get_json()
        form = payload()
        as_form = client.post(
            "/api/generate",
            data=form,
            content_type="multipart/form-data",
        ).get_json()
        # Time allocation is deterministic; wording is varied per generation.
        assert [b["phase"] for b in as_json["plan"]["blocks"]] == [
            b["phase"] for b in as_form["plan"]["blocks"]
        ]
        assert [b["minutes"] for b in as_json["plan"]["blocks"]] == [
            b["minutes"] for b in as_form["plan"]["blocks"]
        ]
        assert as_json["status"] == as_form["status"] == "mock"

    def test_varies_between_calls_but_structure_is_stable(self, client):
        # Mock mode re-rolls content each call so "Regenerate" shows a fresh take.
        bodies = [
            client.post("/api/generate", json=payload()).get_json() for _ in range(4)
        ]
        assert len({body["draft"] for body in bodies}) >= 2, "expected varied mock output"
        # ...while the fixed skeleton (allocation, sections, disclaimer) holds.
        for body in bodies:
            plan = body["plan"]
            assert sum(b["minutes"] for b in plan["blocks"]) == plan["usable_minutes"]
            assert 2 <= len(plan["objectives"]) <= 5
            assert all(1 <= len(b["check_questions"]) <= 3 for b in plan["blocks"])
            assert plan["disclaimer"] in body["draft"]


class TestRefusals:
    def test_safety_refusal_400(self, client):
        response = client.post(
            "/api/generate",
            json=payload(brief="Summarise student grades for the class."),
        )
        assert response.status_code == 400
        body = response.get_json()
        assert body["error"]["code"] == "safety_refusal"
        assert "draft" not in body
        assert "student grades" not in body["error"]["message"]

    def test_reworded_grading_refusal_400(self, client):
        # Intent rules must catch paraphrases that avoid the phrase list.
        response = client.post(
            "/api/generate",
            json=payload(brief="Grade them based on their in-class performance."),
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "safety_refusal"

    def test_pii_refusal_400(self, client):
        response = client.post(
            "/api/generate",
            json=payload(brief="Email tutor@example.com with the results."),
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "safety_refusal"

    def test_feasibility_refusal_422(self, client):
        response = client.post(
            "/api/generate",
            json=payload(
                duration="15 mins",
                brief="Cover 10 learning objectives and 12 activity segments in this session.",
            ),
        )
        assert response.status_code == 422
        body = response.get_json()
        assert body["error"]["code"] == "feasibility_refusal"
        assert body["error"]["message"]

    def test_validation_error_400(self, client):
        response = client.post("/api/generate", json={"topic": "X"})
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "validation_error"

    def test_bad_duration_400(self, client):
        response = client.post("/api/generate", json=payload(duration="whole afternoon"))
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "validation_error"

    def test_api_errors_are_json_not_html(self, client):
        response = client.post(
            "/api/generate", data="not-json{{{", content_type="application/json"
        )
        assert response.status_code in (400, 500)
        assert response.get_json() is not None
        assert response.get_json()["error"]["code"] in ("validation_error", "internal_error")


class TestUploads:
    def test_md_upload_yields_sources(self, client):
        data = payload(
            topic="Bloom verbs",
            brief="Introduce Bloom taxonomy verbs for objective writing with examples.",
        )
        response = client.post(
            "/api/generate",
            data={
                **data,
                "files": (io.BytesIO(b"# Week 1\nUse Bloom verbs for objectives."), "ref.md"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "mock"
        labels = [source["label"] for source in body["sources"]]
        assert "upload:ref.md" in labels
        assert any("upload:ref.md" in line for line in body["draft"].splitlines())

    def test_exe_upload_rejected_400(self, client):
        response = client.post(
            "/api/generate",
            data={
                **payload(),
                "files": (io.BytesIO(b"MZ\x90\x00binary"), "malware.exe"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "file_error"

    def test_file_with_pii_rejected_400(self, client):
        response = client.post(
            "/api/generate",
            data={
                **payload(),
                "files": (io.BytesIO(b"student ID 01234567 Jane"), "roster.txt"),
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "safety_refusal"


class TestIndex:
    def test_renders_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"Lesson-Plan Scaffolder" in response.data

    def test_static_assets(self, client):
        assert client.get("/static/main.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200

"""Flask routes, request handling, error handlers, and JSON shaping.

Module boundaries: this file does NOT import pi_python and does NOT
construct providers — all agent work is delegated to ``agent_service``.
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import agent_service
import files
import plans
from validation import (
    FeasibilityRefusal,
    FileError,
    LessonPlanError,
    ProviderError,
    SafetyRefusal,
    ValidationError,
    check_feasibility_or_raise,
    payload_texts,
    refusal_message,
    scan_texts,
    validate_payload,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 26 * 1024 * 1024  # 25 MB uploads + form headroom

ERROR_HTTP_STATUS = {
    "validation_error": 400,
    "safety_refusal": 400,
    "file_error": 400,
    "feasibility_refusal": 422,
    "provider_error": 502,
    "internal_error": 500,
}


def error_response(code: str, message: str, details: dict | None = None):
    payload = {"error": {"code": code, "message": message, "details": details or {}}}
    return jsonify(payload), ERROR_HTTP_STATUS.get(code, 400)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Unknown API endpoint.",
                    "details": {},
                }
            }
        ), 404
    return render_template("index.html")


@app.errorhandler(405)
def method_not_allowed(_error):
    if request.path.startswith("/api/"):
        return jsonify(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Method not allowed for this endpoint.",
                    "details": {},
                }
            }
        ), 405
    return "Method not allowed", 405


@app.errorhandler(413)
def too_large(_error):
    # Mapped to file_error (400) so API clients always receive the JSON error shape.
    return jsonify(
        {
            "error": {
                "code": "file_error",
                "message": "The uploaded files exceed the 25 MB total limit.",
                "details": {},
            }
        }
    ), 400


@app.errorhandler(Exception)
def unhandled(error):  # pragma: no cover - safety net
    if isinstance(error, HTTPException):
        # Let normal HTTP errors (e.g. page 404) keep their status; API ones get JSON.
        if request.path.startswith("/api/"):
            return jsonify(
                {
                    "error": {
                        "code": "internal_error",
                        "message": error.description if isinstance(error.description, str) else "API error.",
                        "details": {},
                    }
                }
            ), error.code
        return error
    logger.error("unhandled error type=%s", type(error).__name__)
    if request.path.startswith("/api/"):
        return jsonify(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected server error occurred.",
                    "details": {},
                }
            }
        ), 500
    return "Internal server error", 500


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "mode": "mock" if agent_service.mock_mode_selected() else "live",
            "mcp_enabled": agent_service.mcp_enabled(),
        }
    )


def _request_fields() -> dict:
    """Collect string fields from either JSON (tests/scripts) or a multipart form (UI)."""
    if request.content_type and "multipart/form-data" in request.content_type:
        return {key: request.form.get(key, "") for key in request.form}
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return {key: request.form.get(key, "") for key in request.form}
    raise ValidationError("Request body must be a JSON object or form fields.")


@app.post("/api/generate")
def generate():
    files.cleanup_expired_sessions()
    session_id = files.new_session_id()
    uploaded = False
    try:
        normalized = validate_payload(_request_fields())

        _session_id, extracted, upload_warnings = files.save_and_extract_files(
            request.files.getlist("files"), session_id
        )
        uploaded = bool(extracted)

        category = scan_texts(*payload_texts(normalized))
        if category:
            raise SafetyRefusal(refusal_message(category), details={"category": category})

        duration_minutes = plans.parse_duration(normalized["duration"])
        buffer_minutes = plans.compute_buffer(duration_minutes, normalized["buffer_preference"])
        normalized["duration_minutes"] = duration_minutes
        normalized["buffer_minutes"] = buffer_minutes
        normalized["usable_minutes"] = duration_minutes - buffer_minutes
        normalized["buffer_auto"] = plans.is_auto_buffer(normalized["buffer_preference"])

        check_feasibility_or_raise(
            normalized["topic"], duration_minutes, buffer_minutes, normalized["brief"]
        )

        plan, draft, meta, status = agent_service.run_generation(normalized, extracted)
        if not plan.get("sources") and extracted:
            plan["sources"] = [
                {"label": entry["label"], "snippet": ""} for entry in extracted
            ]
        density = plans.density_flag(normalized["brief"], normalized["usable_minutes"])
        if density:
            plan.setdefault("warnings", []).append(density)
        plan["warnings"] = list(dict.fromkeys([*upload_warnings, *plan.get("warnings", [])]))
        plans.attach_extras(plan)

        # Re-scan the generated output before returning it.
        output_category = scan_texts(draft)
        if output_category:
            raise SafetyRefusal(
                refusal_message(output_category),
                details={"category": output_category, "stage": "generated_output"},
            )

        return jsonify(
            {
                "status": status,
                "draft": draft,
                "plan": plan,
                "sources": plan["sources"],
                "warnings": plan["warnings"],
                "meta": meta,
            }
        )
    except (
        ValidationError,
        SafetyRefusal,
        FileError,
        FeasibilityRefusal,
        ProviderError,
        LessonPlanError,
    ) as exc:
        if uploaded:
            files.delete_session(session_id)  # refuse => delete immediately
        if isinstance(exc, LessonPlanError) and exc.details.get("code") == "structure_error":
            return error_response("internal_error", exc.message, exc.details)
        return error_response(exc.code, exc.message, exc.details)
    except Exception:  # pragma: no cover - defensive
        logger.error("generate failed type=internal")
        if uploaded:
            files.delete_session(session_id)
        return error_response("internal_error", "An unexpected server error occurred.")
    # On success the session dir stays until the retention sweep (SESSION_RETENTION_HOURS).


# Startup: ensure the MCP reference root exists, then run the retention sweep.
files.ensure_reference_dirs()
files.cleanup_expired_sessions()


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
    )
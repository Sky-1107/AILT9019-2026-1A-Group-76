"""Payload validation, safety/PII scans, and the custom exceptions used across the app.

Responsibilities: validation and exceptions only. This module must not
import ``pi_python`` and must not touch Flask request objects.
"""

from __future__ import annotations

import re


class LessonPlanError(Exception):
    """Base class for all structured pipeline errors."""

    code = "internal_error"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(LessonPlanError):
    code = "validation_error"


class SafetyRefusal(LessonPlanError):
    code = "safety_refusal"


class FileError(LessonPlanError):
    code = "file_error"


class FeasibilityRefusal(LessonPlanError):
    code = "feasibility_refusal"


class ProviderError(LessonPlanError):
    code = "provider_error"


class AgentConfigurationError(LessonPlanError):
    """A required agent asset (e.g. SKILL.md) is missing or unusable in live mode."""

    code = "internal_error"


# ---------------------------------------------------------------------------
# Field limits
# ---------------------------------------------------------------------------

MAX_TOPIC = 200
MAX_TARGET_LEVEL = 200
MAX_BRIEF = 4000
MAX_ACTIVITY_TYPES = 500
MAX_PACING = 500
MIN_BUFFER = 0
MAX_BUFFER = 30

REQUIRED_FIELDS = ("topic", "duration", "target_level", "brief")


# ---------------------------------------------------------------------------
# Prohibited-content patterns
# ---------------------------------------------------------------------------
# Each entry maps a regex to a category NAME. The matched text is never returned.

PROHIBITED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("grading", re.compile(r"\b(?:student\s+grades?|grading)\b", re.IGNORECASE)),
    ("student_assessment", re.compile(r"\bstudent\s+assess(?:ment|ments)\b", re.IGNORECASE)),
    ("student_performance", re.compile(r"\bstudent\s+performance\b", re.IGNORECASE)),
    ("roster", re.compile(r"\brosters?\b", re.IGNORECASE)),
    ("official_assessment", re.compile(r"\bofficial\s+(?:student\s+)?assessment\b", re.IGNORECASE)),
    ("student_id", re.compile(r"\bstudent\s+ids?\b", re.IGNORECASE)),
    ("coursework_submission", re.compile(r"\bcoursework\s+submissions?\b", re.IGNORECASE)),
    ("pii", re.compile(r"\b(?:personally\s+identifiable\s+information|pii)\b", re.IGNORECASE)),
    (
        "accreditation",
        re.compile(
            r"\b(?:officially\s+)?accredited\s+(?:course|curriculum|lesson)\b"
            r"|\bofficial\s+accreditation\b",
            re.IGNORECASE,
        ),
    ),
)

# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    (
        "phone",
        # 7+ digits, tolerating separators like + (xx) xxxx xxxxx / xxx-xxxxxxx
        re.compile(r"(?=(?:\D*\d){7})\+?\d[\d\s().-]{5,}\d"),
    ),
    ("student_id", re.compile(r"\bstudent\s+id\b", re.IGNORECASE)),
    ("dob", re.compile(r"\b(?:date\s+of\s+birth|dob)\b", re.IGNORECASE)),
    ("named_grade", re.compile(r"\b(?:grade|grades|score|scores)\s+for\s+[A-Z][\w'-]+", re.M)),
)

_REFUSAL_CORE = (
    "This tool does not assess, grade, or track real student performance; does not accept "
    "student rosters, IDs, personal data, or coursework submissions; and does not certify "
    "an officially accredited curriculum."
)

_CATEGORY_HINTS = {
    "grading": "grading or assessment of students",
    "student_assessment": "student assessment records",
    "student_performance": "student performance data",
    "roster": "student rosters",
    "official_assessment": "official student assessment",
    "student_id": "student IDs",
    "coursework_submission": "coursework submissions",
    "pii": "personally identifiable information",
    "accreditation": "claims of official accreditation",
    "email": "personal contact details",
    "phone": "personal contact details",
    "dob": "dates of birth",
    "named_grade": "named student grades or scores",
}


def find_safety_violation(*texts: str) -> str | None:
    """Return the prohibited-content *category* found in the texts, never the match."""
    joined = "\n".join(text for text in texts if text)
    for category, pattern in PROHIBITED_PATTERNS:
        if pattern.search(joined):
            return category
    return None


def find_pii_violation(*texts: str) -> str | None:
    """Return the PII *category* found in the texts, never the match."""
    joined = "\n".join(text for text in texts if text)
    for category, pattern in PII_PATTERNS:
        if pattern.search(joined):
            return category
    return None


def refusal_message(category: str = "scope") -> str:
    """A refusal message that names the category only, never the matched content."""
    hint = _CATEGORY_HINTS.get(category)
    if hint:
        return f"The request touched {hint}, which is outside the scope of this tool. {_REFUSAL_CORE}"
    return _REFUSAL_CORE


def scan_texts(*texts: str) -> str | None:
    """Run prohibited-content then PII scans; return a refusal category or None."""
    category = find_safety_violation(*texts)
    if category:
        return category
    return find_pii_violation(*texts)


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------


def _clean_string(value: object, field: str, max_len: int, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"'{field}' must be a string.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"'{field}' must be a non-empty string.")
    if len(value) > max_len:
        raise ValidationError(f"'{field}' must be at most {max_len} characters.")
    return value


def validate_payload(data: dict) -> dict:
    """Validate and normalize the tutor request fields.

    Returns a dict with keys: topic, duration, target_level, brief, activity_types,
    pacing_preferences, buffer_preference (None | "auto" | int).
    Raises ValidationError on any problem.
    """
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object or form fields.")

    normalized = {
        "topic": _clean_string(data.get("topic"), "topic", MAX_TOPIC, required=True),
        "duration": _clean_string(data.get("duration"), "duration", 40, required=True),
        "target_level": _clean_string(
            data.get("target_level"), "target_level", MAX_TARGET_LEVEL, required=True
        ),
        "brief": _clean_string(data.get("brief"), "brief", MAX_BRIEF, required=True),
        "activity_types": _clean_string(
            data.get("activity_types"), "activity_types", MAX_ACTIVITY_TYPES, required=False
        ),
        "pacing_preferences": _clean_string(
            data.get("pacing_preferences"), "pacing_preferences", MAX_PACING, required=False
        ),
    }

    raw_buffer = data.get("buffer_preference")
    if raw_buffer is None or (isinstance(raw_buffer, str) and not raw_buffer.strip()):
        normalized["buffer_preference"] = None
    elif isinstance(raw_buffer, str) and raw_buffer.strip().lower() == "auto":
        normalized["buffer_preference"] = "auto"
    else:
        try:
            buffer_value = int(str(raw_buffer).strip())
        except ValueError:
            raise ValidationError(
                "'buffer_preference' must be 'auto' or an integer number of minutes."
            ) from None
        if not MIN_BUFFER <= buffer_value <= MAX_BUFFER:
            raise ValidationError(
                f"Buffer preference must be between {MIN_BUFFER} and {MAX_BUFFER} minutes."
            )
        normalized["buffer_preference"] = buffer_value

    return normalized


def payload_texts(payload: dict) -> tuple[str, ...]:
    """All user-supplied free text in a normalized payload, for safety scanning."""
    return tuple(
        value
        for key, value in payload.items()
        if key != "buffer_preference" and isinstance(value, str) and value
    )


def check_feasibility_or_raise(
    topic: str, duration_minutes: int, buffer_minutes: int, brief: str
) -> None:
    """Delegate to plans.check_feasibility and raise FeasibilityRefusal on an issue."""
    from plans import check_feasibility  # local import keeps modules acyclic

    issue = check_feasibility(topic, duration_minutes, buffer_minutes, brief)
    if issue is not None:
        raise FeasibilityRefusal(issue.message, details={"code": issue.code})

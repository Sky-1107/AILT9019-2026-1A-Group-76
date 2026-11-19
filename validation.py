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
#
# Two tiers of rules:
#  * PROHIBITED_PATTERNS — phrase rules on unambiguous vocabulary ("student
#    grades", "roster", "gradebook", "attendance register", "student records").
#    Any occurrence refuses, no exceptions.
#  * PROHIBITED_INTENT_RULES — an assessment verb (grade / assess / evaluate /
#    mark / score / rank / test / track…) within a short window of a *people*
#    object (them, students, the class) or of student-work nouns (essays,
#    scripts, exams). This catches reworded requests such as "Grade them based
#    on their in-class performance." Verbs followed by things ("evaluate two
#    candidate solutions") never match, and legitimate classroom self- and
#    peer-assessment is exempted — see _SELF_PEER_CUE / _is_learner_agent.

# "the class" only counts as people when it is not immediately a thing
# ("grade the class discussion", "rank the class activity").
_CLASS_PEOPLE = r"the\s+class\b(?!\s+(?:discussion|debate|activity|session|lesson|vote))"
_PERSON = (
    r"(?:them|students?|learners?|pupils?|" + _CLASS_PEOPLE + r"|everyone|everybody"
    r"|each\s+(?:student|learner|person|one)|all\s+(?:students|learners)|peers?"
    r"|their|his|her)"
)
_STUDENT_NOUNS = _PERSON
_STUDENT_WORK = (
    r"(?:essays?|scripts?|papers?|exams?|coursework|assignments?|homework"
    r"|worksheets?|quizzes?|tests?)"
)
_WINDOW = r"[\w\s,'\"-]{0,24}"

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
    ("grading", re.compile(r"\bgrade\s?books?\b", re.IGNORECASE)),
    (
        "attendance_tracking",
        re.compile(
            r"\b(?:attendance|marks|grades|grade)\s+(?:register|sheet|book|list|records?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "student_records",
        re.compile(
            r"\b(?:student|learner|pupil)\s+(?:records?|data|files?|profiles?)\b"
            r"|\b(?:academic|pastoral)\s+records?\b"
            r"|\breport\s+cards?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ranking",
        re.compile(
            r"\b(?:class|cohort|year)\s+rankings?\b|\bleaderboards?\b", re.IGNORECASE
        ),
    ),
    (
        "student_performance",
        re.compile(r"\b(?:in-?class|classroom)\s+performance\b", re.IGNORECASE),
    ),
)

PROHIBITED_INTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "grading",
        re.compile(
            rf"\b(?:grade|grades|graded|grading)\b{_WINDOW}\b(?:{_PERSON}|{_STUDENT_WORK})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "student_assessment",
        re.compile(
            rf"\b(?:assess|assesses|assessed|assessing)\b{_WINDOW}\b(?:{_PERSON}|{_STUDENT_WORK})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "student_assessment",
        re.compile(
            rf"\b(?:evaluat(?:e|es|ed|ing))\b{_WINDOW}\b(?:{_STUDENT_NOUNS})\b",
            re.IGNORECASE,
        ),
    ),
    (
        # "mark" is a common noun/verb outside grading contexts ("mark the key
        # terms", "landmark"), so this rule requires the *progression* forms
        # ("marking the students' essays") plus a people/work object.
        "marking",
        re.compile(
            rf"\b(?:marking|marked)\b{_WINDOW}\b(?:{_PERSON}|{_STUDENT_WORK})\b",
            re.IGNORECASE,
        ),
    ),
    (
        # Bare imperative "mark(s) their essays" — only when the work noun is
        # possessed by people, keeping "mark the key turning points" clean.
        "marking",
        re.compile(
            r"\b(?:mark|marks)\b[\w\s,'\"-]{0,12}\b(?:their|his|her|its|students?'?|learners?'?|pupils?'?)'?\s+"
            r"(?:essays?|scripts?|papers?|exams?|coursework|assignments?|homework"
            r"|worksheets?|quizzes?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "scoring",
        re.compile(
            rf"\b(?:scor(?:e|es|ed|ing))\b{_WINDOW}\b(?:{_PERSON}|{_STUDENT_WORK})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ranking",
        re.compile(
            rf"\b(?:rank|ranks|ranked|ranking)\b{_WINDOW}\b(?:{_STUDENT_NOUNS})\b",
            re.IGNORECASE,
        ),
    ),
    (
        "student_assessment",
        re.compile(
            r"\b(?:test|tests|tested|testing)\s+(?:the\s+)?(?:students?|class|learners?|pupils?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        # track/monitor/record/log + a person possessive + a tracked noun:
        # "keep a record of their attendance", "track student progress".
        # "track the lesson's progress" does not match (no person reference).
        "student_performance",
        re.compile(
            rf"\b(?:track|tracks|tracking|monitor|monitors|monitoring|record|records"
            rf"|recording|log|logs|logging)\b{_WINDOW}"
            rf"\b(?:their|his|her|students?'?|learners?'?|pupils?'?|class(?:room)?)'?\s+"
            rf"(?:performance|progress|attendance|participation|behaviour|behavior"
            rf"|absences?|marks|grades|scores)\b",
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
    "marking": "marking student work",
    "scoring": "scoring students or their work",
    "student_assessment": "student assessment records",
    "student_performance": "student performance data",
    "attendance_tracking": "attendance or mark tracking",
    "student_records": "student records",
    "ranking": "ranking or rating of students",
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


# Legitimate classroom self/peer assessment ("learners peer-assess each other's
# drafts", "students self-evaluate", "groups grade one another") is not the tool
# judging real students, so intent rules skip matches whose surrounding wording
# contains one of these cues.
_SELF_PEER_CUE = re.compile(
    r"\b(?:self|peer|mutual)[-_ ]?(?:assess|evaluat|grad|mark|scor|review|feedback|test)"
    r"|\b(?:assess|evaluat|grad|mark|scor|review|test)(?:e|es|ed|ing)?[-_ ]?(?:self|peers)"
    r"|\beach\s+other(?:'?s)?\b|\bone\s+another\b",
    re.IGNORECASE,
)


def _is_learner_agent(text: str, start: int, end: int) -> bool:
    """True when the window around an intent-rule match signals self/peer work."""
    lo = max(0, start - 30)
    hi = min(len(text), end + 15)
    return bool(_SELF_PEER_CUE.search(text, lo, hi))


def find_safety_violation(*texts: str) -> str | None:
    """Return the prohibited-content *category* found in the texts, never the match."""
    joined = "\n".join(text for text in texts if text)
    for category, pattern in PROHIBITED_PATTERNS:
        if pattern.search(joined):
            return category
    for category, pattern in PROHIBITED_INTENT_RULES:
        for match in pattern.finditer(joined):
            if _is_learner_agent(joined, match.start(), match.end()):
                continue
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
# Generated-output scan
# ---------------------------------------------------------------------------
# The full scan_texts above judges a *user's request intent*, so it is
# intentionally aggressive (broad vocabulary + verb/object intent rules). Those
# same rules misfire on generated lesson prose, where topic words such as
# "student data", "personal records" or "assess a transaction" are legitimate
# subject matter (e.g. a fraud-detection or data-privacy lesson). The output
# re-scan therefore checks only unambiguous violations that a draft must never
# contain: real PII, and a claim that the draft is an accredited curriculum.
_OUTPUT_SAFETY_CATEGORIES = ("accreditation",)
_OUTPUT_PII_CATEGORIES = ("email", "phone", "dob", "named_grade")


def scan_generated_output(*texts: str) -> str | None:
    """Return a refusal category for a *generated draft*, or None.

    Narrow by design: concrete PII leakage or an accreditation claim only, so a
    lesson about handling personal/student data is not refused for its topic.
    """
    joined = "\n".join(text for text in texts if text)
    for category, pattern in PROHIBITED_PATTERNS:
        if category in _OUTPUT_SAFETY_CATEGORIES and pattern.search(joined):
            return category
    for category, pattern in PII_PATTERNS:
        if category in _OUTPUT_PII_CATEGORIES and pattern.search(joined):
            return category
    return None


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

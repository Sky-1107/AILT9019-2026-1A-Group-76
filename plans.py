"""Duration parsing, buffer math, block allocation, and Markdown <-> plan conversion.

Pure functions only. Used by BOTH the live and mock paths so the
time math is identical everywhere. The Markdown format produced by ``plan_to_markdown``
is mirrored client-side in ``static/main.js`` (``planToMarkdown``) — keep them in sync.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from validation import ValidationError

DISCLAIMER = "Preliminary, non-accredited draft; tutor review required."

MIN_DURATION = 10
MAX_DURATION = 300
MIN_USABLE = 20
BLOCK_PHASES = ("Hook", "Core Concept", "Interactive Exercise", "Wrap-up")
PHASE_PERCENTS = {"Hook": 0.10, "Core Concept": 0.50, "Interactive Exercise": 0.30, "Wrap-up": 0.10}

BLOOM_LEVELS = (
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
)

# Common Bloom verbs mapped to their taxonomy level, used to label objectives.
_BLOOM_VERB_MAP: dict[str, str] = {
    "list": "remember",
    "recall": "remember",
    "define": "remember",
    "state": "remember",
    "describe": "understand",
    "explain": "understand",
    "summarise": "understand",
    "summarize": "understand",
    "discuss": "understand",
    "identify": "understand",
    "apply": "apply",
    "use": "apply",
    "demonstrate": "apply",
    "implement": "apply",
    "solve": "apply",
    "execute": "apply",
    "compare": "analyze",
    "contrast": "analyze",
    "analyse": "analyze",
    "analyze": "analyze",
    "differentiate": "analyze",
    "examine": "analyze",
    "evaluate": "evaluate",
    "assess": "evaluate",
    "critique": "evaluate",
    "justify": "evaluate",
    "judge": "evaluate",
    "design": "create",
    "construct": "create",
    "produce": "create",
    "develop": "create",
    "compose": "create",
    "plan": "create",
}


@dataclass(frozen=True)
class FeasibilityIssue:
    """A reason the request cannot be turned into a sane lesson plan."""

    code: str
    message: str


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)?\s*$", re.IGNORECASE
)


def parse_duration(text: str) -> int:
    """Parse a duration like ``"50"``, ``"50 mins"`` or ``"1.5 hours"`` into minutes.

    Raises ValidationError when unparseable or outside 10..300 minutes.
    """
    if not isinstance(text, str):
        raise ValidationError("Duration must be a text value such as '50 mins'.")
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise ValidationError(
            f"Could not understand the duration '{text.strip()}'. "
            "Use a value like '50', '50 mins', '1 hour', or '1.5 hours'."
        )
    value = float(match.group(1))
    unit = (match.group(2) or "mins").lower()
    multiplier = 60 if unit.startswith("h") else 1
    minutes = int(round(value * multiplier))
    if not MIN_DURATION <= minutes <= MAX_DURATION:
        raise ValidationError(
            f"Duration must be between {MIN_DURATION} and {MAX_DURATION} minutes "
            f"(got {minutes})."
        )
    return minutes


# ---------------------------------------------------------------------------
# Buffer computation
# ---------------------------------------------------------------------------


def compute_buffer(duration_minutes: int, buffer_preference: str | int | None) -> int:
    """Return buffer minutes, capped so usable time stays at least 20 minutes.

    ``None``/``"auto"`` → 5 minutes per full 30 minutes of lesson time.
    An integer 0..30 → that value. Either way the result satisfies
    ``0 <= buffer <= duration - 20``.
    """
    max_allowed = max(0, duration_minutes - MIN_USABLE)
    if buffer_preference is None or (
        isinstance(buffer_preference, str) and buffer_preference.strip().lower() == "auto"
    ):
        buffer = 5 * (duration_minutes // 30)
    else:
        buffer = int(buffer_preference)
    return max(0, min(buffer, max_allowed))


def is_auto_buffer(buffer_preference: str | int | None) -> bool:
    return buffer_preference is None or (
        isinstance(buffer_preference, str) and buffer_preference.strip().lower() == "auto"
    )


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


def _round_to_nearest_5(value: float) -> int:
    return max(5, int(math.floor(value / 5 + 0.5)) * 5)


def allocate_blocks(usable_minutes: int) -> list[dict]:
    """Split usable minutes into Hook/Core/Interactive/Wrap-up blocks.

    Each non-core block is rounded to the nearest 5 (minimum 5); Core Concept absorbs
    the remainder so the blocks always sum exactly to ``usable_minutes``.
    """
    if usable_minutes < MIN_USABLE:
        raise ValidationError("Usable lesson time is too short to allocate blocks.")
    others = {}
    for phase in BLOCK_PHASES:
        if phase == "Core Concept":
            continue
        raw = usable_minutes * PHASE_PERCENTS[phase]
        others[phase] = _round_to_nearest_5(raw)
    # Core must keep at least 5 minutes; shrink the largest satellite blocks first.
    core = usable_minutes - sum(others.values())
    while core < 5:
        largest = max(others, key=lambda p: others[p])
        if others[largest] <= 5:
            break
        others[largest] -= 5
        core += 5
    order = []
    for phase in BLOCK_PHASES:
        minutes = core if phase == "Core Concept" else others[phase]
        order.append({"phase": phase, "minutes": minutes})
    for index, block in enumerate(order, start=1):
        block["id"] = f"B{index}"
    return order


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------

_OBJECTIVE_COUNT_RE = re.compile(
    r"\b(\d{1,3})\b[\w\s,-]{0,20}?\b(?:learning\s+)?objectives?\b", re.IGNORECASE
)
_SEGMENT_COUNT_RE = re.compile(
    r"\b(\d{1,3})\b[\w\s,-]{0,20}?\b(?:activity\s+)?(?:segments?|sections?|stages?|parts?|activities|blocks)\b",
    re.IGNORECASE,
)
MAX_OBJECTIVES_REQUESTED = 8
MAX_SEGMENTS_REQUESTED = 10


def _count_requested(pattern: re.Pattern[str], text: str) -> int:
    counts = [int(m.group(1)) for m in pattern.finditer(text or "")]
    return max(counts, default=0)


def requested_objective_count(brief: str) -> int:
    """How many objectives the brief explicitly asks for (0 when unstated)."""
    return _count_requested(_OBJECTIVE_COUNT_RE, brief)


def density_flag(brief: str, usable_minutes: int) -> str | None:
    """Soft warning (not a refusal) for briefs that are dense but still feasible."""
    objectives = requested_objective_count(brief)
    if 6 <= objectives <= MAX_OBJECTIVES_REQUESTED:
        minutes_each = usable_minutes / objectives
        return (
            f"Density flag: {objectives} objectives in {usable_minutes} usable minutes "
            f"(~{minutes_each:.0f} min each, including intro and wrap-up). Suggested "
            "adjustment: merge related objectives or extend the session."
        )
    if usable_minutes >= 20 and len((brief or "").strip()) > 3200:
        return (
            "Density flag: the brief is very detailed for the usable time. Suggested "
            "adjustment: prioritise 2-3 focus points and move the rest to pre-class reading."
        )
    return None


def check_feasibility(
    topic: str,
    duration_minutes: int,
    buffer_minutes: int,
    brief: str,
    objectives_hint: int | None = None,
) -> FeasibilityIssue | None:
    """Return a FeasibilityIssue when the brief cannot honestly fit the duration."""
    if not (brief or "").strip():
        return FeasibilityIssue(
            "empty_brief", "The topic brief is empty; please describe what to teach."
        )
    if not isinstance(duration_minutes, int) or not (
        MIN_DURATION <= duration_minutes <= MAX_DURATION
    ):
        return FeasibilityIssue(
            "invalid_duration",
            f"Duration must be between {MIN_DURATION} and {MAX_DURATION} minutes.",
        )
    usable = duration_minutes - buffer_minutes
    if usable < MIN_USABLE:
        return FeasibilityIssue(
            "too_short",
            f"After the buffer, only {usable} minutes of teaching time remain, which is below "
            f"the {MIN_USABLE}-minute minimum for a workable plan. Reduce the buffer or "
            "extend the session.",
        )
    objectives = objectives_hint or _count_requested(_OBJECTIVE_COUNT_RE, brief)
    if objectives > MAX_OBJECTIVES_REQUESTED:
        return FeasibilityIssue(
            "too_many_objectives",
            f"The brief asks for {objectives} learning objectives, but a session of this "
            f"length supports at most {MAX_OBJECTIVES_REQUESTED}. Narrow the objectives "
            "or lengthen the lesson.",
        )
    segments = _count_requested(_SEGMENT_COUNT_RE, brief)
    if segments > MAX_SEGMENTS_REQUESTED:
        return FeasibilityIssue(
            "too_many_segments",
            f"The brief asks for {segments} timed activity segments, which exceeds the "
            f"practical maximum of {MAX_SEGMENTS_REQUESTED} for {usable} usable minutes.",
        )
    return None


# ---------------------------------------------------------------------------
# Structured plan helpers
# ---------------------------------------------------------------------------


PRE_CLASS_CHECKLIST = [
    "Confirm room and any software/hardware the activities need.",
    "Prepare the worked example and one alternate example for early finishers.",
    "Decide how you will group learners for the interactive block.",
    "Note where you will cut a phase if discussion overruns (the buffer is your safety net).",
    "Review the check-questions and adapt wording to your class context.",
]


def attach_extras(plan: dict) -> dict:
    """Add the pre-class tutor checklist (should-have) to a finalized plan."""
    plan["checklist"] = list(PRE_CLASS_CHECKLIST)
    return plan


def make_plan_skeleton(
    topic: str,
    duration_minutes: int,
    buffer_minutes: int,
    objectives: list[dict],
    blocks: list[dict],
    check_questions: list[str],
    sources: list[dict] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Assemble the canonical structured-plan dict."""
    return {
        "topic": topic,
        "duration_minutes": duration_minutes,
        "buffer_minutes": buffer_minutes,
        "usable_minutes": duration_minutes - buffer_minutes,
        "objectives": objectives,
        "blocks": blocks,
        "check_questions": check_questions,
        "sources": sources or [],
        "warnings": warnings or [],
        "disclaimer": DISCLAIMER,
    }


def label_bloom(text: str) -> str:
    """Best-effort Bloom level for an objective sentence, from its leading verb."""
    words = re.findall(r"[A-Za-z]+", text or "")
    for word in words[:3]:
        level = _BLOOM_VERB_MAP.get(word.lower())
        if level:
            return level
    return "understand"


# ---------------------------------------------------------------------------
# Post-generation validation
# ---------------------------------------------------------------------------


def validate_generated_plan(plan: dict) -> list[str]:
    """Return warning strings for structural problems in a generated plan."""
    warnings: list[str] = []
    objectives = plan.get("objectives") or []
    if len(objectives) < 2:
        warnings.append("The draft has fewer than 2 learning objectives.")
    elif len(objectives) > 5:
        warnings.append("The draft has more than 5 learning objectives.")
    blocks = plan.get("blocks") or []
    usable = plan.get("usable_minutes")
    if not blocks:
        warnings.append("The draft has no time-allocation blocks.")
    elif isinstance(usable, int) and sum(b.get("minutes", 0) for b in blocks) != usable:
        warnings.append(
            "Block minutes do not sum to the usable time; the allocation was repaired "
            "against the Core Concept block."
        )
    if not plan.get("check_questions"):
        warnings.append("The draft has no tutor check-questions.")
    if plan.get("disclaimer") != DISCLAIMER:
        warnings.append("The draft was missing the required disclaimer and it was re-added.")
    if plan.get("sources_expected") and not plan.get("sources"):
        warnings.append("Reference material was supplied but the draft cites no sources.")
    return warnings


def repair_block_minutes(plan: dict) -> bool:
    """Adjust the Core Concept block once so blocks sum to usable time. Return success."""
    blocks = plan.get("blocks") or []
    usable = plan.get("usable_minutes")
    if not blocks or not isinstance(usable, int) or usable < len(blocks) * 5:
        return False
    total = sum(b.get("minutes", 0) for b in blocks)
    if total == usable:
        return True
    for block in blocks:
        if block.get("phase") == "Core Concept":
            block["minutes"] = block.get("minutes", 0) + (usable - total)
            return block["minutes"] >= 5
    return False


# ---------------------------------------------------------------------------
# Markdown <-> plan
# ---------------------------------------------------------------------------

_OBJECTIVE_LINE_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])\s*(?:\*\*)?(?:(LO\d+)\s*[:.)]\s*)?(?:\*\*)?(.+)$"
)
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_CHECK_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$")


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in _TABLE_ROW_RE.match(line).group(1).split("|")]


def _is_separator_row(line: str) -> bool:
    if not _TABLE_ROW_RE.match(line):
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell or "-") for cell in cells)


def _heading_level(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,4})\s+(.*)$", line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    return None


def parse_markdown_to_plan(markdown: str, meta: dict) -> dict:
    """Reconstruct the structured plan from the agent's Markdown draft.

    ``meta`` supplies the authoritative inputs: topic, duration_minutes, buffer_minutes,
    usable_minutes and source labels. Missing pieces fall back to meta or safe defaults;
    the raw markdown is always preserved by the caller.
    """
    topic = meta.get("topic", "")
    duration = meta.get("duration_minutes", 0)
    buffer = meta.get("buffer_minutes", 0)

    objectives: list[dict] = []
    blocks: list[dict] = []
    outline: list[str] = []
    check_questions: list[str] = []
    sources: list[dict] = []
    section = ""

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()
        heading = _heading_level(line)
        if heading:
            level, title = heading
            lowered = title.lower()
            if level == 2:
                if "learning objective" in lowered:
                    section = "objectives"
                elif "time allocation" in lowered:
                    section = "time"
                elif "lesson outline" in lowered:
                    section = "outline"
                elif "check-question" in lowered:
                    section = "questions"
                elif lowered.startswith("sources"):
                    section = "sources"
                else:
                    section = "other"
                continue
            if level == 3 and section == "outline":
                outline.append(f"### {title}")
                continue
            if level == 1:
                if not topic:
                    topic = re.sub(r"^Lesson Plan Draft:\s*", "", title).strip()
                continue
            if section == "outline":
                outline.append(f"#### {title}")
                continue
            continue

        if section == "time":
            if _TABLE_ROW_RE.match(line):
                if _is_separator_row(line):
                    continue
                cells = _split_table_row(line)
                if cells and cells[0].lower() in {"phase", "phase name"}:
                    continue
                minutes_match = re.search(r"\d+", cells[1] if len(cells) > 1 else "")
                if minutes_match and cells[0]:
                    blocks.append(
                        {
                            "id": f"B{len(blocks) + 1}",
                            "phase": cells[0].strip(),
                            "minutes": int(minutes_match.group()),
                            "tutor_focus": cells[2].strip() if len(cells) > 2 else "",
                            "check_questions": [],
                        }
                    )
                continue
            continue

        if section == "objectives":
            match = _OBJECTIVE_LINE_RE.match(line)
            if match:
                lo_id, text = match.group(1), match.group(2).strip()
                text = re.sub(r"\((?:bloom|level):?\s*([a-z]+)\)\s*$", "", text, flags=re.I).strip()
                bloom_match = re.search(r"\((?:bloom|level):?\s*([a-z]+)\)\s*$", line, re.I)
                bloom = (
                    bloom_match.group(1).lower()
                    if bloom_match
                    else label_bloom(text)
                )
                objectives.append(
                    {
                        "id": lo_id or f"LO{len(objectives) + 1}",
                        "text": text,
                        "bloom": bloom if bloom in BLOOM_LEVELS else label_bloom(text),
                    }
                )
            continue

        if section == "questions":
            match = _CHECK_RE.match(line)
            if match:
                check_questions.append(match.group(1).strip())
            continue

        if section == "outline":
            if line.strip():
                outline.append(line)
            continue

        if section == "sources":
            match = _CHECK_RE.match(line)
            if match:
                body = match.group(1).strip()
                if re.match(r"^(upload|mcp):", body):
                    sources.append({"label": body, "snippet": ""})
                elif ":" in body:
                    label, snippet = body.split(":", 1)
                    sources.append({"label": label.strip(), "snippet": snippet.strip()})
                else:
                    sources.append({"label": body, "snippet": ""})
            continue

    # Distribute check questions across blocks at transition points (1-3 each).
    if blocks and check_questions:
        per_block = max(1, min(3, len(check_questions) // len(blocks)))
        index = 0
        for block in blocks:
            take = min(per_block, max(1, len(check_questions) - index))
            block["check_questions"] = check_questions[index : index + take]
            index += take

    plan = make_plan_skeleton(
        topic=topic,
        duration_minutes=duration,
        buffer_minutes=buffer,
        objectives=objectives,
        blocks=blocks,
        check_questions=check_questions,
        sources=sources,
    )
    plan["outline_markdown"] = "\n".join(outline).strip()
    plan["sources_expected"] = bool(meta.get("source_labels"))
    if not plan["sources"] and meta.get("source_labels"):
        plan["sources"] = [{"label": label, "snippet": ""} for label in meta["source_labels"]]
    return plan


def plan_to_markdown(plan: dict) -> str:
    """Render the structured plan back to the canonical Markdown format.

    Keep this in sync with ``planToMarkdown`` in ``static/main.js``.
    """
    lines: list[str] = [f"# Lesson Plan Draft: {plan.get('topic', 'Untitled')}", ""]
    lines.append("## Learning Objectives")
    lines.append("")
    for objective in plan.get("objectives", []):
        lines.append(
            f"- {objective.get('id', 'LO')}: {objective.get('text', '').strip()} "
            f"(bloom: {objective.get('bloom', 'understand')})"
        )
    lines.append("")
    lines.append("## Time Allocation")
    lines.append("")
    lines.append("| Phase | Minutes | Tutor focus |")
    lines.append("| --- | ---: | --- |")
    for block in plan.get("blocks", []):
        lines.append(
            f"| {block.get('phase', '')} | {block.get('minutes', 0)} | "
            f"{block.get('tutor_focus', '').strip()} |"
        )
    lines.append("")
    auto_note = " (auto: 5 minutes per 30 minutes of lesson)" if plan.get("buffer_auto") else ""
    lines.append(
        f"Buffer: {plan.get('buffer_minutes', 0)} minutes reserved{auto_note}. "
        f"Usable teaching time: {plan.get('usable_minutes', 0)} of "
        f"{plan.get('duration_minutes', 0)} minutes."
    )
    lines.append("")
    lines.append("## Lesson Outline")
    lines.append("")
    outline = plan.get("outline_markdown")
    if outline:
        lines.append(outline)
        lines.append("")
    else:
        for block in plan.get("blocks", []):
            lines.append(f"### {block.get('phase', '')} ({block.get('minutes', 0)} min)")
            lines.append("")
            focus = block.get("tutor_focus", "").strip()
            if focus:
                lines.append(focus)
                lines.append("")
            for question in block.get("check_questions", []) or []:
                lines.append(f"- Check: {question}")
            if block.get("check_questions"):
                lines.append("")
    lines.append("## Tutor Check-Questions")
    lines.append("")
    for question in plan.get("check_questions", []):
        lines.append(f"- {question}")
    if plan.get("sources"):
        lines.append("")
        lines.append("## Sources")
        lines.append("")
        for source in plan["sources"]:
            snippet = (source.get("snippet") or "").strip()
            if snippet:
                lines.append(f"- {source.get('label', '')}: {snippet}")
            else:
                lines.append(f"- {source.get('label', '')}")
    lines.append("")
    lines.append(plan.get("disclaimer") or DISCLAIMER)
    lines.append("")
    return "\n".join(lines)

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
    elif len(blocks) != 4:
        warnings.append("The draft does not contain the required four time-allocation blocks.")
    if blocks and isinstance(usable, int) and sum(
        b.get("minutes", 0) for b in blocks
    ) != usable:
        warnings.append(
            "Block minutes do not sum to the usable time; the allocation was repaired "
            "against the Core Concept block."
        )
    if blocks and any(not block.get("check_questions") for block in blocks):
        warnings.append(
            "One or more time-allocation blocks have no tutor check-question."
        )
    if any(len(block.get("check_questions") or []) > 3 for block in blocks):
        warnings.append(
            "One or more time-allocation blocks have more than 3 tutor check-questions."
        )
    if not plan.get("check_questions"):
        warnings.append("The draft has no tutor check-questions.")
    if plan.get("disclaimer") != DISCLAIMER:
        warnings.append("The draft was missing the required disclaimer and it was re-added.")
    if plan.get("sources_expected") and not plan.get("sources"):
        warnings.append("Reference material was supplied but the draft cites no sources.")
    return warnings


def repair_block_minutes(plan: dict) -> bool:
    """Adjust one block once so blocks sum to usable time. Return success.

    The absorbing block is the core/teaching phase when a model used its own
    phase names ("Starter", "Explanation", "Plenary"), else the largest block,
    so a non-standard table is still repairable instead of failing to fallback.
    """
    blocks = plan.get("blocks") or []
    usable = plan.get("usable_minutes")
    if not blocks or not isinstance(usable, int) or usable < len(blocks) * 5:
        return False
    total = sum(b.get("minutes", 0) for b in blocks)
    if total == usable:
        return True
    core = None
    for block in blocks:
        if re.search(r"core|concept|main|teach|explain|develop", str(block.get("phase", "")), re.I):
            core = block
            break
    target = core or max(blocks, key=lambda b: b.get("minutes", 0))
    target["minutes"] = target.get("minutes", 0) + (usable - total)
    return target["minutes"] >= 5


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


_LIST_START_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_WRAP_QUOTES = "\"\u201c\u201d\u2018\u2019'`"


def _clean_item(text: str) -> str:
    """Trim markdown emphasis and a single pair of wrapping quotes from an item."""
    text = text.strip().strip("*_` ").strip()
    if len(text) >= 2 and text[0] in _WRAP_QUOTES and text[-1] in _WRAP_QUOTES:
        text = text[1:-1].strip()
    return text
_UNFOLDABLE_RE = re.compile(
    r"^\s*(?:#|\||<<<|>\s|UNTRUSTED_REFERENCE_MATERIAL|---|\[)"  # headings, tables, fences, links
)


def _fold_wrapped_lines(lines: list[str]) -> list[str]:
    """Join soft-wrapped list items into one logical line.

    Models frequently wrap a long objective or check-question across several
    physical lines. Without folding, the parser reads only the first line and
    drops the rest, producing truncated text such as a question that ends on a
    dangling word ("...same leaf? Say"). A non-blank line that is not itself a
    heading/table/list/delimiter, and directly follows a list item, is a
    continuation and is appended to that item separated by a single space.
    """
    folded: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if (
            folded
            and stripped
            and _LIST_START_RE.match(folded[-1])
            and not _LIST_START_RE.match(line)
            and not _UNFOLDABLE_RE.match(line)
        ):
            folded[-1] = f"{folded[-1].rstrip()} {stripped}"
            continue
        folded.append(line)
    return folded


# Durations written inline rather than in a table: "**Time:** 5 minutes",
# "(10 min)", "Duration: 8 mins", "5m". Used by the salvage parser.
_INLINE_TIME_RE = re.compile(
    r"(?:\*\*|\b)?(?:time|duration|length|mins?|minutes?)\b[^\d]{0,4}(\d{1,3})\s*"
    r"(?:min(?:ute)?s?|m\b)",
    re.IGNORECASE,
)
_PAREN_TIME_RE = re.compile(r"\(\s*(\d{1,3})\s*(?:min(?:ute)?s?|m)\s*\)", re.IGNORECASE)


_META_PHASE_RE = re.compile(r"\b(?:buffer|total)\b", re.IGNORECASE)


def _is_meta_phase(name: str) -> bool:
    """True for rows/phases that reserve or total time rather than teach it."""
    return bool(_META_PHASE_RE.search(name or ""))


def _phase_from_heading(title: str) -> str:
    """Strip leading numbering ('1. Starter') and trailing emphasis from a heading."""
    cleaned = re.sub(r"^\s*\d+[.)\-]\s*", "", title)
    cleaned = re.sub(r"[*_`]+$", "", cleaned).strip(" :")
    return cleaned


def _salvage_blocks(markdown: str) -> list[dict]:
    """Recover timed blocks when the draft has no '## Time Allocation' table.

    Tracks the nearest preceding heading as the phase name and takes the first
    inline/parenthetical duration under it. This is what lets a model that invents
    its own schema ('## 1. Starter Activity' + '**Time:** 5 minutes') still parse.
    """
    blocks: list[dict] = []
    phase = ""
    seen_phases: set[str] = set()
    total_re = re.compile(r"^\s*\*{0,2}(?:total\s+)?duration\b", re.IGNORECASE)
    for raw_line in _fold_wrapped_lines(markdown.splitlines()):
        line = raw_line.strip()
        heading = _heading_level(line)
        if heading:
            # Only top-level headings name phases; deeper headings ("### Teacher
            # Action") must not steal the attribution of their parent's time.
            if heading[0] <= 2:
                phase = _phase_from_heading(heading[1])
            continue
        if not phase or phase.lower() in seen_phases:
            continue
        if total_re.match(line):
            continue  # the overall lesson duration, not a block
        match = _INLINE_TIME_RE.search(line) or _PAREN_TIME_RE.search(line)
        if not match:
            continue
        minutes = int(match.group(1))
        if not 1 <= minutes <= 300:
            continue
        if _is_meta_phase(phase):
            continue  # a reserved buffer section is not a taught block
        seen_phases.add(phase.lower())
        blocks.append(
            {
                "id": f"B{len(blocks) + 1}",
                "phase": phase,
                "minutes": minutes,
                "tutor_focus": "",
                "check_questions": [],
            }
        )
    return blocks


def _salvage_questions(markdown: str) -> list[str]:
    """Collect check-questions from anywhere (headings may not match schema).

    Reasoning models emit questions as bullets, numbered items, or plain
    sentences, sometimes with a leading "Check:"/"Ask:" label. Accept any of
    those when the line is a self-contained question.
    """
    questions: list[str] = []
    for raw_line in _fold_wrapped_lines(markdown.splitlines()):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _CHECK_RE.match(line)
        body = match.group(1).strip() if match else line
        body = re.sub(r"^\**\s*(?:check|ask|question)\s*[:\-]\s*\**\s*", "", body, flags=re.I)
        body = _clean_item(body)
        if not body.endswith("?"):
            continue
        if not 8 <= len(body) <= 200 or body in questions:
            continue
        questions.append(body)
        if len(questions) >= 8:
            break
    return questions


def distribute_check_questions(blocks: list[dict], questions: list[str]) -> None:
    """Assign up to three questions per block while preserving their order."""
    for block in blocks:
        block["check_questions"] = []
    if not blocks:
        return

    assigned_count = min(len(questions), len(blocks) * 3)
    per_block, remainder = divmod(assigned_count, len(blocks))
    cursor = 0
    for index, block in enumerate(blocks):
        count = per_block + (1 if index < remainder else 0)
        block["check_questions"] = questions[cursor : cursor + count]
        cursor += count


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

    lines = _fold_wrapped_lines((markdown or "").splitlines())
    for raw_line in lines:
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
                if cells and _is_meta_phase(cells[0]):
                    continue  # buffer/total rows are not taught blocks
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
                text = re.sub(r"\((?:bloom|level):?\s*([a-z]+)\)\s*$", "", text, flags=re.I)
                text = _clean_item(text)
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
                check_questions.append(_clean_item(match.group(1)))
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

    # Salvage pass: a model that ignores the schema (custom headings, inline
    # "**Time:** 5 minutes" durations, question bullets elsewhere) is still parsed
    # here rather than falling back or forcing a costly corrective retry.
    if not blocks:
        blocks = _salvage_blocks(markdown or "")
    if not check_questions:
        check_questions = _salvage_questions(markdown or "")

    # Distribute questions so every block gets a transition prompt when enough
    # questions were supplied, with no block receiving more than 3.
    if blocks and check_questions:
        distribute_check_questions(blocks, check_questions)

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

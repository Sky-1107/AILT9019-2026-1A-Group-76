"""Deterministic mock generation used in mock mode (MOCK_MODE=1 or no API key).

Matches the ``AgentRunResult`` interface from ``agent_service`` without importing
``pi_python`` (duck-typed dataclass with the same fields). Uses ``plans`` for all time
math so the mock and live post-processing paths behave identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import plans


@dataclass
class MockRunResult:
    """Same shape as agent_service.AgentRunResult."""

    text: str
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


_DEFAULT_ACTIVITIES = ("discussion", "guided example", "paired practice")

_TEMPLATES = {
    "remember": "Recall the key terms and definitions connected to {topic}.",
    "understand": "Explain the central idea of {topic} in your own words.",
    "apply": "Apply one core idea of {topic} to a worked example.",
    "analyze": "Compare two approaches within {topic} and justify the difference.",
    "evaluate": "Judge which approach to {topic} fits the given criteria.",
    "create": "Sketch a short plan that uses {topic} in a new context.",
}

_FOCUS = {
    "Hook": "Connect {topic} to something the learners already know; pose the opening question.",
    "Core Concept": "Model the essential ideas of {topic} in {minutes} minutes, pausing twice "
    "for clarification.",
    "Interactive Exercise": "Learners practise {activity} on a fresh example of {topic}; circulate "
    "and sample reasoning.",
    "Wrap-up": "Summarise {topic} in one sentence each; collect remaining questions.",
}

_CHECK_QUESTIONS = [
    "What is the most important idea so far, and why?",
    "How would you explain this to someone who missed the class?",
    "Can you give an example that is not in the brief?",
    "What would change your answer if one assumption were different?",
]

_PACING_NOTES = {
    "slow": "Pacing preference: keep each phase unhurried; the buffer absorbs questions.",
    "steady": "Pacing preference: move steadily between phases with explicit transitions.",
    "fast": "Pacing preference: keep transitions short; front-load the core concept.",
}


def _first_sentences(brief: str, count: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", brief or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return parts[:count]


def _activity_list(activity_types: str) -> list[str]:
    items = [a.strip() for a in (activity_types or "").split(",") if a.strip()]
    return items or list(_DEFAULT_ACTIVITIES)


def _bloom_sequence(count: int) -> list[str]:
    base = ["understand", "apply", "analyze"]
    order = base + ["evaluate", "remember", "create"]
    return order[:count]


def run_mock(payload: dict, reference_labels: list[str]) -> MockRunResult:
    """Build a deterministic lesson-plan Markdown draft for the normalized payload.

    ``payload`` keys: topic, duration_minutes, buffer_minutes, usable_minutes,
    buffer_auto (bool), target_level, brief, activity_types, pacing_preferences.
    """
    topic = payload["topic"]
    duration = int(payload["duration_minutes"])
    buffer = int(payload["buffer_minutes"])
    usable = int(payload["usable_minutes"])
    level = payload.get("target_level", "")
    brief = payload.get("brief", "")
    activities = _activity_list(payload.get("activity_types", ""))
    pacing = (payload.get("pacing_preferences") or "").strip().lower()

    blocks = plans.allocate_blocks(usable)
    for index, block in enumerate(blocks):
        activity = activities[index % len(activities)]
        block["tutor_focus"] = _FOCUS[block["phase"]].format(
            topic=topic, minutes=block["minutes"], activity=activity
        )

    objective_count = 3 if usable >= 30 else 2
    blooms = _bloom_sequence(objective_count)
    objectives = [
        {
            "id": f"LO{number}",
            "text": _TEMPLATES[bloom].format(topic=topic),
            "bloom": bloom,
        }
        for number, bloom in enumerate(blooms, start=1)
    ]

    check_questions = _CHECK_QUESTIONS[: max(3, min(4, len(blocks) + 1))]
    per_block = max(1, len(check_questions) // len(blocks))
    cursor = 0
    for block in blocks:
        take = per_block if cursor + per_block <= len(check_questions) else 1
        block["check_questions"] = check_questions[cursor : cursor + take]
        cursor += take

    lines: list[str] = [f"# Lesson Plan Draft: {topic}", ""]
    lines.append("## Learning Objectives")
    lines.append("")
    lead = (
        f"By the end of this {duration}-minute session for {level or 'learners'}, "
        "learners should be able to:"
        if level
        else f"By the end of this {duration}-minute session, learners should be able to:"
    )
    lines.append(lead)
    lines.append("")
    for objective in objectives:
        lines.append(
            f"- {objective['id']}: {objective['text']} (bloom: {objective['bloom']})"
        )
    lines.append("")
    lines.append("## Time Allocation")
    lines.append("")
    lines.append("| Phase | Minutes | Tutor focus |")
    lines.append("| --- | ---: | --- |")
    for block in blocks:
        lines.append(f"| {block['phase']} | {block['minutes']} | {block['tutor_focus']} |")
    lines.append("")
    auto_note = (
        f" (auto: 5 minutes per 30 minutes of lesson time, capped so at least "
        f"{plans.MIN_USABLE} minutes stay usable)"
        if payload.get("buffer_auto")
        else ""
    )
    lines.append(
        f"Buffer: {buffer} minutes reserved{auto_note}. Usable teaching time: {usable} "
        f"of {duration} minutes."
    )
    lines.append("")
    lines.append("## Lesson Outline")
    lines.append("")
    brief_sentences = _first_sentences(brief, 2)
    if brief_sentences:
        lines.append(" ".join(brief_sentences))
        lines.append("")
    for block in blocks:
        lines.append(f"### {block['phase']} ({block['minutes']} min)")
        lines.append("")
        lines.append(block["tutor_focus"])
        lines.append("")
        for question in block["check_questions"]:
            lines.append(f"- Check: {question}")
        lines.append("")
    for key, note in _PACING_NOTES.items():
        if key in pacing:
            lines.append(note)
            lines.append("")
            break
    lines.append("## Tutor Check-Questions")
    lines.append("")
    for question in check_questions:
        lines.append(f"- {question}")
    if reference_labels:
        lines.append("")
        lines.append("## Sources")
        lines.append("")
        for label in reference_labels:
            lines.append(f"- {label}")
    lines.append("")
    lines.append(plans.DISCLAIMER)
    lines.append("")

    sources = [{"label": label, "snippet": ""} for label in reference_labels]
    meta = {"model": "mock", "provider": "mock", "elapsed_ms": 0, "mode": "mock"}
    return MockRunResult(text="\n".join(lines), sources=sources, warnings=[], meta=meta)

"""Varied mock generation used in mock mode (MOCK_MODE=1 or no API key).

Matches the ``AgentRunResult`` interface from ``agent_service`` without importing
``pi_python`` (duck-typed dataclass with the same fields). Uses ``plans`` for all time
math so the mock and live post-processing paths behave identically.

Content selection is randomized per call: clicking "Regenerate" with the same input
produces a fresh take (different objectives, focuses, questions). The *structure* —
required sections, block allocation, buffer math, disclaimer — stays fixed, so the
offline tests and the response shape remain stable.
"""

from __future__ import annotations

import random
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

# One or two template variants per Bloom level; picked at random per generation.
_TEMPLATES = {
    "remember": (
        "Recall the key terms and definitions connected to {topic}.",
        "List the main facts a learner should retain about {topic}.",
    ),
    "understand": (
        "Explain the central idea of {topic} in your own words.",
        "Describe why {topic} matters, using a everyday analogy.",
        "Summarise the core message of {topic} in two sentences.",
    ),
    "apply": (
        "Apply one core idea of {topic} to a worked example.",
        "Use {topic} to solve a fresh, closely related problem.",
        "Carry out a short task that puts {topic} into practice.",
    ),
    "analyze": (
        "Compare two approaches within {topic} and justify the difference.",
        "Break down a case of {topic} and identify what drives the outcome.",
        "Contrast {topic} with a familiar alternative and map the trade-offs.",
    ),
    "evaluate": (
        "Judge which approach to {topic} fits the given criteria.",
        "Critique a worked {topic} example against a short rubric.",
        "Defend a recommendation about {topic} with two pieces of evidence.",
    ),
    "create": (
        "Sketch a short plan that uses {topic} in a new context.",
        "Design a mini-project around {topic} for a different audience.",
        "Compose an original example that teaches {topic}.",
    ),
}

_FOCUS = {
    "Hook": (
        "Connect {topic} to something the learners already know; pose the opening question.",
        "Open with a surprising fact about {topic} and ask for first instincts.",
        "Show a short real-world vignette about {topic}; solicit quick predictions.",
        "Start from a common misconception about {topic}; take a show-of-hands poll.",
    ),
    "Core Concept": (
        "Model the essential ideas of {topic} in {minutes} minutes, pausing twice for clarification.",
        "Walk through the key moves of {topic} in {minutes} minutes, thinking aloud.",
        "Explain {topic} in layers: definition, worked demonstration, one counter-example.",
        "Present {topic} as a two-step method; check understanding after each step.",
    ),
    "Interactive Exercise": (
        "Learners practise {activity} on a fresh example of {topic}; circulate and sample reasoning.",
        "In pairs, learners attempt a variant of the {topic} example; compare answers after.",
        "Small groups tackle a mini-challenge on {topic}, then report one insight each.",
        "Learners run {activity} on a {topic} scenario while you collect typical errors.",
    ),
    "Wrap-up": (
        "Summarise {topic} in one sentence each; collect remaining questions.",
        "Exit ticket: one idea gained and one question left about {topic}.",
        "Revisit the opening question; learners answer it with today's vocabulary.",
        "Recap the two key moves of {topic}; preview where they return next session.",
    ),
}

_CHECK_QUESTIONS = (
    "What is the most important idea so far, and why?",
    "How would you explain this to someone who missed the class?",
    "Can you give an example that is not in the brief?",
    "What would change your answer if one assumption were different?",
    "Where is the weakest step in your reasoning so far?",
    "Which part of {topic} would you want more practice with?",
    "What connects today's {topic} to last week's material?",
    "If you had half the time, what would you keep and what would you drop?",
)

_LEADS = (
    "By the end of this {duration}-minute session for {level}, learners should be able to:",
    "After {duration} minutes on {topic}, {level} should be able to:",
    "This {duration}-minute session asks {level} to:",
)

_PACING_NOTES = {
    "slow": (
        "Pacing preference: keep each phase unhurried; the buffer absorbs questions.",
        "Pacing preference: allow extra think-time before each transition.",
    ),
    "steady": (
        "Pacing preference: move steadily between phases with explicit transitions.",
        "Pacing preference: keep a metronome rhythm — announce each phase change.",
    ),
    "fast": (
        "Pacing preference: keep transitions short; front-load the core concept.",
        "Pacing preference: run compact segments; park questions in the buffer.",
    ),
}

_BLOOM_ORDER = ("remember", "understand", "apply", "analyze", "evaluate", "create")


def _first_sentences(brief: str, count: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", brief or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return parts[:count]


def _activity_list(activity_types: str) -> list[str]:
    items = [a.strip() for a in (activity_types or "").split(",") if a.strip()]
    return items or list(_DEFAULT_ACTIVITIES)


def _pick_blooms(rng: random.Random, count: int) -> list[str]:
    """Random ascending Bloom levels — a fresh pedagogical angle each generation."""
    chosen = rng.sample(_BLOOM_ORDER, count)
    return sorted(chosen, key=_BLOOM_ORDER.index)


def run_mock(payload: dict, reference_labels: list[str]) -> MockRunResult:
    """Build a lesson-plan Markdown draft for the normalized payload.

    Wording and content choices are randomized per call; the section structure and
    all time math follow plans.py exactly.

    ``payload`` keys: topic, duration_minutes, buffer_minutes, usable_minutes,
    buffer_auto (bool), target_level, brief, activity_types, pacing_preferences.
    """
    rng = random.Random()
    topic = payload["topic"]
    duration = int(payload["duration_minutes"])
    buffer = int(payload["buffer_minutes"])
    usable = int(payload["usable_minutes"])
    level = payload.get("target_level", "") or "learners"
    brief = payload.get("brief", "")
    activities = _activity_list(payload.get("activity_types", ""))
    pacing = (payload.get("pacing_preferences") or "").strip().lower()

    blocks = plans.allocate_blocks(usable)
    for index, block in enumerate(blocks):
        activity = rng.choice(activities)
        block["tutor_focus"] = rng.choice(_FOCUS[block["phase"]]).format(
            topic=topic, minutes=block["minutes"], activity=activity
        )

    objective_count = rng.choice((2, 3, 3, 4, 4, 5)) if usable >= 30 else rng.choice((2, 3))
    blooms = _pick_blooms(rng, objective_count)
    objectives = [
        {
            "id": f"LO{number}",
            "text": rng.choice(_TEMPLATES[bloom]).format(topic=topic),
            "bloom": bloom,
        }
        for number, bloom in enumerate(blooms, start=1)
    ]

    question_count = rng.choice((len(blocks), len(blocks) + 1, len(blocks) + 2))
    pool = [q.format(topic=topic) for q in _CHECK_QUESTIONS]
    check_questions = rng.sample(pool, question_count)
    plans.distribute_check_questions(blocks, check_questions)

    lines: list[str] = [f"# Lesson Plan Draft: {topic}", ""]
    lines.append("## Learning Objectives")
    lines.append("")
    lines.append(
        rng.choice(_LEADS).format(duration=duration, level=level, topic=topic)
    )
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
    for key, notes in _PACING_NOTES.items():
        if key in pacing:
            lines.append(rng.choice(notes))
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

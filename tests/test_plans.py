"""Tests for plans.py: duration parsing, buffer math, allocation, feasibility."""

from __future__ import annotations

import pytest

import plans
from plans import (
    DISCLAIMER,
    allocate_blocks,
    check_feasibility,
    compute_buffer,
    parse_duration,
    parse_markdown_to_plan,
    plan_to_markdown,
    repair_block_minutes,
    validate_generated_plan,
)
from validation import ValidationError


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("50", 50),
            ("50 mins", 50),
            ("50 minutes", 50),
            ("50m", 50),
            ("1 hour", 60),
            ("1.5 hours", 90),
            ("90 min", 90),
            ("  45  ", 45),
        ],
    )
    def test_valid(self, text, expected):
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["banana", "", "50 seconds", "10 hours", "5", "301"])
    def test_invalid_or_out_of_range(self, text):
        with pytest.raises(ValidationError):
            parse_duration(text)


class TestComputeBuffer:
    def test_auto_for_50_minutes(self):
        buffer = compute_buffer(50, "auto")
        assert 5 <= buffer <= 10
        assert 50 - buffer >= 20

    def test_auto_none_same_as_auto(self):
        assert compute_buffer(50, None) == compute_buffer(50, "auto")

    def test_auto_60_minutes_is_10(self):
        assert compute_buffer(60, "auto") == 10

    def test_explicit_value_respected(self):
        assert compute_buffer(50, 15) == 15

    def test_explicit_capped_for_usable_minimum(self):
        buffer = compute_buffer(30, 30)
        assert buffer == 10  # usable must stay >= 20
        assert 30 - buffer >= 20

    def test_zero_allowed(self):
        assert compute_buffer(50, 0) == 0

    def test_invariant_buffer_le_duration_minus_20(self):
        for duration in (20, 30, 50, 90, 120, 300):
            for pref in (None, "auto", 0, 5, 15, 30):
                buffer = compute_buffer(duration, pref)
                assert 0 <= buffer <= max(0, duration - 20)


class TestAllocateBlocks:
    def test_sums_to_usable(self):
        for usable in (20, 25, 40, 45, 55, 90, 280):
            blocks = allocate_blocks(usable)
            assert sum(b["minutes"] for b in blocks) == usable

    def test_four_phases_in_order(self):
        blocks = allocate_blocks(40)
        assert [b["phase"] for b in blocks] == [
            "Hook",
            "Core Concept",
            "Interactive Exercise",
            "Wrap-up",
        ]

    def test_minimum_five_per_block_when_feasible(self):
        blocks = allocate_blocks(40)
        assert all(b["minutes"] >= 5 for b in blocks)

    def test_ids_assigned(self):
        blocks = allocate_blocks(45)
        assert [b["id"] for b in blocks] == ["B1", "B2", "B3", "B4"]

    def test_too_short_raises(self):
        with pytest.raises(ValidationError):
            allocate_blocks(15)


class TestCheckFeasibility:
    def test_15_minute_session_refused(self):
        issue = check_feasibility("X", 15, 0, "Teach recursion with practice.")
        assert issue is not None
        assert issue.code == "too_short"
    def test_ten_objectives_refused(self):
        issue = check_feasibility(
            "X", 50, 5, "Cover 10 learning objectives in one session."
        )
        assert issue is not None
        assert issue.code == "too_many_objectives"

    def test_twelve_segments_refused(self):
        issue = check_feasibility(
            "X", 120, 10, "Run 12 timed activity segments back to back."
        )
        assert issue is not None
        assert issue.code == "too_many_segments"

    def test_empty_brief_refused(self):
        issue = check_feasibility("X", 50, 5, "   ")
        assert issue is not None
        assert issue.code == "empty_brief"

    def test_normal_brief_passes(self):
        assert check_feasibility("X", 50, 5, "Practise a worked example in pairs.") is None


class TestDensityFlag:
    def test_six_objectives_flagged_not_refused(self):
        assert check_feasibility("X", 90, 10, "Cover 6 learning objectives.") is None
        flag = plans.density_flag("Cover 6 learning objectives.", 80)
        assert flag is not None
        assert "Density flag" in flag

    def test_normal_brief_no_flag(self):
        assert plans.density_flag("Practise a worked example in pairs.", 45) is None

    def test_checklist_attached(self):
        plan = {"topic": "T"}
        plans.attach_extras(plan)
        assert len(plan["checklist"]) >= 3


class TestMarkdownRoundTrip:
    def test_parse_table_and_sections(self):
        markdown = "\n".join(
            [
                "# Lesson Plan Draft: Frauds",
                "## Learning Objectives",
                "- LO1: Apply a decision tree to a transaction log (bloom: apply)",
                "- LO2: Compare two rule sets (bloom: analyze)",
                "## Time Allocation",
                "| Phase | Minutes | Tutor focus |",
                "| --- | ---: | --- |",
                "| Hook | 5 | Warm-up question. |",
                "| Core Concept | 25 | Model the method. |",
                "| Interactive Exercise | 10 | Pair task. |",
                "| Wrap-up | 5 | Exit ticket. |",
                "## Tutor Check-Questions",
                "- What changed your mind?",
                "- Why does this rule fire?",
                DISCLAIMER,
            ]
        )
        meta = {
            "topic": "Frauds",
            "duration_minutes": 50,
            "buffer_minutes": 5,
            "usable_minutes": 45,
        }
        plan = parse_markdown_to_plan(markdown, meta)
        assert len(plan["objectives"]) == 2
        assert plan["objectives"][0]["bloom"] == "apply"
        assert sum(b["minutes"] for b in plan["blocks"]) == 45
        assert len(plan["check_questions"]) == 2
        assert plan["disclaimer"] == DISCLAIMER

    def test_repair_adjusts_core_concept(self):
        plan = {
            "usable_minutes": 40,
            "blocks": [
                {"phase": "Hook", "minutes": 5},
                {"phase": "Core Concept", "minutes": 20},
                {"phase": "Interactive Exercise", "minutes": 15},
                {"phase": "Wrap-up", "minutes": 10},
            ],
        }
        assert repair_block_minutes(plan)
        assert sum(b["minutes"] for b in plan["blocks"]) == 40

    def test_validate_warnings(self):
        plan = {
            "objectives": [{"id": "LO1", "text": "x", "bloom": "apply"}],
            "blocks": [],
            "usable_minutes": 40,
            "check_questions": [],
            "disclaimer": "wrong",
            "sources_expected": True,
            "sources": [],
        }
        warnings = validate_generated_plan(plan)
        assert any("fewer than 2" in w for w in warnings)
        assert any("check-questions" in w for w in warnings)
        assert any("disclaimer" in w for w in warnings)
        assert any("sources" in w for w in warnings)

    def test_plan_to_markdown_contains_sections(self):
        plan = {
            "topic": "T",
            "duration_minutes": 50,
            "buffer_minutes": 5,
            "usable_minutes": 45,
            "objectives": [{"id": "LO1", "text": "A", "bloom": "apply"}],
            "blocks": [{"id": "B1", "phase": "Hook", "minutes": 5, "tutor_focus": "F", "check_questions": []}],
            "check_questions": ["Q?"],
            "sources": [],
            "warnings": [],
            "disclaimer": DISCLAIMER,
        }
        markdown = plan_to_markdown(plan)
        for heading in (
            "# Lesson Plan Draft: T",
            "## Learning Objectives",
            "## Time Allocation",
            "## Lesson Outline",
            "## Tutor Check-Questions",
            DISCLAIMER,
        ):
            assert heading in markdown

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

    def test_questions_are_distributed_across_all_blocks(self):
        markdown = "\n".join(
            [
                "# Lesson Plan Draft: Fractions",
                "## Time Allocation",
                "| Phase | Minutes | Tutor focus |",
                "| --- | ---: | --- |",
                "| Hook | 5 | Introduce the idea. |",
                "| Core Concept | 20 | Model the method. |",
                "| Interactive Exercise | 15 | Practise together. |",
                "| Wrap-up | 5 | Review the lesson. |",
                "## Tutor Check-Questions",
                "- What is the central idea?",
                "- How would you apply it?",
                "- What evidence supports your answer?",
                "- What would you change next time?",
                "- How does this connect to the example?",
            ]
        )
        plan = parse_markdown_to_plan(
            markdown,
            {
                "topic": "Fractions",
                "duration_minutes": 50,
                "buffer_minutes": 5,
                "usable_minutes": 45,
            },
        )
        block_questions = [question for block in plan["blocks"] for question in block["check_questions"]]
        assert [len(block["check_questions"]) for block in plan["blocks"]] == [2, 1, 1, 1]
        assert block_questions == plan["check_questions"]

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

    def test_validate_warns_when_a_block_has_no_check_question(self):
        plan = {
            "objectives": [
                {"id": "LO1", "text": "x", "bloom": "understand"},
                {"id": "LO2", "text": "y", "bloom": "apply"},
            ],
            "blocks": [
                {"phase": "Hook", "minutes": 5, "check_questions": ["Why?"]},
                {"phase": "Core Concept", "minutes": 20, "check_questions": ["How?"]},
                {"phase": "Interactive Exercise", "minutes": 15, "check_questions": []},
                {"phase": "Wrap-up", "minutes": 5, "check_questions": ["What next?"]},
            ],
            "usable_minutes": 45,
            "check_questions": ["Why?", "How?", "What next?"],
            "disclaimer": DISCLAIMER,
        }
        warnings = validate_generated_plan(plan)
        assert any("blocks have no tutor check-question" in warning for warning in warnings)

    def test_salvage_parses_non_schema_draft(self):
        # A reasoning model that ignores the skill schema: custom headings and
        # inline "**Time:** N minutes" instead of a Time Allocation table.
        markdown = "\n".join(
            [
                "# Lesson Plan: Fractions",
                "**Duration:** 50 minutes",
                "## Learning Objectives",
                "- Understand what a fraction represents.",
                "- Identify the numerator and denominator.",
                "# Lesson Structure",
                "## 1. Starter Activity",
                "**Time:** 5 minutes",
                "Show an image divided into parts.",
                "## 2. Explanation",
                "**Time:** 10 minutes",
                "Model labelling.",
                "## 3. Main Activity",
                "**Time:** 12 minutes",
                "Shade fraction strips.",
                "## 4. Plenary",
                "**Time:** 7 minutes",
                "Which part was most useful?",
                DISCLAIMER,
            ]
        )
        meta = {
            "topic": "Fractions",
            "duration_minutes": 50,
            "buffer_minutes": 5,
            "usable_minutes": 45,
        }
        plan = parse_markdown_to_plan(markdown, meta)
        assert len(plan["objectives"]) == 2
        assert len(plan["blocks"]) == 4
        assert [b["phase"] for b in plan["blocks"]] == [
            "Starter Activity",
            "Explanation",
            "Main Activity",
            "Plenary",
        ]
        assert plan["blocks"][0]["minutes"] == 5
        # Salvaged questions come from the interrogative bullets.
        assert any("most useful" in q for q in plan["check_questions"])

    def test_soft_wrapped_items_are_folded_not_truncated(self):
        # Models wrap long objectives/questions across physical lines; the
        # parser must rejoin them, not emit a fragment ending on a dangling word.
        markdown = "\n".join(
            [
                "# Lesson Plan Draft: Frauds",
                "## Learning Objectives",
                "- LO1: Apply a decision tree to flag transactions and",
                "  explain the chosen split rule.",
                "## Tutor Check-Questions",
                "- Same amount, different device — do we land on the same leaf?",
                "  Say the rule aloud before you check.",
            ]
        )
        meta = {
            "topic": "Frauds",
            "duration_minutes": 50,
            "buffer_minutes": 5,
            "usable_minutes": 45,
        }
        plan = parse_markdown_to_plan(markdown, meta)
        assert plan["objectives"][0]["text"] == (
            "Apply a decision tree to flag transactions and explain the chosen split rule."
        )
        joined = " ".join(plan["check_questions"])
        assert "Say the rule aloud before you check." in joined
        assert not any(q.endswith("leaf") for q in plan["check_questions"])

    def test_buffer_and_total_rows_are_not_taught_blocks(self):
        # Models often add a "Buffer"/"Total" row; those reserve or summarise
        # time and must not become blocks (usable already excludes the buffer).
        markdown = "\n".join(
            [
                "# Lesson Plan Draft: Fractions",
                "## Time Allocation",
                "| Phase | Minutes | Tutor focus |",
                "| --- | ---: | --- |",
                "| Hook | 5 | Warm-up. |",
                "| Core Concept | 20 | Teach. |",
                "| Interactive Exercise | 15 | Practise. |",
                "| Wrap-up | 5 | Recap. |",
                "| Buffer (reserved, not taught) | 5 | Flex time. |",
                "| Total | 50 | Whole lesson. |",
            ]
        )
        meta = {
            "topic": "Fractions",
            "duration_minutes": 50,
            "buffer_minutes": 5,
            "usable_minutes": 45,
        }
        plan = parse_markdown_to_plan(markdown, meta)
        assert [b["phase"] for b in plan["blocks"]] == [
            "Hook",
            "Core Concept",
            "Interactive Exercise",
            "Wrap-up",
        ]
        assert sum(b["minutes"] for b in plan["blocks"]) == 45

    def test_repair_targets_core_phase_with_custom_names(self):
        # Models rarely name a block "Core Concept"; repair must still work.
        plan = {
            "usable_minutes": 40,
            "blocks": [
                {"phase": "Starter", "minutes": 5},
                {"phase": "Main teaching", "minutes": 20},
                {"phase": "Plenary", "minutes": 10},
            ],
        }
        assert repair_block_minutes(plan)
        assert sum(b["minutes"] for b in plan["blocks"]) == 40
        # The core/teaching block absorbed the +5 difference (20 -> 25), not the
        # largest-by-accident (which happens to be the same block here, so we
        # also check a case where they differ below).
        assert [b for b in plan["blocks"] if b["phase"] == "Main teaching"][0]["minutes"] == 25

    def test_repair_falls_back_to_largest_block(self):
        plan = {
            "usable_minutes": 40,
            "blocks": [
                {"phase": "Warm-up", "minutes": 5},
                {"phase": "Task", "minutes": 25},
                {"phase": "Review", "minutes": 10},
            ],
        }
        assert repair_block_minutes(plan)
        assert sum(b["minutes"] for b in plan["blocks"]) == 40

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

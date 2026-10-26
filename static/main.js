/* Lesson-Plan Scaffolder frontend — vanilla JS only, no frameworks, no CDNs.
 * All agent/server output is inserted with textContent (never innerHTML).
 * planToMarkdown mirrors plans.plan_to_markdown in the backend; keep them in sync.
 */

(() => {
    "use strict";

    const form = document.getElementById("lesson-form");
    const generateButton = document.getElementById("generate-button");
    const sampleButton = document.getElementById("sample-button");
    const clearButton = document.getElementById("clear-button");
    const copyButton = document.getElementById("copy-button");
    const exportButton = document.getElementById("export-button");
    const regenerateButton = document.getElementById("regenerate-button");

    const statusRegion = document.getElementById("status-region");
    const refusalPanel = document.getElementById("refusal-panel");
    const refusalCode = document.getElementById("refusal-code");
    const refusalMessage = document.getElementById("refusal-message");
    const demoBadge = document.getElementById("demo-badge");
    const resultActions = document.getElementById("result-actions");
    const resultTabs = document.getElementById("result-tabs");

    const tabWorkspace = document.getElementById("tab-workspace");
    const tabRaw = document.getElementById("tab-raw");
    const viewWorkspace = document.getElementById("view-workspace");
    const viewRaw = document.getElementById("view-raw");
    const rawMarkdown = document.getElementById("raw-markdown");

    const calcTotal = document.getElementById("calc-total");
    const calcUsable = document.getElementById("calc-usable");
    const timeCalculator = document.getElementById("time-calculator");
    const overrunAlert = document.getElementById("overrun-alert");
    const bufferValue = document.getElementById("buffer-value");
    const bufferNote = document.getElementById("buffer-note");

    const objectivesList = document.getElementById("objectives-list");
    const blocksList = document.getElementById("blocks-list");
    const questionsList = document.getElementById("questions-list");
    const outlineEditor = document.getElementById("outline-editor");
    const checklistBlock = document.getElementById("checklist-block");
    const checklistList = document.getElementById("checklist-list");

    const sourcesBlock = document.getElementById("sources-block");
    const sourcesList = document.getElementById("sources-list");
    const warningsBlock = document.getElementById("warnings-block");
    const warningsList = document.getElementById("warnings-list");
    const disclaimerLine = document.getElementById("disclaimer-line");

    const DISCLAIMER = "Preliminary, non-accredited draft; tutor review required.";

    const sampleBrief = {
        topic: "Fraud detection with decision trees",
        duration: "50 mins",
        target_level: "1st Year Undergrad",
        brief:
            "Learners compare two rule-based ways to flag suspicious transactions and practise " +
            "on a worked example. Connect to a real payment-app experience they already know.",
        activity_types: "worked example, pair discussion",
        pacing_preferences: "slow start, steady transitions",
        buffer_preference: "auto"
    };

    let currentPlan = null;

    /* ---------------- helpers ---------------- */

    function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function setStatus(message, kind) {
        statusRegion.textContent = message;
        statusRegion.classList.remove("status-ok", "status-error");
        if (kind) statusRegion.classList.add(kind === "ok" ? "status-ok" : "status-error");
    }

    function showRefusal(code, message) {
        refusalCode.textContent = "Refusal code: " + code;
        refusalMessage.textContent = message;
        refusalPanel.hidden = false;
    }

    function hideRefusal() {
        refusalPanel.hidden = true;
        refusalCode.textContent = "";
        refusalMessage.textContent = "";
    }

    function setLoading(isLoading) {
        generateButton.disabled = isLoading;
        sampleButton.disabled = isLoading;
        clearButton.disabled = isLoading;
        regenerateButton.disabled = isLoading;
        generateButton.classList.toggle("is-loading", isLoading);
        generateButton.querySelector(".button-label").textContent =
            isLoading ? "Generating draft…" : "Generate Lesson Draft";
    }

    function slugify(text) {
        return (text || "draft")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 48) || "draft";
    }

    /* ---------------- tabs (keyboard operable) ---------------- */

    function selectTab(active) {
        const workspace = active === tabWorkspace;
        tabWorkspace.classList.toggle("is-active", workspace);
        tabRaw.classList.toggle("is-active", !workspace);
        tabWorkspace.setAttribute("aria-selected", String(workspace));
        tabRaw.setAttribute("aria-selected", String(!workspace));
        tabWorkspace.tabIndex = workspace ? 0 : -1;
        tabRaw.tabIndex = workspace ? -1 : 0;
        viewWorkspace.hidden = !workspace;
        viewRaw.hidden = workspace;
    }

    tabWorkspace.addEventListener("click", () => selectTab(tabWorkspace));
    tabRaw.addEventListener("click", () => selectTab(tabRaw));
    [tabWorkspace, tabRaw].forEach((tab) => {
        tab.addEventListener("keydown", (event) => {
            if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                event.preventDefault();
                const next = tab === tabWorkspace ? tabRaw : tabWorkspace;
                selectTab(next);
                next.focus();
            }
        });
    });

    /* ---------------- plan <-> markdown (mirrors plans.py) ---------------- */

    function planToMarkdown(plan) {
        const lines = [];
        lines.push("# Lesson Plan Draft: " + (plan.topic || "Untitled"), "");
        lines.push("## Learning Objectives", "");
        (plan.objectives || []).forEach((objective) => {
            lines.push(
                "- " + (objective.id || "LO") + ": " + (objective.text || "").trim() +
                " (bloom: " + (objective.bloom || "understand") + ")"
            );
        });
        lines.push("", "## Time Allocation", "");
        lines.push("| Phase | Minutes | Tutor focus |");
        lines.push("| --- | ---: | --- |");
        (plan.blocks || []).forEach((block) => {
            lines.push(
                "| " + (block.phase || "") + " | " + Number(block.minutes || 0) + " | " +
                (block.tutor_focus || "").trim() + " |"
            );
        });
        lines.push("");
        const autoNote = plan.buffer_auto
            ? " (auto: 5 minutes per 30 minutes of lesson)"
            : "";
        lines.push(
            "Buffer: " + (plan.buffer_minutes || 0) + " minutes reserved" + autoNote +
            ". Usable teaching time: " + (plan.usable_minutes || 0) + " of " +
            (plan.duration_minutes || 0) + " minutes."
        );
        lines.push("", "## Lesson Outline", "");
        if (plan.outline_markdown) {
            lines.push(plan.outline_markdown, "");
        } else {
            (plan.blocks || []).forEach((block) => {
                lines.push("### " + (block.phase || "") + " (" + Number(block.minutes || 0) + " min)", "");
                if (block.tutor_focus) lines.push(block.tutor_focus.trim(), "");
                (block.check_questions || []).forEach((q) => lines.push("- Check: " + q));
                if (block.check_questions && block.check_questions.length) lines.push("");
            });
        }
        lines.push("## Tutor Check-Questions", "");
        (plan.check_questions || []).forEach((question) => lines.push("- " + question));
        if (plan.sources && plan.sources.length) {
            lines.push("", "## Sources", "");
            plan.sources.forEach((source) => {
                const snippet = (source.snippet || "").trim();
                lines.push(snippet ? "- " + source.label + ": " + snippet : "- " + source.label);
            });
        }
        lines.push("", plan.disclaimer || DISCLAIMER, "");
        return lines.join("\n");
    }

    /* ---------------- metrics ---------------- */

    function recomputeMetrics() {
        if (!currentPlan) return;
        const total = (currentPlan.blocks || []).reduce(
            (sum, block) => sum + (Number(block.minutes) || 0), 0
        );
        const usable = Number(currentPlan.usable_minutes) || 0;
        calcTotal.textContent = String(total);
        calcUsable.textContent = "of " + usable + " usable min";
        const over = total > usable;
        timeCalculator.classList.toggle("is-over", over);
        if (over) {
            overrunAlert.hidden = false;
            overrunAlert.textContent = "Overrun: +" + (total - usable) + " min beyond usable time";
        } else {
            overrunAlert.hidden = true;
        }
        bufferValue.textContent = (Number(currentPlan.buffer_minutes) || 0) + " min";
        bufferNote.textContent = currentPlan.buffer_auto
            ? "auto rule: 5 min per 30 min of lesson"
            : "explicit tutor choice";
        refreshRawMarkdown();
    }

    function refreshRawMarkdown() {
        if (currentPlan) rawMarkdown.textContent = planToMarkdown(currentPlan);
    }

    /* ---------------- workspace rendering ---------------- */

    function renderObjectives() {
        objectivesList.textContent = "";
        currentPlan.objectives.forEach((objective, index) => {
            const item = el("li");
            const head = el("div", "item-head");
            head.appendChild(el("span", "item-tag", objective.id || "LO" + (index + 1)));
            const bloom = el("select");
            ["remember", "understand", "apply", "analyze", "evaluate", "create"].forEach((level) => {
                const option = el("option", undefined, level);
                option.value = level;
                if (level === objective.bloom) option.selected = true;
                bloom.appendChild(option);
            });
            bloom.setAttribute("aria-label", "Bloom level for " + (objective.id || "objective"));
            const remove = el("button", "mini-button", "Remove");
            remove.type = "button";
            remove.addEventListener("click", () => {
                currentPlan.objectives.splice(index, 1);
                renumber(currentPlan.objectives, "LO");
                renderObjectives();
                recomputeMetrics();
            });
            head.appendChild(bloom);
            head.appendChild(remove);
            const text = el("textarea");
            text.rows = 2;
            text.value = objective.text || "";
            text.setAttribute("aria-label", "Objective " + (index + 1) + " text");
            text.addEventListener("input", () => {
                objective.text = text.value;
                refreshRawMarkdown();
            });
            bloom.addEventListener("change", () => {
                objective.bloom = bloom.value;
                refreshRawMarkdown();
            });
            item.appendChild(head);
            item.appendChild(text);
            objectivesList.appendChild(item);
        });
        const add = el("button", "add-row", "+ Add objective");
        add.type = "button";
        add.addEventListener("click", () => {
            currentPlan.objectives.push({ id: "", text: "", bloom: "understand" });
            renumber(currentPlan.objectives, "LO");
            renderObjectives();
            recomputeMetrics();
        });
        objectivesList.appendChild(add);
    }

    function renderBlocks() {
        blocksList.textContent = "";
        currentPlan.blocks.forEach((block, index) => {
            const item = el("li");
            const head = el("div", "item-head");
            const phase = el("input");
            phase.type = "text";
            phase.value = block.phase || "";
            phase.setAttribute("aria-label", "Phase name for block " + (index + 1));
            phase.classList.add("block-phase");
            const minutes = el("input");
            minutes.type = "number";
            minutes.min = "0";
            minutes.step = "1";
            minutes.value = String(Number(block.minutes) || 0);
            minutes.className = "block-minutes";
            minutes.setAttribute("aria-label", "Minutes for " + (block.phase || "block"));
            const remove = el("button", "mini-button", "Remove");
            remove.type = "button";
            remove.addEventListener("click", () => {
                currentPlan.blocks.splice(index, 1);
                renumber(currentPlan.blocks, "B");
                renderBlocks();
                recomputeMetrics();
            });
            head.appendChild(phase);
            head.appendChild(minutes);
            head.appendChild(remove);
            const focus = el("textarea");
            focus.rows = 2;
            focus.value = block.tutor_focus || "";
            focus.setAttribute("aria-label", "Tutor focus for " + (block.phase || "block"));
            focus.addEventListener("input", () => {
                block.tutor_focus = focus.value;
                refreshRawMarkdown();
            });
            phase.addEventListener("input", () => {
                block.phase = phase.value;
                refreshRawMarkdown();
            });
            minutes.addEventListener("input", () => {
                block.minutes = Number(minutes.value) || 0;
                recomputeMetrics();
            });
            item.appendChild(head);
            item.appendChild(focus);
            blocksList.appendChild(item);
        });
        const add = el("button", "add-row", "+ Add block");
        add.type = "button";
        add.addEventListener("click", () => {
            currentPlan.blocks.push({ id: "", phase: "New phase", minutes: 5, tutor_focus: "", check_questions: [] });
            renumber(currentPlan.blocks, "B");
            renderBlocks();
            recomputeMetrics();
        });
        blocksList.appendChild(add);
    }

    function renderQuestions() {
        questionsList.textContent = "";
        currentPlan.check_questions.forEach((question, index) => {
            const item = el("li");
            const head = el("div", "item-head");
            head.appendChild(el("span", "item-tag", "Q" + (index + 1)));
            const remove = el("button", "mini-button", "Remove");
            remove.type = "button";
            remove.addEventListener("click", () => {
                currentPlan.check_questions.splice(index, 1);
                renderQuestions();
                refreshRawMarkdown();
            });
            head.appendChild(remove);
            const text = el("textarea");
            text.rows = 2;
            text.value = question;
            text.setAttribute("aria-label", "Check question " + (index + 1));
            text.addEventListener("input", () => {
                currentPlan.check_questions[index] = text.value;
                refreshRawMarkdown();
            });
            item.appendChild(head);
            item.appendChild(text);
            questionsList.appendChild(item);
        });
        const add = el("button", "add-row", "+ Add question");
        add.type = "button";
        add.addEventListener("click", () => {
            currentPlan.check_questions.push("");
            renderQuestions();
            refreshRawMarkdown();
        });
        questionsList.appendChild(add);
    }

    function renumber(items, prefix) {
        items.forEach((item, index) => {
            item.id = prefix + (index + 1);
        });
    }

    function renderMetaLists() {
        const sources = currentPlan.sources || [];
        sourcesBlock.hidden = sources.length === 0;
        sourcesList.textContent = "";
        sources.forEach((source) => {
            const text = source.snippet ? source.label + " — " + source.snippet : source.label;
            sourcesList.appendChild(el("li", undefined, text));
        });
        const warnings = currentPlan.warnings || [];
        warningsBlock.hidden = warnings.length === 0;
        warningsList.textContent = "";
        warnings.forEach((warning) => warningsList.appendChild(el("li", undefined, warning)));
        const checklist = currentPlan.checklist || [];
        checklistBlock.hidden = checklist.length === 0;
        checklistList.textContent = "";
        checklist.forEach((item) => checklistList.appendChild(el("li", undefined, item)));
        disclaimerLine.textContent = currentPlan.disclaimer || DISCLAIMER;
    }

    function renderWorkspace(plan) {
        currentPlan = plan;
        if (!plan.objectives) plan.objectives = [];
        if (!plan.blocks) plan.blocks = [];
        if (!plan.check_questions) plan.check_questions = [];
        renderObjectives();
        renderBlocks();
        renderQuestions();
        outlineEditor.value = plan.outline_markdown || "";
        renderMetaLists();
        recomputeMetrics();
    }

    outlineEditor.addEventListener("input", () => {
        if (currentPlan) {
            currentPlan.outline_markdown = outlineEditor.value;
            refreshRawMarkdown();
        }
    });

    const workspaceGrid = document.querySelector(".workspace-grid");

    /* ---------------- result visibility ---------------- */

    function showResults() {
        resultTabs.hidden = false;
        resultActions.hidden = false;
        // Stack the layout so the three workspace columns get the full page width.
        if (workspaceGrid) workspaceGrid.classList.add("has-results");
        selectTab(tabWorkspace);
    }

    function hideResults() {
        resultTabs.hidden = true;
        resultActions.hidden = true;
        if (workspaceGrid) workspaceGrid.classList.remove("has-results");
        currentPlan = null;
        // demoBadge is intentionally left alone: it reflects the server mode,
        // which is known from page load (see refreshModeBadge).
    }

    /* ---------------- request ---------------- */

    // Client-side give-up: the server's provider timeout is 60s with retries, so
    // 150s is comfortably beyond any healthy live call.
    const REQUEST_TIMEOUT_MS = 150000;

    async function submitGeneration() {
        hideRefusal();
        setLoading(true);
        const startedAt = Date.now();
        setStatus("Generating your lesson draft… Mock mode is instant; a live model can take up to a minute.", null);
        const elapsedTimer = window.setInterval(() => {
            const seconds = Math.round((Date.now() - startedAt) / 1000);
            setStatus("Still generating… " + seconds + "s elapsed.", null);
        }, 10000);

        const controller = new AbortController();
        const giveUpTimer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        const formData = new FormData(form);
        try {
            const response = await fetch("/api/generate", { method: "POST", body: formData, signal: controller.signal });
            let data;
            try {
                data = await response.json();
            } catch {
                throw new Error("The server returned an unreadable response.");
            }
            if (!response.ok) {
                const error = (data && data.error) || {};
                showRefusal(error.code || "internal_error", error.message || "The request failed.");
                setStatus("The draft was refused. See the refusal panel.", "error");
                hideResults();
                return;
            }
            demoBadge.hidden = data.status !== "mock";
            renderWorkspace(data.plan || {});
            rawMarkdown.textContent = data.draft || planToMarkdown(data.plan || {});
            showResults();
            setStatus(
                data.status === "mock"
                    ? "Demo-mode draft ready (mock generation, no live model). Review and edit before teaching."
                    : "Draft ready. Review and edit before teaching.",
                "ok"
            );
            statusRegion.focus();
        } catch (error) {
            hideResults();
            if (error.name === "AbortError") {
                showRefusal(
                    "provider_error",
                    "The request timed out after " + REQUEST_TIMEOUT_MS / 1000 + " seconds. " +
                    "The server may be running in live mode with an unreachable provider or a " +
                    "missing OPENAI_BASE_URL. Check the .env settings and restart python app.py, " +
                    "or set MOCK_MODE=1 for an instant offline draft."
                );
                setStatus("The request timed out. See the details panel.", "error");
            } else {
                showRefusal("provider_error", error.message || "The draft could not be generated.");
                setStatus("The draft could not be generated.", "error");
            }
            statusRegion.focus();
        } finally {
            window.clearTimeout(giveUpTimer);
            window.clearInterval(elapsedTimer);
            setLoading(false);
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitGeneration();
    });

    const fileInput = document.getElementById("files");
    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files.length > 0) {
            setStatus(
                "Reminder: do not upload student records, grades, or coursework — " +
                "reference files must be curriculum material only.",
                null
            );
        }
    });

    /* Show the Demo mode badge as soon as the page learns the server runs in mock
       mode — checked at load via /api/health, and re-confirmed after each response. */
    async function refreshModeBadge() {
        try {
            const response = await fetch("/api/health");
            if (response.ok) {
                const data = await response.json();
                demoBadge.hidden = data.mode !== "mock";
            }
        } catch {
            /* health unavailable: keep the badge as-is */
        }
    }
    refreshModeBadge();

    regenerateButton.addEventListener("click", () => submitGeneration());

    /* ---------------- buttons ---------------- */

    sampleButton.addEventListener("click", () => {
        form.reset();
        document.getElementById("topic").value = sampleBrief.topic;
        document.getElementById("duration").value = sampleBrief.duration;
        document.getElementById("target-level").value = sampleBrief.target_level;
        document.getElementById("brief").value = sampleBrief.brief;
        document.getElementById("activity-types").value = sampleBrief.activity_types;
        document.getElementById("pacing").value = sampleBrief.pacing_preferences;
        document.getElementById("buffer").value = sampleBrief.buffer_preference;
        hideRefusal();
        setStatus("Sample brief loaded. Adjust it, then generate.", null);
    });

    const presets = {
        stem: {
            topic: "Problem-solving with Newton's method",
            duration: "50 mins",
            target_level: "1st Year Undergrad STEM",
            brief: "Learners iteratively approximate a root using Newton's method, starting from a graph sketch. Worked example first, then pairs solve a second function and compare convergence behaviour.",
            activity_types: "worked example, pair problem-solving",
            pacing_preferences: "slow start, steady transitions",
            buffer_preference: "auto"
        },
        essay: {
            topic: "Argument structure in persuasive essays",
            duration: "60 mins",
            target_level: "2nd Year Humanities",
            brief: "Discuss how claims, evidence, and warrants combine in a persuasive essay. Learners annotate a sample paragraph in small groups, then draft one counter-argument paragraph individually.",
            activity_types: "group discussion, annotation, individual drafting",
            pacing_preferences: "extended discussion time",
            buffer_preference: "10"
        },
        lab: {
            topic: "Titration technique and endpoint detection",
            duration: "90 mins",
            target_level: "1st Year Laboratory Science",
            brief: "Demonstrate a strong acid-strong base titration, highlighting burette handling and endpoint judgement. Learners then repeat the procedure in pairs and record three concordant titres.",
            activity_types: "demonstration, hands-on lab pairs",
            pacing_preferences: "ample time for the practical block",
            buffer_preference: "auto"
        }
    };

    document.querySelectorAll("[data-preset]").forEach((button) => {
        button.addEventListener("click", () => {
            const preset = presets[button.dataset.preset];
            if (!preset) return;
            document.getElementById("topic").value = preset.topic;
            document.getElementById("duration").value = preset.duration;
            document.getElementById("target-level").value = preset.target_level;
            document.getElementById("brief").value = preset.brief;
            document.getElementById("activity-types").value = preset.activity_types;
            document.getElementById("pacing").value = preset.pacing_preferences;
            document.getElementById("buffer").value = preset.buffer_preference;
            hideRefusal();
            setStatus("Preset '" + preset.topic + "' loaded. Adjust it, then generate.", null);
        });
    });

    clearButton.addEventListener("click", () => {
        form.reset();
        hideResults();
        hideRefusal();
        setStatus("Form cleared. Your generated lesson plan will appear here.", null);
    });

    copyButton.addEventListener("click", async () => {
        if (!currentPlan) return;
        const text = planToMarkdown(currentPlan);
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
            } else {
                const scratch = el("textarea");
                scratch.value = text;
                scratch.setAttribute("readonly", "");
                scratch.style.position = "fixed";
                scratch.style.left = "-9999px";
                document.body.appendChild(scratch);
                scratch.select();
                document.execCommand("copy");
                document.body.removeChild(scratch);
            }
            setStatus("Draft copied to your clipboard.", "ok");
        } catch {
            setStatus("Copy was unavailable in this browser. Use the Raw Markdown tab to select and copy.", "error");
        }
    });

    exportButton.addEventListener("click", () => {
        if (!currentPlan) return;
        const text = planToMarkdown(currentPlan);
        const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = el("a");
        link.href = url;
        link.download = "lesson-plan-" + slugify(currentPlan.topic) + ".md";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setStatus("Markdown exported.", "ok");
    });
})();

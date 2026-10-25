# Lesson-Plan Scaffolder

A Flask web application, where a tutor pastes a short teaching
brief (topic, duration, audience, context, optional reference files), and the tool
generates a structured lesson-plan draft — learning objectives, a time allocation, a
lesson outline, and tutor check-questions — in an **editable three-column workspace**
with a live total-time calculator and buffer-time indicator.

Generation runs through a **live LLM** (`pi_python.Agent` + `OpenAICompletionsProvider`).
A deterministic **mock mode** gives the same output shape offline, for testing and demos.

**Target user:** university tutors and teaching staff. The tool supports — and never
replaces — tutor judgment.

## This tool does not

1. Assess, grade, or store data or rosters of real students.
2. Accept official student coursework or personally identifiable information (PII).
3. Claim or certify that a draft is an officially accredited curriculum.

Requests that touch these boundaries are refused (HTTP 400 `safety_refusal`); impossible
or overloaded briefs are refused too (HTTP 422 `feasibility_refusal`). Refusal messages
name the category only — they never echo your text. Every draft carries:
*"Preliminary, non-accredited draft; tutor review required."*

## How it works

```
Web form (brief + optional files)
  → Flask API            validate fields, scan for PII/prohibited content
  → files.py             allowlist + size checks, text extraction, sanitization
  → plans.py             duration parsing, buffer math, feasibility check
  → agent_service.py     live LLM via pi_python; .pi/ skill, context, and MCP reader
                         injected; uploads passed as delimited UNTRUSTED data
  → post-process         parse Markdown → structured plan → repair/retry → re-scan
  → JSON response        { status, draft, plan, sources, warnings, meta }
  → Editable workspace   tutor reviews, edits, copies, exports Markdown, regenerates
```

Only `agent_service.py` imports `pi_python`. The MCP curriculum reader
(`mcp_curriculum_server.py`) is **read-only** and confined to `data/references/`.

## Setup

Python 3.10+ (verified on 3.14).

```bash
git clone <this repo> && cd <repo name>
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit .env  (see table below)
python app.py                      # open http://127.0.0.1:5000
```

No API key? Just skip the key and the app runs in mock mode automatically.

## Configuration (`.env`)

`.env` is git-ignored; you create it from `.env.example` after cloning. All variables
are optional unless noted. **Variable names must match exactly** (including the
`OPENAI_` prefix) — unknown names are silently ignored — and the file is read only at
startup, so **restart `python app.py` after editing it**. Provider settings are read
only inside `agent_service.py`; secrets are never logged.

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | *(empty)* | **Required for live generation.** API key for the provider. If empty (or `MOCK_MODE=1`), the app uses the deterministic mock path and the UI shows a "Demo mode" badge. |
| `BASE_URL` | `https://api.openai.com/v1` | Root URL of any OpenAI-compatible `/chat/completions` endpoint (e.g. Ollama `http://localhost:11434/v1`, vLLM, Azure-compatible gateways). |
| `MODEL` | `gpt-4o-mini` | Model name sent to the endpoint. Custom models are declared automatically with safe context/output limits, so unknown names still work. |
| `TEMPERATURE` | `0` | Sampling temperature. `0` = most deterministic drafts; raise for more varied wording. |
| `TIMEOUT_SECONDS` | `60` | Per-request HTTP timeout for the provider. On timeout the API returns a friendly 502 `provider_error`. |
| `MAX_OUTPUT_TOKENS` | `2000` | Cap on the model's output length per draft. |
| `MOCK_MODE` | `1` | `1` forces the offline mock path even when an API key is set (used by CI/tests). |
| `MCP_ENABLED` | `1` | `1` starts the read-only MCP curriculum reader from `.pi/mcp.json` and gives the agent its tools. `0` skips MCP. If the server fails to start, generation continues without it and a warning is returned. |
| `MCP_REQUIRED` | `0` | `1` makes a failed MCP start a hard error (502) instead of a warning. |
| `SESSION_RETENTION_HOURS` | `24` | Uploaded reference files are kept under `data/references/uploads/<session>/` for this many hours, then swept at startup and before each request. Refusals delete immediately. |
| `FLASK_DEBUG` | `0` | `1` enables Flask's debug reloader (development only). |
| `SECRET_KEY` | `change-me` | Reserved for Flask sessions. The app is stateless today, so this value is not used at runtime; keep a random one if you later add sessions. |

## Trying it out

Three quick cases (from the UI, or with curl against `POST /api/generate`):

1. **Positive:** topic *"Fraud detection with decision trees"*, duration `50 mins`,
   audience `1st Year Undergrad`, a short worked-example brief, buffer `auto`.
   Expect `status` `mock`/`ok`, 2–5 objectives, 4 blocks summing to usable minutes
   (50 − 5 = 45), ≥3 check-questions, and the disclaimer.
2. **Safety refusal:** a brief containing *"student grades"* or *"roster"*.
   Expect HTTP 400, `error.code == "safety_refusal"`, no draft, no echo of the phrase.
3. **Feasibility refusal:** duration `15 mins` asking for *"10 learning objectives"*.
   Expect HTTP 422, `error.code == "feasibility_refusal"`, with an explanation.

`GET /api/health` reports `{"status":"ok","mode":"live"|"mock","mcp_enabled":…}`.

## Testing

```bash
MOCK_MODE=1 pytest -q          # PowerShell: $env:MOCK_MODE='1'; pytest -q
```

100 offline tests cover validation and PII scans, duration/buffer/allocation math,
feasibility refusals, upload rules and cleanup, and the full API contract in mock mode.
`tests/fake_openai_server.py` is an optional helper: a fake OpenAI-compatible SSE
endpoint for exercising the live path offline (set `OPENAI_BASE_URL` to it).

## Uploads, privacy, and MCP

- Uploads: `.pdf .docx .txt .md` only, ≤10 MB each, ≤5 per request, ≤25 MB total;
  magic-byte checked; stored outside the web root with randomized names; text capped at
  20,000 chars/file, sanitized, and scanned before use. File contents are never logged.
- Briefs and reference text are **sent to the configured LLM provider**. Never upload
  student records, grades, or coursework — the UI warns before upload.
- Uploaded/MCP text is wrapped in `<<<UNTRUSTED_REFERENCE_MATERIAL ...>>>` and treated
  as data, never as instructions (prompt-injection guard).
- `data/references/` is the MCP reader's root (a sample `_smoke.md` is included). The
  server exposes only read/list/search tools and rejects paths outside the root.

## pi_python compatibility

Verified 2026-10-25 with `pi-python-core[mcp]==0.11.0` (import name `pi_python`,
v0.11.0) on Python 3.14.3.

- Agent: `pi_python.Agent(provider=…, model=…, system_prompt=…, options=…)`; the app
  uses `prompt_sync()`, which returns a `RunResult` (`.status`, `.messages`, `.usage`).
- Provider: `OpenAICompletionsProvider(base_url=…, api_key=…, transport=…)` with the
  timeout set through `HTTPTransport(timeout=…)`; the configured model is declared with
  `provider.model(id, max_tokens=MAX_OUTPUT_TOKENS)` because this provider never guesses
  model capabilities.
- `.pi` loading: `.pi/` is loaded as a `pi_python` plugin (`load_plugins`), which
  registers the skill (SKILL.md carries the required `name`/`description` frontmatter)
  and starts the MCP server defined in `.pi/mcp.json` (`${PYTHON}` / `${PLUGIN_ROOT}`
  are expanded by the loader). Context and skill text are additionally injected into
  the system prompt in the fixed order.

`mcp-server-filesystem` **does not exist on PyPI** (verified with `pip index versions`),
and the nearest package is not read-only, so the curriculum reader is the repo-local
`mcp_curriculum_server.py` built on the `mcp>=2.3,<3` SDK.

## Ethics and limitations

- Drafts are a **starting point, not a script** — your real-time judgment wins; the UI
  keeps this notice visible. Buffer time (auto: 5 min per 30) exists so rigid pacing
  does not crowd out learning.
- Non-accredited output; tutor review required; live quality varies with the model.
- Streaming responses, PDF export, and rubric self-scoring are not implemented. Presets,
  density flag, and the pre-class checklist **are** implemented.
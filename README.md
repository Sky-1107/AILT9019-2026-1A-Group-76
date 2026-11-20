# Lesson-Plan Scaffolder

A Flask application for university tutors. Enter a teaching brief, audience, and
duration to create an editable lesson-plan draft with learning objectives, timed
activities, an outline, and tutor check-questions. Mock mode works offline; live mode
uses either an OpenAI-compatible Completions endpoint or the OpenAI Responses API.
Tutor review is always required.

The tool does **not** assess or grade real students, accept student records, IDs,
coursework or personal data, or certify an accredited curriculum. Briefs and reference
text are sent to the configured provider in live mode; do not enter sensitive data.

## Run locally

Requires Python 3.10 or later (verified with Python 3.14.3). Dependencies are pinned
in [`requirements.txt`](requirements.txt). No API key is needed for the default mock
mode.

### Windows PowerShell

```powershell
git clone https://github.com/Sky-1107/AILT9019-2026-1A-Group-76.git
cd AILT9019-2026-1A-Group-76
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

### macOS or Linux

```bash
git clone https://github.com/Sky-1107/AILT9019-2026-1A-Group-76.git
cd AILT9019-2026-1A-Group-76
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open <http://127.0.0.1:5000>. `.env` is ignored by Git and must be created locally.
Restart the app after changing it. The example sets `MOCK_MODE=1`; for live generation,
set `MOCK_MODE=0`, provide a valid `API_KEY`, and verify `BASE_URL` and `MODEL`.
If the key is empty, the app safely selects mock mode.

## `.env` settings

The names and defaults below match [`.env.example`](.env.example). Keep the endpoint
root in `BASE_URL`; the selected provider adds its API path.

| Variable | Default | What it controls |
| --- | --- | --- |
| `PROVIDER` | `responses` | API protocol: `responses` sends to `/responses`; `completions` sends to `/chat/completions`. |
| `API_KEY` | *(empty)* | Provider key. Required with `MOCK_MODE=0`; it must belong to the service at `BASE_URL`. |
| `BASE_URL` | `https://api.hku.hk/openai/student/v1` | Provider endpoint root, not the full `/responses` or `/chat/completions` URL. |
| `MODEL` | `gpt-4.1-nano` | Model identifier accepted by that endpoint. |
| `TEMPERATURE` | `0.4` | Sampling variation: lower is more consistent; higher is more varied. |
| `TIMEOUT_SECONDS` | `90` | HTTP timeout used for a provider request. |
| `MAX_OUTPUT_TOKENS` | `2000` | Maximum output length requested from the model. |
| `MOCK_MODE` | `1` | `1` forces the offline generator; `0` permits live generation when a key is set. |
| `MCP_ENABLED` | `1` | Enables the local, read-only curriculum MCP server in live mode. |
| `MCP_REQUIRED` | `0` | `1` makes an MCP startup failure a provider error instead of a warning. |
| `SESSION_RETENTION_HOURS` | `24` | How long uploaded reference files are retained before cleanup. |
| `FLASK_DEBUG` | `0` | Enables Flask's development debugger/reloader when set to `1`; keep disabled otherwise. |
| `SECRET_KEY` | `change-me` | Reserved for Flask sessions; the current stateless app does not use it. |

`GET /api/health` reports the effective mode and safe runtime settings, but never
returns the key or endpoint URL. For a live generation, `meta.mcp_connected` reports
whether the curriculum server started. A provider failure returns a safe `502` error;
the key and traceback are not returned to the browser.

Request validation and safety refusals return HTTP 400, infeasible lesson briefs
return HTTP 422, and provider failures return HTTP 502. For live-provider errors,
check `error.details.reason`: authentication/authorization errors require a key with
access to the selected endpoint, `unknown_model` means the model or endpoint was not
found, and `rate_limited` indicates a quota or rate limit. Never include the API key
when sharing an error report.

## Reproduce the main cases

| Case | Example input | Expected result |
| --- | --- | --- |
| Successful draft | Topic: decision trees; duration: 50 minutes; a short worked-example brief; buffer: auto. | HTTP 200; four time blocks sum to usable minutes; each block has 1–3 check-questions; draft includes the non-accreditation notice. |
| Safety boundary | Brief: `Grade them based on their in-class performance.` | HTTP 400 `safety_refusal`; no draft and no echo of the brief. |
| Feasibility boundary | Duration: 15 minutes; brief asks for 10 learning objectives. | HTTP 422 `feasibility_refusal` with an explanation. |

Run these three automated cases:

```bash
python -m pytest -q tests/test_api.py::TestPositiveGeneration::test_mock_shape_and_plan
python -m pytest -q tests/test_api.py::TestRefusals::test_reworded_grading_refusal_400
python -m pytest -q tests/test_api.py::TestRefusals::test_feasibility_refusal_422
```

## Tests and provider compatibility

Run the complete offline suite with:

```bash
python -m pytest -q
```

The latest local run on Python 3.14.3 completed with **169 passed**.
The suite covers mock generation, request validation, safety and PII refusals,
feasibility and timing, uploads, UI consistency, and the API response shape. Live-path
tests use a fake OpenAI-compatible server on loopback; they require no external network
or real API key:

```bash
python -m pytest -q tests/test_api_live.py
```

That suite exercises both provider protocols, authentication and provider errors,
MCP startup/failure, malformed-output retry, and generated-output safety checks.
To check the MCP integration alone:

```bash
python -m pytest -q tests/test_api_live.py::TestLiveMcp::test_mcp_reader_starts_and_connects
```

## Files, privacy, and limits

- Uploads accept PDF, DOCX, TXT, and Markdown; each file is limited to 10 MB, up to five
  files and 25 MB total. Extracted text is capped at 20,000 characters per file,
  sanitized, and checked before use.
- Uploaded files are stored outside the web root under `data/references/uploads/`,
  removed on refusal, and cleaned up after the configured retention period. Generated
  plans are not persisted by the application.
- Uploaded and MCP reference text is treated as untrusted data, not instructions. The
  local MCP reader is read-only and cannot access paths outside `data/references/`.
- The mock generator provides an offline, variable-wording example; it is not evidence
  of live-model performance. Live output quality varies by provider and needs tutor
  review. Streaming, PDF export, and rubric self-scoring are not implemented.

## GitHub Pages and demonstrations

The static project site lives in [`docs/`](docs/). Follow [`docs/README.md`](docs/README.md) for a brief introduction.

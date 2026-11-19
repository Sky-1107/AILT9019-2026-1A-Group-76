"""Fake OpenAI-compatible SSE endpoint used to validate live agent paths offline.

Serves both /chat/completions and /responses so tests can drive different
behaviours (the selected provider appends its endpoint to BASE_URL):

    /v1/          every request returns the streamed lesson-plan draft
    /v1-retry/    first request returns malformed text, later ones the good draft
                  (drives the one corrective-retry path)
    /v1-bad/      always returns a draft that violates the safety boundaries
                  (drives the output re-scan refusal)
    /v1-auth/     every request is rejected with HTTP 401 invalid_api_key
                  (drives the provider-failure message classification)
    /v1-topic/    returns a draft whose SUBJECT is handling student/personal
                  data (topic vocabulary only) — the output re-scan must accept it
    /v1-freestyle/ returns a real-world reasoning-model draft that ignores the
                  skill schema (custom headings, inline "**Time:** N minutes");
                  the salvage parser must handle it in ONE call, no retry

GET /stats reports per-path request counts. Run standalone for manual checks:
python tests/fake_openai_server.py [port]
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DRAFT_LINES = [
    "# Lesson Plan Draft: Test Topic",
    "",
    "## Learning Objectives",
    "",
    "- LO1: Apply the core method to a worked example (bloom: apply)",
    "- LO2: Analyse two competing approaches (bloom: analyze)",
    "",
    "## Time Allocation",
    "",
    "| Phase | Minutes | Tutor focus |",
    "| --- | ---: | --- |",
    "| Hook | 5 | Pose the opening puzzle. |",
    "| Core Concept | 20 | Model the method step by step. |",
    "| Interactive Exercise | 15 | Pairs solve a fresh example. |",
    "| Wrap-up | 5 | Exit ticket and recap. |",
    "",
    "## Lesson Outline",
    "",
    "### Hook (5 min)",
    "",
    "Pose the opening puzzle about the topic.",
    "",
    "## Tutor Check-Questions",
    "",
    "- What is the key idea here?",
    "- Where would this break down?",
    "- How would you explain it to a peer?",
    "- What clue in the example supports your conclusion?",
    "",
    "Preliminary, non-accredited draft; tutor review required.",
]

GOOD_DRAFT = "\n".join(DRAFT_LINES)

# No required sections at all: forces the live path's one corrective retry.
MALFORMED_DRAFT = (
    "Sorry, here is a friendly paragraph about lessons instead, with no headings, "
    "objectives, or time table anywhere in it."
)

# Captured from a real reasoning model (qwen) that ignored the skill's schema:
# its own headings and inline durations instead of a Time Allocation table.
FREESTYLE_DRAFT = "\n".join(
    [
        "# Lesson Plan: Introduction to Fractions",
        "",
        "**Duration:** 50 minutes",
        "",
        "## Learning Objectives",
        "",
        "- Understand what a fraction represents.",
        "- Identify the numerator and denominator in a fraction.",
        "- Recognise fractions in real-life contexts.",
        "",
        "# Lesson Structure",
        "",
        "## 1. Starter Activity: What Is a Fraction?",
        "",
        "**Time:** 5 minutes",
        "",
        "Show an image divided into equal parts.",
        "",
        "## 2. Explanation: Numerator and Denominator",
        "",
        "**Time:** 10 minutes",
        "",
        "Model labelling parts of a fraction.",
        "",
        "## 3. Main Activity 1: Shading Fractions",
        "",
        "**Time:** 12 minutes",
        "",
        "Learners shade fraction strips.",
        "",
        "## 4. Plenary: Exit Ticket",
        "",
        "**Time:** 7 minutes",
        "",
        "Ask: Which part of today's lesson was most useful?",
        "Were equal parts clear to all students?",
        "",
        "Preliminary, non-accredited draft; tutor review required.",
    ]
)

# A structurally valid draft that crosses a safety boundary: the server's output
# re-scan must turn this into a 400 safety_refusal before it reaches the client.
# A draft about data protection: it contains topic vocabulary ("student data",
# "personal records", "assess ... risk") that the intent/vocabulary rules would
# flag in a *request*, but which is legitimate subject matter in a *draft*.
TOPIC_VOCABULARY_DRAFT = GOOD_DRAFT.replace(
    "Pose the opening puzzle about the topic.",
    "Pose the opening puzzle: how do we protect student data and personal "
    "records? Learners assess whether a transaction shows fraud risk.",
)

# A structurally valid draft that crosses a hard output boundary: claiming the
# draft is an accredited curriculum. The output re-scan must turn this into a
# 400 safety_refusal before it reaches the client. (Ordinary topic vocabulary
# such as "student data" is deliberately NOT a violation here.)
BAD_OUTPUT_DRAFT = GOOD_DRAFT.replace(
    "Pose the opening puzzle about the topic.",
    "Pose the opening puzzle about the topic. This lesson is an accredited "
    "curriculum and needs no tutor review.",
)

_lock = threading.Lock()
_request_counts: dict[str, int] = {}


def reset_stats() -> None:
    with _lock:
        _request_counts.clear()


def _count(key: str) -> int:
    with _lock:
        _request_counts[key] = _request_counts.get(key, 0) + 1
        return _request_counts[key]


def _scenario(path: str) -> str:
    """Normalize a request path to its scenario bucket name."""
    for name in ("freestyle", "retry", "bad", "auth", "topic", "total"):
        if f"/v1-{name}/" in path:
            return name
    return "good"


def _draft_for(path: str) -> str:
    # Count every chat request under its scenario so tests can assert the exact
    # number of provider calls (e.g. "no corrective retry" == count 1).
    count = _count(_scenario(path))
    if "/v1-freestyle/" in path:
        return FREESTYLE_DRAFT if count == 1 else GOOD_DRAFT
    if "/v1-topic/" in path:
        return TOPIC_VOCABULARY_DRAFT
    if "/v1-bad/" in path:
        return BAD_OUTPUT_DRAFT
    if "/v1-retry/" in path:
        return MALFORMED_DRAFT if count == 1 else GOOD_DRAFT
    return GOOD_DRAFT


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stats endpoint for assertions
        if self.path == "/stats":
            with _lock:
                payload = json.dumps(dict(_request_counts)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        is_responses = self.path.endswith("/responses")
        is_completions = self.path.endswith("/chat/completions")
        if not (is_responses or is_completions):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")

        if "/v1-header/" in self.path and (
            not self.headers.get("api-key")
            or not self.headers.get("Authorization", "").startswith("Bearer ")
        ):
            self._send_json(
                401,
                {
                    "error": {
                        "message": "Both API authentication headers are required.",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )
            return

        if "/v1-auth/" in self.path:
            # Mirrors a real provider rejection: the error body never contains
            # the caller's key, so it is safe to surface the status code.
            self._send_json(
                401,
                {
                    "error": {
                        "message": "Invalid API-key provided.",
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )
            return

        draft = _draft_for(self.path)

        if is_responses:
            item = {
                "id": "msg-test",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": draft, "annotations": []}
                ],
            }
            events = [
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "id": "msg-test",
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_text.delta",
                    "output_index": 0,
                    "delta": draft,
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": item,
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-test",
                        "object": "response",
                        "status": "completed",
                        "model": body.get("model", "gpt-4o-mini"),
                        "output": [item],
                        "usage": {"input_tokens": 100, "output_tokens": 200},
                    },
                },
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for event in events:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
            return

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            words = draft.split(" ")
            for index, word in enumerate(words):
                piece = word + (" " if index < len(words) - 1 else "")
                chunk = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "model": body.get("model", "gpt-4o-mini"),
                    "choices": [
                        {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                    ],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            final = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "model": body.get("model", "gpt-4o-mini"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": len(words),
                    "total_tokens": 100 + len(words),
                },
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            response = {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": body.get("model", "gpt-4o-mini"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": draft},
                        "finish_reason": "stop",
                    }
                ],
            }
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, *args):  # quiet
        pass


def serve_in_thread() -> ThreadingHTTPServer:
    """Start the fake endpoint on an ephemeral 127.0.0.1 port (loopback only)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    running = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake openai server on http://127.0.0.1:{port}/v1", flush=True)
    running.serve_forever()

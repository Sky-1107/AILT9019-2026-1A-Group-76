"""Fake OpenAI-compatible SSE endpoint used to validate the live agent path offline.

Run: python tests/fake_openai_server.py [port]
Responds to POST /v1/chat/completions with a streamed lesson-plan draft.
"""

from __future__ import annotations

import json
import sys
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
    "",
    "Preliminary, non-accredited draft; tutor review required.",
]

DRAFT = "\n".join(DRAFT_LINES)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            words = DRAFT.split(" ")
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
                        "message": {"role": "assistant", "content": DRAFT},
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


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake openai server on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()

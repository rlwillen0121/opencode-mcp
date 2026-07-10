"""Small HTTP MCP facade that dispatches asynchronous OpenCode jobs.

The server intentionally keeps tool calls short: `coding_task_start` records a
job, launches OpenCode in the background, and returns a durable job id. Clients
poll `coding_task_status` or fetch `coding_task_result` later.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "opencode-mcp"
SERVER_VERSION = "0.1.0"
MAX_OUTPUT_CHARS = 120_000


@dataclasses.dataclass
class Job:
    id: str
    prompt: str
    cwd: str
    status: str = "queued"
    created_at: float = dataclasses.field(default_factory=time.time)
    updated_at: float = dataclasses.field(default_factory=time.time)
    command: list[str] = dataclasses.field(default_factory=list)
    returncode: int | None = None
    output: str = ""
    error: str | None = None
    continue_notes: list[str] = dataclasses.field(default_factory=list)
    process: subprocess.Popen[str] | None = dataclasses.field(default=None, repr=False)

    def public(self, include_output: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "command": self.command,
            "returncode": self.returncode,
            "error": self.error,
            "continue_notes": self.continue_notes,
        }
        if include_output:
            data["output"] = self.output
        else:
            data["output_tail"] = self.output[-8000:]
        return data


class JobStore:
    def __init__(self, opencode_bin: str, default_cwd: str) -> None:
        self.opencode_bin = opencode_bin
        self.default_cwd = default_cwd
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, prompt: str, cwd: str | None = None, extra_args: list[str] | None = None) -> Job:
        job_id = uuid.uuid4().hex
        workdir = str(Path(cwd or self.default_cwd).expanduser().resolve())
        command = [self.opencode_bin, "run", prompt, *(extra_args or [])]
        job = Job(id=job_id, prompt=prompt, cwd=workdir, command=command)
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._jobs[job_id]

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        with self._lock:
            if job.status in {"succeeded", "failed", "cancelled"}:
                return job
            job.status = "cancelling"
            job.updated_at = time.time()
            process = job.process
        if process and process.poll() is None:
            process.send_signal(signal.SIGTERM)
        return job

    def add_continue_note(self, job_id: str, prompt: str) -> Job:
        job = self.get(job_id)
        with self._lock:
            job.continue_notes.append(prompt)
            job.updated_at = time.time()
        return job

    def _run_job(self, job: Job) -> None:
        if not shutil.which(self.opencode_bin):
            with self._lock:
                job.status = "failed"
                job.error = f"OpenCode binary not found: {self.opencode_bin}"
                job.updated_at = time.time()
            return
        try:
            with self._lock:
                job.status = "running"
                job.updated_at = time.time()
            process = subprocess.Popen(
                job.command,
                cwd=job.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self._lock:
                job.process = process
            assert process.stdout is not None
            for line in process.stdout:
                with self._lock:
                    job.output = (job.output + line)[-MAX_OUTPUT_CHARS:]
                    job.updated_at = time.time()
            returncode = process.wait()
            with self._lock:
                job.returncode = returncode
                if job.status == "cancelling":
                    job.status = "cancelled"
                else:
                    job.status = "succeeded" if returncode == 0 else "failed"
                job.updated_at = time.time()
        except Exception as exc:  # noqa: BLE001 - surface failure to MCP client
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = time.time()


TOOLS: list[dict[str, Any]] = [
    {
        "name": "coding_task_start",
        "description": "Start an asynchronous OpenCode coding job and return immediately with a job id.",
        "inputSchema": {
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string", "description": "Repository/worktree path for the job."},
                "extra_args": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "coding_task_status",
        "description": "Return current status and recent output for a coding job.",
        "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}},
    },
    {
        "name": "coding_task_result",
        "description": "Return the full retained output and final metadata for a coding job.",
        "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}},
    },
    {
        "name": "coding_task_continue",
        "description": "Attach follow-up instructions to a job. Notes are retained for operators and future adapters.",
        "inputSchema": {"type": "object", "required": ["job_id", "prompt"], "properties": {"job_id": {"type": "string"}, "prompt": {"type": "string"}}},
    },
    {
        "name": "coding_task_cancel",
        "description": "Cancel a running coding job.",
        "inputSchema": {"type": "object", "required": ["job_id"], "properties": {"job_id": {"type": "string"}}},
    },
]


def content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


def handle_tool(store: JobStore, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "coding_task_start":
        job = store.start(args["prompt"], args.get("cwd"), args.get("extra_args"))
        return content(job.public())
    if name == "coding_task_status":
        return content(store.get(args["job_id"]).public())
    if name == "coding_task_result":
        return content(store.get(args["job_id"]).public(include_output=True))
    if name == "coding_task_continue":
        return content(store.add_continue_note(args["job_id"], args["prompt"]).public())
    if name == "coding_task_cancel":
        return content(store.cancel(args["job_id"]).public())
    raise ValueError(f"unknown tool: {name}")


class MCPHandler(BaseHTTPRequestHandler):
    store: JobStore

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/healthz"}:
            self._send(HTTPStatus.OK, {"ok": True, "server": SERVER_NAME})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/mcp":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            response = self._jsonrpc(request)
            self._send(HTTPStatus.OK, response)
        except Exception as exc:  # noqa: BLE001 - JSON-RPC error response
            self._send(HTTPStatus.OK, {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}})

    def _jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = handle_tool(self.store, params["name"], params.get("arguments") or {})
        elif method == "notifications/initialized":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.environ.get("OPENCODE_MCP_DEBUG"):
            super().log_message(format, *args)


def build_server(host: str, port: int, store: JobStore) -> ThreadingHTTPServer:
    handler = type("ConfiguredMCPHandler", (MCPHandler,), {"store": store})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run an asynchronous OpenCode MCP dispatcher")
    parser.add_argument("--host", default=os.environ.get("OPENCODE_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OPENCODE_MCP_PORT", "8765")))
    parser.add_argument("--opencode-bin", default=os.environ.get("OPENCODE_BIN", "opencode"))
    parser.add_argument("--cwd", default=os.environ.get("OPENCODE_MCP_CWD", os.getcwd()))
    args = parser.parse_args(argv)
    server = build_server(args.host, args.port, JobStore(args.opencode_bin, args.cwd))
    print(f"{SERVER_NAME} listening on http://{args.host}:{args.port}/mcp", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

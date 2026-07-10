from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from opencode_mcp.server import JobStore, build_server, handle_tool


def test_tool_lifecycle_with_python_executable(tmp_path, monkeypatch):
    fake = tmp_path / "opencode"
    fake.write_text("#!/usr/bin/env sh\necho job:$1 prompt:$2\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}" + os.environ.get("PATH", ""))
    store = JobStore("opencode", str(tmp_path))
    result = handle_tool(store, "coding_task_start", {"prompt": "hello"})
    payload = json.loads(result["content"][0]["text"])
    job_id = payload["job_id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        status = store.get(job_id).public(include_output=True)
        if status["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.05)

    final = store.get(job_id).public(include_output=True)
    assert final["status"] == "succeeded"
    assert "job:run prompt:hello" in final["output"]


def test_http_tools_list(tmp_path):
    server = build_server("127.0.0.1", 0, JobStore(sys.executable, str(tmp_path)))
    port = server.server_address[1]
    try:
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read())
        names = {tool["name"] for tool in body["result"]["tools"]}
        assert "coding_task_start" in names
        assert "coding_task_status" in names
    finally:
        server.shutdown()

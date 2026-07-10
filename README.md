# OpenCode MCP Dispatcher

A small HTTP MCP server that lets Amazon Quick or another MCP host delegate
coding work to OpenCode without relying on an ACP bridge.

The server exposes a durable, asynchronous job API. `coding_task_start` launches
OpenCode in the background and returns a job id immediately, which keeps each MCP
tool call short. Clients can poll for status, fetch retained output, attach
follow-up notes, or cancel the subprocess.

## Tools

| Tool | Purpose |
| --- | --- |
| `coding_task_start` | Start an OpenCode job asynchronously and return `job_id`. |
| `coding_task_status` | Return status, metadata, and recent output tail. |
| `coding_task_result` | Return full retained output and final metadata. |
| `coding_task_continue` | Record follow-up instructions for the job. |
| `coding_task_cancel` | Send `SIGTERM` to a running OpenCode process. |

## Run locally

```bash
python -m opencode_mcp.server --host 127.0.0.1 --port 8765 --cwd /path/to/repo
```

Environment variables:

- `OPENCODE_BIN`: OpenCode executable name or absolute path. Defaults to
  `opencode`.
- `OPENCODE_MCP_HOST`: bind host. Defaults to `127.0.0.1`.
- `OPENCODE_MCP_PORT`: bind port. Defaults to `8765`.
- `OPENCODE_MCP_CWD`: default working directory for jobs. Defaults to the
  process working directory.
- `OPENCODE_MCP_DEBUG`: when set, enables HTTP request logging.

## Quick / remote MCP shape

Point the MCP client at:

```text
http://<host>:8765/mcp
```

This implementation uses JSON-RPC over HTTP and implements the core methods
needed by MCP clients:

- `initialize`
- `tools/list`
- `tools/call`
- `notifications/initialized`

For corporate source code, prefer running this inside an approved environment
that can clone repositories into isolated worktrees. Avoid exposing a local
workstation runner through a public tunnel.

## Example JSON-RPC calls

```bash
curl -s http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```bash
curl -s http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"coding_task_start","arguments":{"prompt":"Fix the failing tests","cwd":"/path/to/repo"}}}'
```

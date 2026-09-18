# opencode-mcp

HTTP MCP server that runs **OpenCode jobs in the background** and gives the host a job id immediately.

OpenCode runs are long. MCP tool calls should not be. This dispatcher starts `opencode run`, returns, and lets the client poll for status, output, or cancel.

Works with any MCP host that can call a JSON-RPC HTTP endpoint (Claude Desktop, Cursor, Amazon Q, custom agents).

## Tools

| Tool | Purpose |
| --- | --- |
| `coding_task_start` | Launch `opencode run <prompt>` and return `job_id` |
| `coding_task_status` | Status, metadata, and an output tail |
| `coding_task_result` | Full retained output (capped) plus final metadata |
| `coding_task_continue` | Store a follow-up note on the job (not piped into the running process) |
| `coding_task_cancel` | `SIGTERM` a running OpenCode process |

Jobs live in memory for the life of the process. Restarting the server drops them.

## Requirements

- Python 3.11+
- [OpenCode](https://github.com/sst/opencode) on `PATH`, or pass `--opencode-bin`

## Install

```bash
git clone https://github.com/rlwillen0121/opencode-mcp.git
cd opencode-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

No extra runtime dependencies. The server is stdlib-only.

## Run

```bash
python -m opencode_mcp.server --host 127.0.0.1 --port 8765 --cwd /path/to/repo
```

or:

```bash
opencode-mcp --host 127.0.0.1 --port 8765 --cwd /path/to/repo
```

MCP endpoint: `http://127.0.0.1:8765/mcp`  
Health: `GET /health` or `GET /healthz`

### Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `OPENCODE_BIN` | `opencode` | Binary name or absolute path |
| `OPENCODE_MCP_HOST` | `127.0.0.1` | Bind address |
| `OPENCODE_MCP_PORT` | `8765` | Bind port |
| `OPENCODE_MCP_CWD` | process cwd | Default workdir for jobs |
| `OPENCODE_MCP_DEBUG` | unset | Log HTTP requests when set |

CLI flags override the matching env vars (`--host`, `--port`, `--opencode-bin`, `--cwd`).

## Point an MCP client at it

JSON-RPC over HTTP. Implemented methods: `initialize`, `tools/list`, `tools/call`, `notifications/initialized`.

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

Poll with `coding_task_status` / `coding_task_result` using the returned `job_id`.

## Security

There is **no authentication**. Bind to loopback.

- Default host is `127.0.0.1`. Do not set `--host 0.0.0.0` unless something else authenticates in front.
- Do not expose this through a public tunnel. It will run OpenCode against whatever `cwd` the client sends.
- For anything other than a personal laptop, run it in an isolated worktree or disposable environment.

See [SECURITY.md](SECURITY.md).

## Tests

```bash
pip install pytest
pytest
```

## License

MIT. See [LICENSE](LICENSE).

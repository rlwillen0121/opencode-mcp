# Security

`opencode-mcp` is a local dispatcher. It has no auth, no TLS, and it will execute OpenCode against any `cwd` the MCP client sends.

## Do

- Bind to `127.0.0.1` (the default).
- Point `--cwd` at a dedicated worktree, not your whole home directory.
- Treat tool arguments as untrusted if the MCP host is shared.

## Do not

- Publish the `/mcp` port to the internet or a tunnel.
- Bind `0.0.0.0` without an authenticating reverse proxy.
- Run it as a privileged user.

## Report a vulnerability

Open a private GitHub security advisory on [rlwillen0121/opencode-mcp](https://github.com/rlwillen0121/opencode-mcp).

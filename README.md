# ThoughtSpot MCP Server (thoughtspot-mcp)

MCP server for the [ThoughtSpot REST API v2.0](https://developers.thoughtspot.com/docs/rest-apiv2-reference). Built with the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (FastMCP).

Lets any MCP-compatible client (Cursor, Claude Desktop, Claude Code, MCP Inspector, etc.) interact with your ThoughtSpot instance through natural language.

## Features

- 18 tools covering health, metadata search/delete, TML export/import, data-warehouse connections, data retrieval, and report exports
- Read and write operations for core resources (create, update, delete)
- TML round-trip: export objects as ThoughtSpot Modeling Language and re-import them (sync + async with status polling)
- Data access: run TML search queries and pull Liveboard / Answer data
- Report exports in PDF, PNG, CSV, and XLSX
- Automatic bearer-token exchange with in-memory caching, aggressive refresh (300s validity), and transparent 401 retry
- Markdown and JSON response formats on summary tools
- Runs over **stdio** (local) — works with Cursor, Claude Desktop, Claude Code, and Docker
- Works with self-hosted ThoughtSpot and ThoughtSpot Cloud

## Available Tools

| Tool | Description |
|---|---|
| **Health** | |
| `thoughtspot_health_check` | Check the instance is reachable and credentials are valid |
| **Metadata** | |
| `thoughtspot_search_metadata` | Search for metadata objects (Liveboards, Answers, Models, Connections, Tags, Users, ...) |
| `thoughtspot_delete_metadata` | Permanently delete one or more metadata objects |
| **TML** | |
| `thoughtspot_export_tml` | Export ThoughtSpot objects as TML (ThoughtSpot Modeling Language) |
| `thoughtspot_import_tml` | Import (create or update) ThoughtSpot objects from TML definitions |
| `thoughtspot_async_import_tml` | Start an asynchronous TML import and return a task ID to poll |
| `thoughtspot_get_tml_import_status` | Poll the status of asynchronous TML import task(s) |
| **Connections** | |
| `thoughtspot_search_connections` | List or filter data-warehouse connections configured in ThoughtSpot |
| `thoughtspot_get_connection` | Get full details (config + registered objects) of one connection by GUID or name |
| `thoughtspot_create_connection` | Create a new data-warehouse connection |
| `thoughtspot_update_connection` | Update a connection — rename, re-describe, or register tables/schemas |
| `thoughtspot_set_connection_status` | Activate or deactivate a connection |
| `thoughtspot_delete_connection` | Permanently delete a connection |
| **Data** | |
| `thoughtspot_search_data` | Run a TML search query against a Worksheet, View, Table, or SQL view |
| `thoughtspot_get_liveboard_data` | Get the data behind a Liveboard's visualizations |
| `thoughtspot_get_answer_data` | Get the data behind a saved Answer |
| **Reports** | |
| `thoughtspot_export_liveboard_report` | Export a Liveboard (and its visualizations) as a PDF, PNG, CSV, or XLSX file |
| `thoughtspot_export_answer_report` | Export an Answer as a CSV, PDF, XLSX, or PNG file |

## Prerequisites

- A running **ThoughtSpot** instance with **REST API v2.0** access — either:
  - Self-hosted ThoughtSpot, or
  - [ThoughtSpot Cloud](https://www.thoughtspot.com/)
- A service-account user with the privileges needed for the tools you plan to call.
- One of the following to run the server:
  - **[uvx](https://docs.astral.sh/uv/)** (zero-install; runs the published package on demand — see [Run with uvx](#run-with-uvx-zero-install)), or
  - **[uv](https://docs.astral.sh/uv/)** + **Python 3.13+** (local clone / development), or
  - **[Docker](https://docs.docker.com/get-docker/)** (no Python / uv needed on the host)

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/trustxai/thoughtspot-mcp.git
cd thoughtspot-mcp
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your `THOUGHTSPOT_HOST`, `THOUGHTSPOT_USERNAME`, and one of
`THOUGHTSPOT_SECRET_KEY` (trusted auth) or `THOUGHTSPOT_PASSWORD`. See
[Authentication](#authentication) for details.

### 3. Run the server

```bash
uv run thoughtspot-mcp
```

## Run with uvx (zero-install)

[uvx](https://docs.astral.sh/uv/) runs the published PyPI package on demand — no
clone, no virtualenv, no persistent install. The command matches the package
name, so no `--from` is needed:

```bash
uvx thoughtspot-mcp
```

Credentials are passed via the client's `env` block (see below), or exported in
your shell for a manual run:

```bash
THOUGHTSPOT_HOST=https://my-instance.thoughtspot.cloud \
THOUGHTSPOT_USERNAME=<service-account> \
THOUGHTSPOT_SECRET_KEY=<your-secret-key> \
uvx thoughtspot-mcp
```

> **Python version:** the package targets **Python 3.13+**. uv auto-provisions a
> matching interpreter, so this normally just works. If your environment pins an
> older default, force it with `uvx --python=3.13 thoughtspot-mcp`.

## Client Configuration

Every MCP client (Cursor, Claude Desktop, etc.) can run the server in one of three ways:

- **uvx** — zero-install; runs the published package on demand (see [Run with uvx](#run-with-uvx-zero-install)).
- **uv** — from a local clone; best for development.
- **Docker** — no Python / uv required on the host; everything runs in a container. Build the image once and every client config reuses it.

### Build the Docker image (one-time)

```bash
docker build -t thoughtspot-mcp:latest .
```

### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

**Option A — uvx**

```json
{
  "mcpServers": {
    "thoughtspot": {
      "command": "uvx",
      "args": ["thoughtspot-mcp"],
      "env": {
        "THOUGHTSPOT_HOST": "https://my-instance.thoughtspot.cloud",
        "THOUGHTSPOT_USERNAME": "<service-account>",
        "THOUGHTSPOT_SECRET_KEY": "<your-secret-key>"
      }
    }
  }
}
```

**Option B — uv**

```json
{
  "mcpServers": {
    "thoughtspot": {
      "command": "uv",
      "args": ["--directory", "/path/to/thoughtspot-mcp", "run", "thoughtspot-mcp"],
      "env": {
        "THOUGHTSPOT_HOST": "https://my-instance.thoughtspot.cloud",
        "THOUGHTSPOT_USERNAME": "<service-account>",
        "THOUGHTSPOT_SECRET_KEY": "<your-secret-key>"
      }
    }
  }
}
```

**Option C — Docker**

```json
{
  "mcpServers": {
    "thoughtspot": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--name", "thoughtspot-mcp",
        "-e", "THOUGHTSPOT_HOST",
        "-e", "THOUGHTSPOT_USERNAME",
        "-e", "THOUGHTSPOT_SECRET_KEY",
        "thoughtspot-mcp:latest"
      ],
      "env": {
        "THOUGHTSPOT_HOST": "https://my-instance.thoughtspot.cloud",
        "THOUGHTSPOT_USERNAME": "<service-account>",
        "THOUGHTSPOT_SECRET_KEY": "<your-secret-key>"
      }
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

**Option A — uv**

```json
{
  "mcpServers": {
    "thoughtspot": {
      "command": "uv",
      "args": ["--directory", "/path/to/thoughtspot-mcp", "run", "thoughtspot-mcp"],
      "env": {
        "THOUGHTSPOT_HOST": "https://my-instance.thoughtspot.cloud",
        "THOUGHTSPOT_USERNAME": "<service-account>",
        "THOUGHTSPOT_SECRET_KEY": "<your-secret-key>"
      }
    }
  }
}
```

**Option B — Docker**

```json
{
  "mcpServers": {
    "thoughtspot": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--name", "thoughtspot-mcp",
        "-e", "THOUGHTSPOT_HOST",
        "-e", "THOUGHTSPOT_USERNAME",
        "-e", "THOUGHTSPOT_SECRET_KEY",
        "thoughtspot-mcp:latest"
      ],
      "env": {
        "THOUGHTSPOT_HOST": "https://my-instance.thoughtspot.cloud",
        "THOUGHTSPOT_USERNAME": "<service-account>",
        "THOUGHTSPOT_SECRET_KEY": "<your-secret-key>"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add \
  --env THOUGHTSPOT_HOST=https://my-instance.thoughtspot.cloud \
  --env THOUGHTSPOT_USERNAME=<service-account> \
  --env THOUGHTSPOT_SECRET_KEY=<your-secret-key> \
  --transport stdio \
  thoughtspot \
  -- uvx thoughtspot-mcp
```

> The `--` separates `claude mcp add`'s own flags from the server command. Put
> every `--env` flag **before** the `--` and the server name; anything after the
> `--` is passed verbatim to the launched process. Placing `--env` after the `--`
> makes the CLI mis-parse it as an argument to `uvx`.

### MCP Inspector

The Inspector can launch the stdio server directly:

```bash
npx @modelcontextprotocol/inspector uvx thoughtspot-mcp
```

Set `THOUGHTSPOT_HOST`, `THOUGHTSPOT_USERNAME`, and your credential env var in the
Inspector's environment panel (or export them in your shell first).

## Authentication

The server authenticates against ThoughtSpot REST API v2.0 by exchanging your
credentials for a **bearer token** via `POST /api/rest/2.0/auth/token/full`. The
token is cached in memory and attached as `Authorization: Bearer <token>` on every
request.

Credentials are resolved by **precedence** — the first available option wins:

1. **`THOUGHTSPOT_ACCESS_TOKEN`** — a pre-fetched bearer token. Skips the token
   exchange entirely; use it when you already have a valid token.
2. **`THOUGHTSPOT_SECRET_KEY`** (+ `THOUGHTSPOT_USERNAME`) — **trusted authentication**.
   Preferred: no password is stored, and it enables RLS impersonation. Enable it
   under **Develop → Security Settings** in ThoughtSpot.
3. **`THOUGHTSPOT_PASSWORD`** (+ `THOUGHTSPOT_USERNAME`) — username/password token
   exchange. Simplest when trusted auth is off.

> **Token validity + auto-refresh.** ThoughtSpot access tokens default to a
> **300-second** validity window. The client refreshes aggressively (with a safety
> margin before expiry) and transparently retries **once** on an HTTP 401, so
> long-running sessions keep working without manual re-authentication.

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `THOUGHTSPOT_HOST` | Yes | — | Instance base URL, e.g. `https://my-instance.thoughtspot.cloud` (no `/api/rest` path) |
| `THOUGHTSPOT_USERNAME` | Yes* | — | Service-account username used for token exchange |
| `THOUGHTSPOT_SECRET_KEY` | Yes* | — | Trusted-auth secret key (preferred credential) |
| `THOUGHTSPOT_PASSWORD` | Yes* | — | Password (fallback credential) |
| `THOUGHTSPOT_ACCESS_TOKEN` | No | — | Pre-fetched bearer token (skips exchange) |
| `THOUGHTSPOT_ORG_ID` | No | — | Target a specific Org (multi-tenant instances) |
| `THOUGHTSPOT_TOKEN_VALIDITY_SECONDS` | No | `300` | Token validity window requested at exchange |
| `THOUGHTSPOT_REQUEST_TIMEOUT_SECONDS` | No | `30` | HTTP request timeout (seconds) |

\* Provide **one** credential path: either `THOUGHTSPOT_ACCESS_TOKEN`, or
`THOUGHTSPOT_USERNAME` + `THOUGHTSPOT_SECRET_KEY`, or `THOUGHTSPOT_USERNAME` +
`THOUGHTSPOT_PASSWORD`.

## Running Manually (without a client)

If you just want to exercise the server from the CLI:

```bash
# uvx — no clone
uvx thoughtspot-mcp

# uv
uv run thoughtspot-mcp

# Docker
docker run --rm -i --env-file .env thoughtspot-mcp:latest
```

## Troubleshooting

These are real ThoughtSpot REST API v2.0 gotchas worth knowing:

- **Connection update uses the plural path.** Update a connection via
  `connections/{id}/update` (plural `connections`). The singular
  `connection/{id}/update` path is **deprecated** — using it can silently no-op or
  return an error.
- **Connection config must be wrapped.** When creating or updating a connection,
  the data-warehouse configuration payload must be nested under a
  `data_warehouse_config` key. A bare, unwrapped config is rejected.
- **Global rate limit → HTTP 429.** ThoughtSpot enforces a global rate limit of
  **100 requests/second per IP**. Bursty tool loops can trip it and receive
  `HTTP 429 Too Many Requests`; back off and retry.
- **Trailing slash required on relevant-questions.** The
  `/ai/relevant-questions/` endpoint requires a **trailing slash**. Omitting it
  results in a routing failure (e.g. 404 / redirect), not the expected response.

## Contributing

Contributions are welcome! Open an issue or pull request to get started.

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.

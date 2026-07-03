# thoughtspot-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server for the
[ThoughtSpot REST API v2.0](https://developers.thoughtspot.com/docs/rest-apiv2-reference).
Self-hosted, stdio transport, Apache-2.0.

> **Status:** early development (v0.1.0). The full tool surface (metadata search,
> TML export/import, connections, data queries, reports, users/groups, tags, logs)
> is under active construction. See the roadmap in the project plan.

## Quickstart

```bash
uv sync --group dev
cp .env.example .env   # fill in THOUGHTSPOT_HOST + credentials
uv run thoughtspot-mcp
```

## Authentication

Set `THOUGHTSPOT_HOST` and `THOUGHTSPOT_USERNAME`, then one of (in precedence order):

1. `THOUGHTSPOT_ACCESS_TOKEN` — a pre-fetched bearer token.
2. `THOUGHTSPOT_SECRET_KEY` — trusted authentication (recommended; enable under
   *Develop > Security Settings*).
3. `THOUGHTSPOT_PASSWORD` — password login (simplest fallback).

Tokens are exchanged via `POST /auth/token/full` and auto-refreshed (default
validity is only 300s).

See `.env.example` for all configuration options.

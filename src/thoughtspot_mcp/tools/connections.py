"""Connection tools for the ThoughtSpot API (Wave A — task T1.3).

Planned tools:
    - create / search / status / update / delete over the connection endpoints.
    - IMPORTANT: use the PLURAL update path POST /connections/{id}/update
      (singular /connection/update is deprecated, removal slated Sept 2025).
      create and search remain singular for now.
    - Abstract the traps: data_warehouse_config wrapping, JSON-string-on-create
      vs dict-on-update, validate semantics, pagination.
    - Idempotency helper: find-by-name before create.

Intentional empty stub registered in ``tools/__init__``; owned by the T1.3 worktree.
"""

from __future__ import annotations

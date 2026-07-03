"""System / audit-log tools for the ThoughtSpot API (Wave B — task T1.8).

Planned tools:
    - system info:      GET /system
    - config overrides: GET /system/config-overrides
    - audit logs fetch: POST /logs/fetch

Note: GET /system is also used by the health-check tool (health.py). This module
adds richer system/config/audit surfaces.

Intentional empty stub registered in ``tools/__init__``; owned by the T1.8 worktree.
"""

from __future__ import annotations

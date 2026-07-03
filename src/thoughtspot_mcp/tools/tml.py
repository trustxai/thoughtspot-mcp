"""TML (ThoughtSpot Modeling Language) tools (Wave A — task T1.2).

Planned tools:
    - thoughtspot_export_tml: POST /metadata/tml/export (export_associated /
      export_fqn / edoc_format options; FQN-harvest convenience mode returning a
      guid map; handle metadata_content vs edocs response shapes).
    - thoughtspot_import_tml: POST /metadata/tml/import with per-object status.
    - async import + status: POST /metadata/tml/async/import and status endpoint
      (async status rate limit ~100/min).

Intentional empty stub registered in ``tools/__init__``; owned by the T1.2 worktree.
"""

from __future__ import annotations

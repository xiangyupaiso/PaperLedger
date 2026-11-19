"""Shared pytest scaffolding for the paper-orchestrator script ports.

The deliverable scripts live in ``skills/paper-orchestrator/scripts`` (public
layout) and are standalone CLI modules (no installed package). Put that
directory on ``sys.path`` so tests can ``import lit_search`` (and later
``plot_from_logs``, ``latex_compose``, ...) directly, mirroring how the host
runs them as ``python <script>.py``.
"""
import sys
from pathlib import Path

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "paper-orchestrator"
    / "scripts"
)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
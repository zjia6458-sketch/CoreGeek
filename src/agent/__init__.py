"""Competition-facing compatibility package.

The judger entrypoint imports ``agent.server``.  The application itself stays
under ``fortress_agent`` so the competition-specific import surface does not
leak through the internal architecture.
"""

from .server import serve

__all__ = ["serve"]

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_competition_agent_server_adapter_is_importable():
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from agent.server import serve
        assert callable(serve)
    finally:
        sys.path.pop(0)


def test_main3_requires_exactly_one_port_argument():
    result = subprocess.run(
        [sys.executable, str(ROOT / "main3.py")],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Usage: python main3.py <port>" in (
        result.stdout + result.stderr
    )


def test_main3_rejects_invalid_port_without_starting_server():
    result = subprocess.run(
        [sys.executable, str(ROOT / "main3.py"), "not-a-port"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "port must be an integer" in (
        result.stdout + result.stderr
    )

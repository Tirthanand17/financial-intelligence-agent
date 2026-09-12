import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "phase6_controlled_validation.py"


def test_phase6_validation_requires_explicit_network_flag() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0
    assert "BLOCKED: no network calls were made." in result.stdout
    assert "--allow-network" in result.stdout
    assert result.stderr == ""

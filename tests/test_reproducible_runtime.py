from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^=<>!~\s]+$")


def _dependency_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _normalized_name(requirement: str) -> str:
    name = requirement.split("==", 1)[0].split("[", 1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def test_python_runtime_is_pinned_to_exact_patch_version() -> None:
    configured = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"3\.11\.\d+", configured)
    assert configured == "3.11.16"


def test_locked_requirements_use_only_exact_versions() -> None:
    locked = _dependency_lines(ROOT / "requirements.txt")
    assert locked
    assert all(PIN_RE.fullmatch(line) for line in locked)
    assert len({_normalized_name(line) for line in locked}) == len(locked)


def test_every_direct_dependency_is_present_in_lock() -> None:
    direct = _dependency_lines(ROOT / "requirements.in")
    locked = _dependency_lines(ROOT / "requirements.txt")

    direct_names = {_normalized_name(line) for line in direct}
    locked_names = {_normalized_name(line) for line in locked}

    assert direct_names <= locked_names
    assert all(PIN_RE.fullmatch(line) for line in direct)

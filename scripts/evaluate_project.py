"""Gatekeeper evaluation script for Project Chatbot.

Runs sequentially:
1. ruff check app/ tests/ (Checks imports, syntax, dead code)
2. mypy app/ (Type safety, contract violations)
3. pytest tests/ (Full project test suite)

Exits with non-zero code on any failure.
"""

import os
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output encoding on Windows console
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 60}")
    print(f" GATEKEEPER STEP: {name}")
    print(f" Command: {' '.join(cmd)}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(f"\n[FAILED] Step '{name}' exited with code {result.returncode}")
        return False

    print(f"\n[PASSED] Step '{name}' succeeded.")
    return True


def main() -> int:
    target_dir = "app" if (PROJECT_ROOT / "app").exists() else "src"
    venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    python_cmd = str(venv_python) if venv_python.exists() else sys.executable

    steps = [
        ("Ruff Lint Check", [python_cmd, "-m", "ruff", "check", target_dir, "tests/"]),
        ("Mypy Strict Type Check", [python_cmd, "-m", "mypy", "--strict", target_dir]),
        ("Pytest Test Suite", [python_cmd, "-m", "pytest", "tests/", "-v", "--tb=short"]),
    ]

    for name, cmd in steps:
        success = run_step(name, cmd)
        if not success:
            print("\n" + "#" * 60)
            print("[GATEKEEPER REJECTED] Fix all issues before proceeding!")
            print("#" * 60)
            return 1

    print("\n" + "*" * 60)
    print("[GATEKEEPER PASSED] All lint, type, and unit checks clean 100%!")
    print("*" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

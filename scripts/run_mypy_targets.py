from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    targets_path = repo_root / "scripts" / "mypy_targets.txt"
    targets = [
        stripped
        for line in targets_path.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]
    command = [sys.executable, "-m", "mypy", "--follow-imports=skip", *targets]
    completed = subprocess.run(command, cwd=repo_root, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

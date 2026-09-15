import os
import subprocess
import sys
from pathlib import Path

from python_lab.models import TestResult


def run_tests(
    test_path: Path,
    project_root: Path,
    solution_path: Path | None = None,
) -> TestResult:
    env = os.environ.copy()
    if solution_path is not None:
        env["PYTHON_LAB_SOLUTION"] = str(solution_path)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env=env,
    )
    return TestResult(
        passed=completed.returncode == 0,
        return_code=completed.returncode,
        output=completed.stdout or "",
    )

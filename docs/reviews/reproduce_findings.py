"""Isolated diagnostics for the 2026-10-09 review; this is not a passing test suite.

Run with the project's development venv. All learner state and generated tests
live in a TemporaryDirectory. A `reproduced` value means a defect was observed,
not that the application is healthy. Update these diagnostics after fixes.
"""

import argparse
import asyncio
import json
import sys
import time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread

from rich.console import Console
from textual.widgets import TextArea

import python_lab.app as app_module
from python_lab.app import PythonLabApp
from python_lab.catalog import load_goal, load_missions, load_roadmap, load_skills
from python_lab.cli import PythonLabCLI, _banner
from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressRepository
from python_lab.session import SessionError, SessionLog
from python_lab.test_runner import run_tests
from python_lab.tui.app import PythonLabTUI


ROOT = Path(__file__).resolve().parents[2]


def make_app(root):
    missions = load_missions(ROOT / "missions")
    return PythonLabApp(
        goal=load_goal(ROOT / "data/goal.json"),
        skills=load_skills(ROOT / "data/skills.json"),
        missions=missions,
        repository=ProgressRepository(root / "progress.json"),
        project_root=root,
        roadmap=load_roadmap(ROOT / "data/roadmap.json", missions),
    )


def session_lost_update(root):
    path = root / "sessions.json"
    first, second = SessionLog(path), SessionLog(path)
    first.start()
    second.start()
    before = len(second.load())
    first.record("/status", "from first instance")
    after = len(first.load())
    return {"before": before, "after": after, "reproduced": after < before}


def progress_race(root):
    path = root / "progress.json"
    ProgressRepository(path).save(AppProgress())
    first, second = ProgressRepository(path), ProgressRepository(path)
    states = [first.load(), second.load()]
    for mission_id, state in zip(("001", "002"), states):
        state.missions[mission_id] = MissionProgress(status="started")

    # Pause both writers after the revision read, before either replaces the file.
    # This controls scheduling, without changing the actual save implementation.
    barrier = Barrier(2)
    for repository in (first, second):
        original = repository._current_revision
        calls = [0]

        def paused_revision(original=original, calls=calls):
            revision = original()
            calls[0] += 1
            if calls[0] == 1:
                barrier.wait(timeout=5)
            return revision

        repository._current_revision = paused_revision

    errors = []

    def save(repository, state):
        try:
            repository.save(state)
        except Exception as exc:
            errors.append(type(exc).__name__)

    threads = [
        Thread(target=save, args=(repository, state))
        for repository, state in zip((first, second), states)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    retained = sorted(ProgressRepository(path).load().missions)
    return {"errors": errors, "retained": retained, "reproduced": not errors and len(retained) == 1}


def blank_tui_explanation(root):
    lab = make_app(root)
    lab.start("001")
    tui = PythonLabTUI(lab)
    prompts = []

    def unexpected_input(prompt):
        prompts.append(prompt)
        return "unexpected stdin fallback"

    # Record a would-be stdin read, so the diagnostic cannot block the terminal.
    tui.cli.console.input = unexpected_input

    async def scenario():
        async with tui.run_test(size=(80, 24)) as pilot:
            tui._submit("/explain")
            await pilot.pause()
            tui.query_one("#explain-text", TextArea).load_text("")
            await pilot.click("#explain-save")
            await pilot.pause()

    asyncio.run(scenario())
    return {"stdin_prompts": prompts, "reproduced": bool(prompts)}


def progress_read_race(root):
    path = root / "progress.json"
    old = AppProgress(missions={"001": MissionProgress(status="started")})
    ProgressRepository(path).save(old)
    repository = ProgressRepository(path)
    original = repository._current_revision
    calls = [0]

    def intervening_write():
        calls[0] += 1
        if calls[0] == 1:
            newer = AppProgress(missions={
                "001": MissionProgress(status="started"),
                "002": MissionProgress(status="started"),
            })
            writer = ProgressRepository(path)
            writer.load()
            writer.save(newer)
        return original()

    repository._current_revision = intervening_write
    loaded = repository.load()
    on_disk_before_save = sorted(ProgressRepository(path).load().missions)
    repository.save(loaded)
    retained = sorted(ProgressRepository(path).load().missions)
    return {"before": on_disk_before_save, "after": retained,
            "reproduced": len(retained) < len(on_disk_before_save)}


def session_write_error(root):
    lab = make_app(root)
    log = SessionLog(root / "sessions.json")
    log.start()
    cli = PythonLabCLI(lab, console=Console(file=StringIO()), session_log=log)

    def failed_record(*args):
        raise SessionError("simulated disk full")

    log.record = failed_record
    error = None
    try:
        cli.execute("/status")
    except SessionError as exc:
        error = type(exc).__name__
    return {"escaped_exception": error, "reproduced": error == "SessionError"}


def invalid_state(root):
    path = root / "invalid.json"
    path.write_bytes(b"\xff")
    errors = {}
    for repository in (ProgressRepository, SessionLog):
        try:
            repository(path).load()
        except Exception as exc:
            errors[repository.__name__] = type(exc).__name__
    path.write_text(json.dumps({"missions": {"001": {"status": []}}}), encoding="utf-8")
    try:
        ProgressRepository(path).load()
    except Exception as exc:
        errors["invalid_status"] = type(exc).__name__
    return {
        "exceptions": errors,
        "reproduced": errors == {
            "ProgressRepository": "UnicodeDecodeError",
            "SessionLog": "UnicodeDecodeError",
            "invalid_status": "TypeError",
        },
    }


def timeout_child(root):
    tests = root / "tests"
    tests.mkdir()
    ready, marker = root / "ready", root / "child-survived"
    child_code = (
        "import time; from pathlib import Path; time.sleep(2); "
        f"Path({str(marker)!r}).write_text('finished after timeout')"
    )
    (tests / "test_child.py").write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n\n"
        "def test_child():\n"
        f"    subprocess.Popen([sys.executable, '-c', {child_code!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"    Path({str(ready)!r}).write_text('started')\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    result = run_tests(tests, root, timeout=1.5)
    deadline = time.monotonic() + 3
    while ready.exists() and not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return {
        "return_code": result.return_code,
        "child_launched": ready.exists(),
        "child_finished_after_timeout": marker.exists(),
        "reproduced": result.return_code == -1 and marker.exists(),
    }


def removed_active_mission(root):
    path = root / "progress.json"
    ProgressRepository(path).save(AppProgress(
        current_mission_id="removed",
        missions={"removed": MissionProgress(status="started")},
    ))
    lab = make_app(root)
    error = None
    try:
        _banner(lab, Console(file=StringIO()))
    except app_module.ApplicationError as exc:
        error = str(exc)
    return {"bootstrap_exception": error, "reproduced": error == "Missão inexistente: removed"}


def invalid_skills(root):
    path = root / "skills.json"
    path.write_text(json.dumps([
        {"id": "x", "name": "first", "category": "core", "future": False},
        {"id": "x", "name": "second", "category": "core", "future": "false"},
    ]), encoding="utf-8")
    loaded = load_skills(path)
    return {
        "retained_count": len(loaded),
        "name": loaded["x"].name,
        "future": loaded["x"].future,
        "reproduced": len(loaded) == 1 and loaded["x"].future is True,
    }


def refresh_fingerprints(root):
    lab = make_app(root)
    lab.start("001")
    lab.save_plan(dict(input="registros", output="totais", steps="agrupar", risks="vazio"))
    mission = lab.current_mission()
    result = lab.run_current_tests(mission.test_path.parent / "reference_solution.py")
    if not result.passed:
        raise RuntimeError(result.output)
    original = app_module.solution_fingerprint
    calls = []
    measurements = {}

    def counted(path):
        calls.append(path)
        return original(path)

    tui = PythonLabTUI(lab)

    async def scenario():
        async with tui.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            calls.clear()
            start = time.perf_counter()
            for _ in range(20):
                tui._refresh_status()
            measurements.update(
                calls_per_refresh=len(calls) / 20,
                mean_ms=round((time.perf_counter() - start) * 1000 / 20, 3),
            )

    app_module.solution_fingerprint = counted
    try:
        asyncio.run(scenario())
    finally:
        app_module.solution_fingerprint = original
    return {"mission_result": result.summary, **measurements}


def save_benchmark(root):
    repository = ProgressRepository(root / "progress.json")
    state = repository.load()
    state.missions["001"] = MissionProgress(status="started")
    results = []
    for count in (0, 10000):
        state.missions["001"].attempt_history = [
            dict(timestamp="2026-10-09T00:00:00Z", passed=False, return_code=1,
                 summary="3 testes: 0 aprovado(s), 3 falho(s)",
                 solution_path="/workspace/python-lab/missions/001/starter.py")
            for _ in range(count)
        ]
        times = []
        for _ in range(3):
            start = time.perf_counter()
            repository.save(state)
            times.append((time.perf_counter() - start) * 1000)
        results.append(dict(attempts=count, bytes=repository.path.stat().st_size,
                            mean_ms=round(sum(times) / len(times), 3)))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    probes = [session_lost_update, progress_race, progress_read_race, blank_tui_explanation,
              session_write_error, invalid_state, removed_active_mission, timeout_child, invalid_skills,
              refresh_fingerprints]
    if args.benchmark:
        probes.append(save_benchmark)
    with TemporaryDirectory(prefix="python-lab-review-") as directory:
        output = {}
        for probe in probes:
            root = Path(directory) / probe.__name__
            root.mkdir()
            output[probe.__name__] = probe(root)
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

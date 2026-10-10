"""Exercise the pilot using real mission suites and isolated learner state."""

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest
from textual.widgets import Input, TextArea

from python_lab.app import PythonLabApp
from python_lab.catalog import load_goal, load_missions, load_roadmap, load_skills
from python_lab.progress import ProgressRepository
from python_lab.session import SessionLog
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.widgets import Composer


ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
def test_pilot_journey_with_real_tests_and_isolated_progress(tmp_path, size):
    for slug in ("001-consolidar-falhas", "006-classificar-ordens"):
        copytree(ROOT / "missions" / slug, tmp_path / "missions" / slug)
    missions = [
        replace(mission, solution_path=mission.test_path.parent / "reference_solution.py")
        for mission in load_missions(tmp_path / "missions")
    ]
    lab = PythonLabApp(
        load_goal(ROOT / "data" / "goal.json"),
        load_skills(ROOT / "data" / "skills.json"),
        missions,
        ProgressRepository(tmp_path / "lab.sqlite3"),
        tmp_path,
        load_roadmap(ROOT / "data" / "roadmap.json", missions),
    )
    session = SessionLog(tmp_path / "lab.sqlite3")
    session.start()
    tui = PythonLabTUI(lab, session)

    async def scenario():
        async with tui.run_test(size=size) as pilot:
            async def submit(command):
                composer = tui.query_one("#composer", Composer)
                composer.focus()
                composer.value = command
                await pilot.press("enter")
                await pilot.pause()

            for mission_id in ("001", "006"):
                await submit(f"/mission {mission_id}")
                assert lab.progress.current_mission_id is None
                await submit(f"/start {mission_id}")
                assert tui.query_one("#composer").region.bottom <= size[1]
                preview = os.environ.get("PYTHON_LAB_PREVIEW_DIR")
                if preview:
                    folder = Path(preview)
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / f"pilot-{mission_id}-{size[0]}x{size[1]}.svg").write_text(
                        tui.export_screenshot(), encoding="utf-8",
                    )
                await submit("/concepts")
                assert lab.current_progress().hints_revealed == 0
                await submit("/plan")
                tui.query_one("#plan-input", Input).value = "Dados da missão"
                tui.query_one("#plan-output", Input).value = "Contrato de saída"
                tui.query_one("#plan-steps", TextArea).load_text("Compreender\nImplementar\nVerificar")
                tui.query_one("#plan-risks", TextArea).load_text("Lista vazia\nRegras sobrepostas")
                tui.query_one("#plan-save").focus()
                await pilot.press("enter")
                await pilot.pause()
                await submit("/test")
                await tui.workers.wait_for_complete()
                await pilot.pause()
                assert lab.tests_are_current(), tui.transcript_entries[-1]
                attempts = lab.current_progress().attempts
                await submit("/test details")
                assert lab.current_progress().attempts == attempts == 1
                await submit("/explain")
                tui.query_one("#explain-text", TextArea).load_text(
                    "Verifiquei a precedência das regras e os casos extremos com os testes."
                )
                tui.query_one("#explain-save").focus()
                await pilot.press("enter")
                await pilot.pause()
                assert lab.progress.missions[mission_id].status == "completed"
                assert lab.progress.current_mission_id is None
            await submit("/session")
            assert "Sessão atual" in tui.transcript_entries[-1]

    asyncio.run(scenario())
    assert session._current["ended_at"] is not None
    assert lab.repository.load().missions["006"].status == "completed"

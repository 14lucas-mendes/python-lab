from python_lab.test_runner import solution_fingerprint


def test_next_step_without_mission_recommends_start(app):
    assert app.next_step() == "Inicie a missão 001 com /start 001"


def test_next_step_after_start_asks_for_plan(app):
    app.start("001")
    assert app.next_step() == "Registre o planejamento com /plan"


def test_next_step_after_plan_asks_to_edit_and_test(app):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    assert app.next_step() == "Edite a solução e execute /test"


def test_next_step_when_tests_are_stale_asks_to_retest(app):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("ok = True\n", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    app.persist()
    solution.write_text("ok = False\n", encoding="utf-8")
    assert app.next_step() == "Execute /test novamente para a solução atual"


def test_next_step_when_tests_are_current_asks_for_explain(app):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("ok = True\n", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    app.persist()
    assert app.next_step() == "Registre a explicação com /explain"


def test_next_step_when_all_missions_are_done(app):
    app.start("001")
    app.progress.missions["001"].status = "completed"
    app.progress.current_mission_id = None
    app.persist()
    assert app.next_step() == "Todas as missões concluídas."


def test_status_hashes_once(app, monkeypatch):
    app.start("001")
    app.save_plan(dict(input="x", output="y", steps="z", risks="w"))
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("ok = True\n", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    calls = []
    def fingerprint(path):
        calls.append(path)
        return solution_fingerprint(path)
    monkeypatch.setattr("python_lab.app.solution_fingerprint", fingerprint)
    snapshot = app.status_snapshot()
    assert calls == [solution]
    assert snapshot.current_mission_id == "001"
    assert snapshot.plan_complete and snapshot.tests_current
    assert snapshot.next_step == "Registre a explicação com /explain"
    assert snapshot.last_result is None


def test_snapshot_has_no_test_evidence_without_mission(app):
    snapshot = app.status_snapshot()
    assert snapshot.current_mission_id is None
    assert not snapshot.plan_complete and not snapshot.tests_current
    assert snapshot.next_step == "Inicie a missão 001 com /start 001"


def test_plan_completion_is_shared():
    from python_lab.learning import plan_is_complete
    assert not plan_is_complete(None)
    assert not plan_is_complete(dict(input="x", output="y", steps="z", risks="  "))
    assert plan_is_complete(dict(input="x", output="y", steps="z", risks="w"))

from scripts.freeze_legacy_evaluation_history import FILES


def test_legacy_freeze_covers_questions_and_first_runs():
    assert set(FILES) == {
        "testdata/golden/z3_blind_questions.yaml",
        "testdata/golden/z4_blind_questions.yaml",
        "artifacts/blind_z3/eval_z3_run.json",
        "artifacts/blind_z4/eval_z4_run.json",
    }

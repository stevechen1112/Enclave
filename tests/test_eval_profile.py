"""
P0-2：Eval Profile 統一設定 — 單元測試。

驗收標準（對照稽核文件 §5.5）：
- artifact 含 profile ID 與 hash
- profile 可從 YAML 載入
- 門檻與指標可正確讀取
"""
import pytest
from pathlib import Path

from app.eval.profile import EvalProfile, load_profile, list_profiles, PROFILES_DIR


class TestEvalProfile:
    def test_load_z3_blind(self):
        profile = load_profile("z3_blind")
        assert profile.name == "z3_blind"
        assert profile.gt_frozen is True
        assert profile.questions_file == "z3_blind_questions.yaml"
        assert profile.retrieval_top_k == 5
        assert "hit_at_k" in profile.metrics
        assert profile.thresholds.get("hit_at_k_min") == 0.85

    def test_load_z4_blind(self):
        profile = load_profile("z4_blind")
        assert profile.name == "z4_blind"
        assert profile.gt_frozen is True
        assert profile.anti_target_drawing is True

    def test_load_z5_holdout(self):
        profile = load_profile("z5_holdout")
        assert profile.name == "z5_holdout"
        assert profile.gt_frozen is False  # 待凍結

    def test_load_z1_golden(self):
        profile = load_profile("z1_golden")
        assert profile.name == "z1_golden"
        assert profile.expanded_file == "z1_expanded_from_annotations.yaml"

    def test_profile_hash_stable(self):
        profile1 = load_profile("z3_blind")
        profile2 = load_profile("z3_blind")
        assert profile1.profile_hash == profile2.profile_hash

    def test_profile_hash_differs(self):
        profile1 = load_profile("z3_blind")
        profile2 = load_profile("z4_blind")
        assert profile1.profile_hash != profile2.profile_hash

    def test_questions_path(self):
        profile = load_profile("z3_blind")
        assert profile.questions_path.name == "z3_blind_questions.yaml"
        assert profile.questions_path.parent.name == "golden"

    def test_artifact_path(self):
        profile = load_profile("z3_blind")
        assert profile.artifact_path.name == "answer_correctness_z3_last_run.json"

    def test_to_dict_contains_hash(self):
        profile = load_profile("z3_blind")
        d = profile.to_dict()
        assert "profile_hash" in d
        assert len(d["profile_hash"]) == 12

    def test_list_profiles(self):
        profiles = list_profiles()
        assert "z3_blind" in profiles
        assert "z4_blind" in profiles
        assert "z5_holdout" in profiles
        assert "z1_golden" in profiles

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent_profile")

    def test_thresholds_defaults(self):
        profile = EvalProfile(name="test")
        assert profile.thresholds == {}
        assert profile.metrics == ["hit_at_k", "mrr", "answer_correctness"]
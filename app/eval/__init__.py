"""Shared evaluation primitives for capability-value gates.

Every CV-* gate script builds on these so that thresholds, confidence intervals and
INCONCLUSIVE handling are defined in exactly one place.
"""
from app.eval.metrics import (
    Judgement,
    character_error_rate,
    hit_at_k,
    judge,
    mean_reciprocal_rank,
    mcnemar_exact_p,
    ndcg_at_k,
    normalize_field,
    normalize_field_t2s,
    wilson_interval,
)
from app.eval.profile import EvalProfile, load_profile, list_profiles

__all__ = [
    "Judgement",
    "character_error_rate",
    "hit_at_k",
    "judge",
    "mcnemar_exact_p",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "normalize_field",
    "normalize_field_t2s",
    "wilson_interval",
    "EvalProfile",
    "load_profile",
    "list_profiles",
]

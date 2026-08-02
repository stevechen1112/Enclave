"""Metrics and judgement rules shared by all capability-value gates.

The judgement vocabulary matches the plan document (§9.1):
PROVEN / MARGINAL / INCONCLUSIVE / NO_VALUE / INSUFFICIENT_DATA.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Sequence

Z_95 = 1.959963984540054


# ---------------------------------------------------------------- text handling

_PUNCT = re.compile(r"[\s\u3000,，.。;；:：、/\\|()（）\[\]【】{}<>《》\"'`~!！?？*#\-—_]+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")


def normalize_field(value: str) -> str:
    """Normalize a field value before exact matching.

    Full-width to half-width, thousands separators removed, punctuation and
    whitespace stripped, case folded. Defined once so annotation and scoring
    cannot drift apart.
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _THOUSANDS.sub("", text)
    text = _PUNCT.sub("", text)
    return text.casefold()


_S2T = None


def _s2t_converter():
    """Lazy OpenCC simplified->traditional converter; False when unavailable."""
    global _S2T
    if _S2T is None:
        try:
            import opencc
            _S2T = opencc.OpenCC("s2t")
        except Exception:
            _S2T = False
    return _S2T


def normalize_field_t2s(value: str) -> str:
    """normalize_field plus simplified->traditional conversion.

    OCR engines (incl. DeepDOC's) frequently emit simplified characters for
    traditional-Chinese scans. Scoring traditional ground truth against that
    output verbatim would conflate script choice with recognition error, so
    gates may opt into this script-tolerant variant — applied to BOTH sides.
    """
    text = normalize_field(value)
    conv = _s2t_converter()
    if conv:
        try:
            text = conv.convert(text)
        except Exception:
            pass
    return text


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """CER = edit_distance / len(reference). Returns 1.0 when nothing was extracted.

    The denominator is the length of the *normalized* reference, but the numerator
    is capped at that length so CER never exceeds 1.0. This prevents a hypothesis
    that is longer than the reference (e.g. OCR hallucinating extra characters)
    from producing a nonsensical score.
    """
    ref = normalize_field(reference) if normalize else reference
    hyp = normalize_field(hypothesis) if normalize else hypothesis
    if not ref:
        return 0.0 if not hyp else 1.0
    distance = _levenshtein(ref, hyp)
    return min(distance, len(ref)) / len(ref)


# ------------------------------------------------------------ ranking metrics

def hit_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int = 5) -> float:
    relevant = set(relevant_ids)
    return 1.0 if any(doc_id in relevant for doc_id in ranked_ids[:k]) else 0.0


def mean_reciprocal_rank(ranked_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    relevant = set(relevant_ids)
    for rank, doc_id in enumerate(ranked_ids, 1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[str], relevant_ids: Iterable[str], k: int = 5) -> float:
    relevant = set(relevant_ids)
    dcg = sum(1.0 / math.log2(i + 1) for i, doc_id in enumerate(ranked_ids[:k], 1) if doc_id in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


# ------------------------------------------------------------------ statistics

def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _binom_coeff(n: int, k: int) -> int:
    return math.comb(n, k)


def mcnemar_exact_p(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value for paired binary outcomes.

    only_a: cases the baseline got right and the treatment got wrong.
    only_b: cases the treatment got right and the baseline got wrong.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(_binom_coeff(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


# ------------------------------------------------------------------- judgement

class Judgement(str):
    PROVEN = "PROVEN"
    MARGINAL = "MARGINAL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_VALUE = "NO_VALUE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class JudgeResult:
    judgement: str
    delta: float
    ci_low: float
    ci_high: float
    n: int
    threshold: float
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "judgement": self.judgement,
            "delta": round(self.delta, 4),
            "ci_low": round(self.ci_low, 4),
            "ci_high": round(self.ci_high, 4),
            "n": self.n,
            "threshold": self.threshold,
            **self.detail,
        }


def judge(
    baseline_successes: int,
    treatment_successes: int,
    total: int,
    threshold: float,
    min_n: int = 10,
    discordant: tuple[int, int] | None = None,
) -> JudgeResult:
    """Apply the plan's judgement rules to a paired before/after comparison.

    threshold is expressed as a proportion (0.20 means +20 percentage points).
    discordant, when supplied as (only_baseline_right, only_treatment_right),
    enables the exact McNemar test appropriate for paired data.
    """
    if total < min_n:
        return JudgeResult(Judgement.INSUFFICIENT_DATA, 0.0, 0.0, 1.0, total, threshold,
                           {"reason": f"n={total} below min_n={min_n}"})

    base_rate = baseline_successes / total
    treat_rate = treatment_successes / total
    delta = treat_rate - base_rate

    detail: dict = {"baseline_rate": round(base_rate, 4), "treatment_rate": round(treat_rate, 4)}

    if discordant is not None:
        only_base, only_treat = discordant
        p_value = mcnemar_exact_p(only_base, only_treat)
        detail.update({"mcnemar_p": round(p_value, 6), "discordant": [only_base, only_treat]})
        n_disc = only_base + only_treat
        if n_disc == 0:
            return JudgeResult(Judgement.NO_VALUE if delta <= 0 else Judgement.INCONCLUSIVE,
                               delta, 0.0, 0.0, total, threshold, detail)
        low, high = wilson_interval(only_treat, n_disc)
        ci_low, ci_high = (2 * low - 1) * n_disc / total, (2 * high - 1) * n_disc / total
    else:
        b_low, b_high = wilson_interval(baseline_successes, total)
        t_low, t_high = wilson_interval(treatment_successes, total)
        ci_low, ci_high = t_low - b_high, t_high - b_low

    detail["ci_method"] = "mcnemar_paired" if discordant is not None else "wilson_unpaired"

    if delta <= 0:
        verdict = Judgement.NO_VALUE
    elif ci_low <= 0:
        verdict = Judgement.INCONCLUSIVE
    elif ci_low > threshold:
        verdict = Judgement.PROVEN
    else:
        verdict = Judgement.MARGINAL
    return JudgeResult(verdict, delta, ci_low, ci_high, total, threshold, detail)

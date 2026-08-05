import sys
sys.path.insert(0, "scripts")
from eval_answer_correctness import span_in_answer, _normalize_span_text

ans_r21 = "繳納期限為：**民國 114 年 11 月 15 日**（西元 2025 年 11 月 15 日）。"
print("R21 norm span:", repr(_normalize_span_text("11月15")))
print("R21 norm ans :", repr(_normalize_span_text(ans_r21)))
print("R21 hit:", span_in_answer("11月15", ans_r21))

ans_r16 = "1. 民國114年7－8月 ... 2. 民國114年9－10月"
print("R16 a:", span_in_answer("114年09-10月", ans_r16))
print("R16 b:", span_in_answer("114年07-08月", ans_r16))

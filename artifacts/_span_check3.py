import sys
sys.path.insert(0, "scripts")
from eval_answer_correctness import span_in_answer

cases = [
    ("11月15", "繳納期限為：**民國 114 年 11 月 15 日**（西元 2025 年 11 月 15 日）。", True),
    ("114年09-10月", "1. 民國114年7－8月 2. 民國114年9－10月", True),
    ("114年07-08月", "1. 民國114年7－8月 2. 民國114年9－10月", True),
    ("2026-02-02", "訂單日期是 2026 年 2 月 2 日。", True),
    ("1980.02.16", "出生日期是1980年2月16日", True),
    ("2026.07.19", "預計入境日 2026-07-19", True),
    ("0930168033", "電話：0930-168-033", True),
    ("32,130", "總計 NT$32,130 元", True),
    ("0.6.1 Beta", "版本為 0.6.1 Beta", True),
    ("114年11月", "簽署日為民國114年11月4日", True),
    ("114年11月15日", "繳納期限：114年11月15日", True),
    ("人易科技股份有限公司", "廠商是八策數位", False),
    ("36,733", "應納稅額 24,919 元", False),
]
bad = 0
for sp, ans, want in cases:
    got = span_in_answer(sp, ans)
    if got != want:
        bad += 1
        print("WRONG", repr(sp), "->", got, "want", want)
    else:
        print("OK", repr(sp))
print("bad:", bad)

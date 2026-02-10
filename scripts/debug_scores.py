import sys
sys.path.insert(0, "/code")
import os
os.environ.setdefault("POSTGRES_SERVER", "db")
os.environ.setdefault("REDIS_HOST", "redis")

# Test the A2 string length
s1 = "公司績效考核一年 2 次，分別在 6 月與 12 月各進行一次。"
s2 = "此為公司內規規定的考核週期，詳見員工手冊相關章節。"
combined = s1 + s2
print(f"s1 len: {len(s1)}")
print(f"s2 len: {len(s2)}")
print(f"combined len: {len(combined)}")
print(f"combined: {combined}")
print(f"len > 50: {len(combined) > 50}")

# Test _terms_match for C4
import re
def _terms_match(expected, answer):
    parts = re.split(r"[，。、,;；\s/]+", expected)
    terms = [p for p in parts if len(p) >= 2][:5]
    print(f"  terms: {terms}")
    return all(t in answer for t in terms)

print("\n--- C4 terms_match ---")
expected_c4 = "合法但不得低於基本工資"
answer_c4_structured = "試用期薪資打 9 折原則上合法但不得低於基本工資。需在勞動契約中明確約定；若 9 折後低於基本工資或最低工資，則屬違法。"
answer_c4_llm = "試用期薪資打 9 折在法律上可行，但不得低於基本工資。需在勞動契約中明確約定；若 9 折後低於基本工資或最低工資，則屬違法。"
print(f"structured match: {_terms_match(expected_c4, answer_c4_structured)}")
print(f"llm match: {_terms_match(expected_c4, answer_c4_llm)}")

# Test _numbers_match for E1
def _extract_numbers(text):
    nums = re.findall(r"\d+(?:[,.]\d+)?", text or "")
    return [float(n.replace(",", "")) for n in nums]

print("\n--- E1 numbers ---")
expected_e1 = "OCR 辨識結果"
print(f"E1 expected nums: {_extract_numbers(expected_e1)}")
print(f"E1 terms: ", end="")
_terms_match(expected_e1, "統一編號為 61846629")

# Test for E3
print("\n--- E3 numbers ---")
expected_e3 = "不可以，勞基法§13"
print(f"E3 expected nums: {_extract_numbers(expected_e3)}")
answer_e3 = "根據《職業災害勞工保護法》第20條"
print(f"E3 answer nums: {_extract_numbers(answer_e3)}")

# Test for H1
print("\n--- H1 numbers ---")
expected_h1 = "3 個月，63,000→70,000"
print(f"H1 expected nums: {_extract_numbers(expected_h1)}")
answer_h1 = "試用期通常為 1-3 個月 薪資為正式薪資的 90%"
print(f"H1 answer nums: {_extract_numbers(answer_h1)}")

import sys, os
sys.path.insert(0, "/code")
os.environ.setdefault("POSTGRES_SERVER", "db")
os.environ.setdefault("REDIS_HOST", "redis")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@db:5432/unihr_saas")

from uuid import UUID

# Get the tenant_id from the test run
import json
tenant_id = None
with open('/code/test-data/test-results/run_20260211_031503/test_log.jsonl') as f:
    for line in f:
        d = json.loads(line)
        summary = d.get("summary", {})
        if isinstance(summary, dict) and "tenant" in summary:
            tenant_id = summary["tenant"]
            break

print(f"tenant_id: {tenant_id}")

if tenant_id:
    from app.services.structured_answers import try_structured_answer, EmployeeRoster, RegistrationForm
    
    tid = UUID(tenant_id)
    
    # Test roster loading
    roster = EmployeeRoster.load(tid)
    print(f"\nroster loaded: {roster is not None}")
    if roster:
        print(f"roster has data: True")
    
    # Test A2
    print("\n--- A2 ---")
    result = try_structured_answer(tid, "公司績效考核是一年幾次？")
    if result:
        print(f"answer len: {len(result.answer)}")
        print(f"answer: {result.answer}")
        print(f"sources: {len(result.sources)}")
    else:
        print("result is None!")
    
    # Test C4
    print("\n--- C4 ---")
    result = try_structured_answer(tid, "我們公司試用期薪資打 9 折，這樣合法嗎？")
    if result:
        print(f"answer len: {len(result.answer)}")
        print(f"answer: {result.answer}")
    else:
        print("result is None!")
    
    # Test E1
    print("\n--- E1 ---")
    result = try_structured_answer(tid, "請問變更登記表上的公司統一編號是多少？")
    if result:
        print(f"answer len: {len(result.answer)}")
        print(f"answer: {result.answer}")
    else:
        print("result is None!")
    
    # Test E3
    print("\n--- E3 ---")
    result = try_structured_answer(tid, "員工請職業災害醫療期間，公司因業務緊縮想資遣他，可以嗎？")
    if result:
        print(f"answer len: {len(result.answer)}")
        print(f"answer: {result.answer}")
    else:
        print("result is None!")
    
    # Test H1
    print("\n--- H1 ---")
    result = try_structured_answer(tid, "新人試用期多久？薪資有差異嗎？")
    if result:
        print(f"answer len: {len(result.answer)}")
        print(f"answer: {result.answer}")
    else:
        print("result is None!")

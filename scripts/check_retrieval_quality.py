"""
檢索品質驗證腳本
針對 101 個上傳文件進行多類型問題測試，驗證 RAG 系統的回答品質
"""
import requests, json, time

BASE_URL = "http://localhost:8001"
USER = "admin@example.com"
PASS = "admin123"

def login():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login/access-token",
                      data={"username": USER, "password": PASS})
    r.raise_for_status()
    return r.json()["access_token"]

def ask(token, question, conv_id=None):
    payload = {"question": question, "top_k": 5}
    if conv_id:
        payload["conversation_id"] = conv_id
    r = requests.post(f"{BASE_URL}/api/v1/chat/chat",
                      json=payload, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return None, None, None
    d = r.json()
    answer = d.get("answer", d.get("content", ""))
    sources = [s.get("title", s.get("document_name", s.get("filename", ""))) for s in d.get("sources", [])]
    conv_id = d.get("conversation_id")
    return answer, sources, conv_id

def score_answer(answer, keywords, min_len=50):
    if not answer or len(answer) < min_len:
        return 0
    hits = sum(1 for kw in keywords if kw.lower() in answer.lower())
    return round(hits / len(keywords) * 100)

TEST_CASES = [
    # ── 薪資 ──────────────────────────────────────────────────────
    {
        "category": "薪資制度",
        "question": "員工陳建宏的本薪是多少？加班費如何計算？",
        "keywords": ["58,000", "加班", "陳建宏", "本薪"],
        "expect_sources": ["陳建宏", "薪資"],
    },
    {
        "category": "薪資制度",
        "question": "公司薪資調整幅度是多少？S級員工可以調幾%？",
        "keywords": ["2.5%", "5%", "S級", "調整"],
        "expect_sources": ["公告", "通知"],
    },
    # ── 勞動法規 ──────────────────────────────────────────────────
    {
        "category": "勞動法規",
        "question": "特別休假未休完可以放棄嗎？公司規定是什麼？",
        "keywords": ["未休", "工資", "放棄", "勞基法"],
        "expect_sources": ["員工手冊", "勞動"],
    },
    {
        "category": "勞動法規",
        "question": "生理假扣全勤獎金合法嗎？",
        "keywords": ["生理假", "全勤", "性平法", "3天"],
        "expect_sources": ["員工手冊", "勞動"],
    },
    {
        "category": "勞動法規",
        "question": "競業禁止條款的補償金標準是什麼？",
        "keywords": ["50%", "月薪", "6個月", "補償"],
        "expect_sources": ["勞動契約", "智慧財產"],
    },
    # ── 請假 ──────────────────────────────────────────────────────
    {
        "category": "請假規定",
        "question": "員工李志偉什麼原因申請婚假？請了幾天？",
        "keywords": ["婚假", "8天", "李志偉", "結婚"],
        "expect_sources": ["請假單", "李志偉"],
    },
    {
        "category": "請假規定",
        "question": "陪產假可以請幾天？",
        "keywords": ["陪產假", "7", "有薪"],
        "expect_sources": ["員工手冊", "請假"],
    },
    # ── 採購/報帳 ─────────────────────────────────────────────────
    {
        "category": "採購報帳",
        "question": "採購金額超過50萬需要誰核准？",
        "keywords": ["董事會", "50萬", "核准"],
        "expect_sources": ["採購", "SOP"],
    },
    {
        "category": "採購報帳",
        "question": "出差每日餐費上限是多少？早餐午餐晚餐各多少？",
        "keywords": ["600", "100", "200", "300", "餐費"],
        "expect_sources": ["出差", "SOP"],
    },
    # ── 績效 ──────────────────────────────────────────────────────
    {
        "category": "績效考核",
        "question": "王俊傑今年績效考核結果是幾分？什麼等級？",
        "keywords": ["97", "S", "王俊傑", "業績"],
        "expect_sources": ["考核", "王俊傑"],
    },
    {
        "category": "績效考核",
        "question": "考核等級C代表什麼？需要做什麼？",
        "keywords": ["C", "可", "D", "考核"],
        "expect_sources": ["績效", "policy", "考核"],
    },
    # ── 組織人力 ─────────────────────────────────────────────────
    {
        "category": "組織人力",
        "question": "研發部現在有多少人？缺額幾個？主管是誰？",
        "keywords": ["12", "5", "陳建宏", "研發部"],
        "expect_sources": ["人力", "部門", "組織"],
    },
    {
        "category": "組織人力",
        "question": "公司2025年年度離職率是多少？",
        "keywords": ["離職", "22.2%", "12人", "2025"],
        "expect_sources": ["離職", "人力", "分析"],
    },
    # ── 健康紀錄 ─────────────────────────────────────────────────
    {
        "category": "健康管理",
        "question": "王俊傑的健康檢查有哪些異常項目？",
        "keywords": ["體重", "血壓", "血糖", "膽固醇", "王俊傑"],
        "expect_sources": ["健康", "王俊傑"],
    },
    # ── 培訓 ──────────────────────────────────────────────────────
    {
        "category": "教育訓練",
        "question": "AI工具應用工作坊的講師是誰？訓練了哪些人？",
        "keywords": ["陳建宏", "Enclave", "AI", "工作坊"],
        "expect_sources": ["訓練", "工作坊"],
    },
    # ── 多輪對話 ─────────────────────────────────────────────────
    {
        "category": "多輪對話",
        "question": "公司有哪些員工福利？",
        "keywords": ["勞保", "健保", "年終", "三節"],
        "expect_sources": ["福利"],
        "followup": "其中教育訓練補助是多少錢？",
        "followup_keywords": ["15,000", "教育", "補助"],
    },
]

def main():
    print("=" * 70)
    print("  Enclave RAG 檢索品質驗證")
    print(f"  測試案例：{len(TEST_CASES)} 個 / 文件庫：101 份")
    print("=" * 70)

    token = login()
    print(f"✅ 登入成功\n")

    results = []
    total_score = 0
    conv_test_conv_id = None

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"[{i:02d}/{len(TEST_CASES)}] ── {tc['category']}：{tc['question'][:45]}...")

        t0 = time.time()
        answer, sources, conv_id = ask(token, tc["question"])
        latency = time.time() - t0

        if answer is None:
            print(f"       ❌ API 呼叫失敗\n")
            results.append({"q": tc["question"], "score": 0, "status": "API_FAIL"})
            continue

        score = score_answer(answer, tc["keywords"])
        answer_preview = answer[:120].replace("\n", " ")

        # 來源匹配
        src_str = ", ".join(sources[:3]) if sources else "（無來源）"
        src_match = any(
            any(ex.lower() in s.lower() for ex in tc["expect_sources"])
            for s in sources
        ) if sources else False

        status = "✅" if score >= 50 and src_match else ("⚠️" if score >= 30 else "❌")
        print(f"       {status} 關鍵字命中：{score}% | 來源：{src_str[:60]}")
        print(f"       💬 {answer_preview}...")
        print(f"       ⏱  {latency:.2f}s\n")

        results.append({
            "category": tc["category"],
            "question": tc["question"],
            "score": score,
            "src_match": src_match,
            "latency": latency,
            "status": status,
        })
        total_score += score

        # 多輪測試
        if "followup" in tc:
            print(f"       ↩  多輪追問：{tc['followup']}")
            t0 = time.time()
            a2, s2, _ = ask(token, tc["followup"], conv_id=conv_id)
            lat2 = time.time() - t0
            score2 = score_answer(a2 or "", tc.get("followup_keywords", []))
            status2 = "✅" if score2 >= 50 else ("⚠️" if score2 >= 30 else "❌")
            preview2 = (a2 or "")[:100].replace("\n", " ")
            print(f"       {status2} 多輪關鍵字命中：{score2}% | ⏱ {lat2:.2f}s")
            print(f"       💬 {preview2}...\n")
            results.append({
                "category": tc["category"] + "（多輪）",
                "question": tc["followup"],
                "score": score2,
                "src_match": True,
                "latency": lat2,
                "status": status2,
            })
            total_score += score2

    # ── 摘要報告 ──────────────────────────────────────────────────
    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    passed = sum(1 for r in results if r.get("score", 0) >= 50)
    warned = sum(1 for r in results if 30 <= r.get("score", 0) < 50)
    failed = sum(1 for r in results if r.get("score", 0) < 30)
    avg_latency = sum(r.get("latency", 0) for r in results) / n if n > 0 else 0

    by_cat = {}
    for r in results:
        cat = r.get("category", "?")
        by_cat.setdefault(cat, []).append(r["score"])

    print("=" * 70)
    print("  檢索品質摘要報告")
    print("=" * 70)
    print(f"  總測試數：{n}　✅ 通過(≥50%)：{passed}　⚠️ 偏低：{warned}　❌ 不足：{failed}")
    print(f"  平均關鍵字命中率：{avg_score:.1f}%")
    print(f"  平均回答延遲：{avg_latency:.2f}s")
    print()
    print("  各類別平均得分：")
    for cat, scores in by_cat.items():
        avg = sum(scores) / len(scores)
        bar = "█" * int(avg // 10) + "░" * (10 - int(avg // 10))
        flag = "✅" if avg >= 50 else ("⚠️" if avg >= 30 else "❌")
        print(f"  {flag} {cat:<16} {bar} {avg:.0f}%")
    print("=" * 70)

    overall = "優秀" if avg_score >= 75 else ("良好" if avg_score >= 55 else ("需改善" if avg_score >= 35 else "不足"))
    print(f"\n  整體評級：【{overall}】（平均命中率 {avg_score:.1f}%）\n")

if __name__ == "__main__":
    main()

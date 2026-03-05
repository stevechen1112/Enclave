#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真實內容審查腳本
讀取：
1. 最近 5 筆對話的完整問答內容
2. 最近生成的報告內容
3. KB 搜尋返回的真實 chunk 文字
"""

import requests, json, textwrap

BASE = "http://localhost:8001"

r = requests.post(f"{BASE}/api/v1/auth/login/access-token",
    data={"username": "admin@example.com", "password": "admin123"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

SEP = "=" * 70

# ─────────────────────────────────────────────────────────
# 1. 真實對話問答內容
# ─────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("① 最近對話 ── 問題 + 完整回答")
print(SEP)

convs_r = requests.get(f"{BASE}/api/v1/chat/conversations?limit=5", headers=h).json()
convs = convs_r if isinstance(convs_r, list) else convs_r.get("items", convs_r.get("conversations", []))

for i, c in enumerate(convs[:5], 1):
    conv_id = c.get("id")
    title = c.get("title", "?")
    print(f"\n[對話 {i}]  {title}  (id={str(conv_id)[:8]}...)")
    print("-" * 50)

    msgs_r = requests.get(f"{BASE}/api/v1/chat/conversations/{conv_id}/messages?limit=20", headers=h).json()
    msgs = msgs_r if isinstance(msgs_r, list) else msgs_r.get("messages", msgs_r.get("items", []))

    for m in msgs:
        role = m.get("role", "?")
        content = m.get("content", "")
        label = "👤 USER   " if role == "user" else "🤖 ASSISTANT"
        print(f"\n{label}")
        # 印完整內容（最多 1000 字）
        if len(content) > 1000:
            print(content[:1000])
            print(f"  ... [省略餘下 {len(content)-1000} 字]")
        else:
            print(content)

# ─────────────────────────────────────────────────────────
# 2. 生成報告內容
# ─────────────────────────────────────────────────────────
print(f"\n\n{SEP}")
print("② 最近生成報告 ── 完整內容")
print(SEP)

rpts_r = requests.get(f"{BASE}/api/v1/generate/reports?limit=5", headers=h).json()
rpts = rpts_r if isinstance(rpts_r, list) else rpts_r.get("reports", rpts_r.get("items", []))

for i, rpt in enumerate(rpts[:3], 1):
    rpt_id = rpt.get("id")
    det_r = requests.get(f"{BASE}/api/v1/generate/reports/{rpt_id}", headers=h).json()
    title = det_r.get("title", "?")
    template = det_r.get("template", "?")
    prompt = det_r.get("prompt", "?")
    content = det_r.get("content", "")
    wc = det_r.get("word_count", len(content))

    print(f"\n[報告 {i}]  {title}")
    print(f"  模板: {template}  字數: {wc}")
    print(f"  提示詞: {prompt[:80]}")
    print(f"  --- 內容 ---")
    if len(content) > 2000:
        print(content[:2000])
        print(f"  ... [省略餘下 {len(content)-2000} 字]")
    else:
        print(content)

# ─────────────────────────────────────────────────────────
# 3. KB 搜尋真實 chunk 內容
# ─────────────────────────────────────────────────────────
print(f"\n\n{SEP}")
print("③ KB 搜尋 ── 真實 chunk 文字")
print(SEP)

queries = ["勞工退休金提撥率", "特休假計算"]
for q in queries:
    print(f"\n查詢：「{q}」")
    print("-" * 50)
    res_r = requests.post(f"{BASE}/api/v1/kb/search",
        json={"query": q, "top_k": 3, "search_mode": "hybrid"},
        headers={**h, "Content-Type": "application/json"}).json()
    results = res_r if isinstance(res_r, list) else res_r.get("results", res_r.get("chunks", []))
    for j, chunk in enumerate(results[:3], 1):
        text = chunk.get("text", chunk.get("content", ""))
        score = chunk.get("score", chunk.get("similarity", "?"))
        doc = chunk.get("document_title", chunk.get("filename", chunk.get("source", "?")))
        print(f"\n  [#{j}]  來源:{doc}  score={score}")
        print(textwrap.fill(text[:500], width=68, initial_indent="  ", subsequent_indent="  "))
        if len(text) > 500:
            print(f"  ... [+{len(text)-500} 字]")

print(f"\n\n{SEP}")
print("審查完成")
print(SEP)

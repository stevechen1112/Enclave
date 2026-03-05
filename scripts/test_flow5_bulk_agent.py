#!/usr/bin/env python3
"""
Enclave Flow 5：50+ 檔案大量 Agent 處理全流程測試
====================================================
完整測試 Agent 從設定到處理大量文件的端到端管道：
  準備 50+ 測試檔案 → 新增監控資料夾 → 掃描 → 分類 → 審核 →
  批次核准 → 入庫 → 語意搜尋驗證 → 清理

使用本地 test-data (23 檔) + 自動生成補充檔案 (27+) = 50+ 檔案

測試項目：
  T5-01  準備測試目錄（50+ 檔案）
  T5-02  新增監控資料夾
  T5-03  資料夾列表確認
  T5-04  觸發手動掃描
  T5-05  等待掃描完成（輪詢審核佇列）
  T5-06  審核佇列至少 50 項
  T5-07  掃描預覽 — Ollama 分類正確
  T5-08  駁回 2 個項目
  T5-09  修改 3 個項目分類
  T5-10  批次核准全部剩餘項目
  T5-11  觸發批次重索引
  T5-12  等待入庫完成
  T5-13  批次狀態統計正確
  T5-14  語意搜尋 — 薪資相關（命中生成檔）
  T5-15  語意搜尋 — 新人到職（命中真實檔）
  T5-16  語意搜尋 — 勞動契約（命中真實檔）
  T5-17  文件列表確認數量
  T5-18  批次報告端點可達
  T5-19  停止 Agent watcher
  T5-20  刪除監控資料夾
  T5-21  清理生成的測試檔案
  T5-22  清理結果摘要存檔

用法：
  python scripts/test_flow5_bulk_agent.py
  python scripts/test_flow5_bulk_agent.py --keep          # 保留資料不清理
  python scripts/test_flow5_bulk_agent.py --files 80      # 測試 80 檔
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Windows cp950 workaround: force UTF-8 stdout
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── UI ─────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def ok(name: str, detail: str = "") -> None:
    global passed
    passed += 1
    msg = f"  {GREEN}✔ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def fail(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  {RED}✘ {name}{RESET}"
    if detail:
        msg += f"  {DIM}({detail}){RESET}"
    print(msg)


def skip(name: str, reason: str = "") -> None:
    global skipped
    skipped += 1
    print(f"  {YELLOW}⊘ {name} — SKIP: {reason}{RESET}")


def section(title: str):
    print(f"\n{BOLD}{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}{RESET}")


def _assert(condition: bool, name: str, detail: str = "") -> bool:
    if condition:
        ok(name, detail)
    else:
        fail(name, detail)
    return condition


# ── API Client ─────────────────────────────────
class ApiClient:
    def __init__(self, base_url: str, user: str, password: str):
        self.base = base_url
        self.session = requests.Session()
        r = self.session.post(
            f"{self.base}/api/v1/auth/login/access-token",
            data={"username": user, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.session.get(f"{self.base}/api/v1{path}", timeout=30, **kwargs)

    def post(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.post(f"{self.base}/api/v1{path}", json=json_data, timeout=60, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.session.delete(f"{self.base}/api/v1{path}", timeout=15, **kwargs)

    def patch(self, path: str, json_data=None, **kwargs) -> requests.Response:
        return self.session.patch(f"{self.base}/api/v1{path}", json=json_data, timeout=15, **kwargs)

    def search(self, query: str, top_k: int = 5) -> dict:
        r = self.session.post(
            f"{self.base}/api/v1/kb/search",
            json={"query": query, "top_k": top_k},
            timeout=30,
        )
        return {"status_code": r.status_code, "body": r.json() if r.status_code == 200 else {}}


# ── Test Data Generation ───────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_DATA_DIR = PROJECT_ROOT / "test-data" / "company-documents"
BULK_TEST_DIR = PROJECT_ROOT / "test-data" / "_bulk_agent_test"

# Docker 容器掛載 .:/code
DOCKER_BULK_DIR = "/code/test-data/_bulk_agent_test"

# 自動生成的測試文件模板（HR 相關主題，分散內容以利分類測試）
GENERATED_FILE_TEMPLATES = [
    # 薪資相關 (5)
    ("salary/薪資結構說明.md", "# 薪資結構說明\n\n## 底薪\n員工底薪依職級區分：\n- 一般職：28,000 - 35,000\n- 專業職：35,000 - 55,000\n- 管理職：55,000 - 85,000\n\n## 加班費\n依勞基法規定，平日加班前2小時以1.34倍計算，第3小時起以1.67倍計算。\n\n## 全勤獎金\n每月全勤獎金 1,500 元，遲到一次即不發放。"),
    ("salary/年終獎金辦法.md", "# 年終獎金辦法\n\n## 發放時間\n每年農曆春節前一週統一發放。\n\n## 計算方式\n- 基本年終：保障1.5個月\n- 績效年終：依部門績效 0-2 個月\n\n## 資格\n- 需到職滿三個月以上\n- 試用期間不計入年終\n- 離職者按比例計算\n\n## 特殊規定\n因公受傷留停期間照常計算年終。"),
    ("salary/加班費計算範例.md", "# 加班費計算範例\n\n## 情境一：平日加班\n月薪 36,000 元，平日加班 3 小時\n- 時薪 = 36,000 ÷ 30 ÷ 8 = 150\n- 前 2 小時：150 × 1.34 × 2 = 402\n- 第 3 小時：150 × 1.67 × 1 = 250.5\n- 合計：652.5 元\n\n## 情境二：休息日加班\n- 前 2 小時：時薪 × 1.34\n- 第 3-8 小時：時薪 × 1.67\n- 第 9 小時以上：時薪 × 2.67"),
    ("salary/津貼補助辦法.md", "# 津貼補助辦法\n\n## 交通津貼\n- 一般員工：每月 1,500 元\n- 外勤人員：每月 3,000 元 + 實報實銷\n\n## 伙食津貼\n- 每月 2,400 元（免稅額度）\n\n## 住宿補助\n- 外派人員：提供宿舍或每月 8,000 元租屋補助\n\n## 進修補助\n- 與工作相關課程：全額補助\n- 學位進修：補助 50%，上限 50,000 元/年"),
    ("salary/績效獎金制度.md", "# 績效獎金制度\n\n## 評核週期\n每季評核一次，年度總結。\n\n## 評分標準\n- A 級（前 10%）：獎金 3 個月\n- B 級（前 30%）：獎金 2 個月\n- C 級（中間 40%）：獎金 1 個月\n- D 級（後 20%）：無績效獎金\n\n## 特殊加給\n- 專案完成獎：依專案規模 5,000 - 50,000\n- 年度 MVP：額外 2 個月薪資"),

    # 教育訓練 (5)
    ("training/新人訓練計畫.md", "# 新人訓練計畫\n\n## 第一週：環境適應\n- Day 1：報到、領取設備、認識環境\n- Day 2-3：公司制度與文化簡介\n- Day 4-5：部門介紹與導師配對\n\n## 第二週：專業入門\n- 線上學習平台基礎課程\n- 觀摩資深同仁作業\n\n## 第三-四週：實務操作\n- 在導師指導下執行簡單任務\n- 每週回報學習心得\n\n## 評估\n滿月後由導師與主管進行評估面談。"),
    ("training/導師制度辦法.md", "# 導師制度辦法\n\n## 導師資格\n- 年資滿 2 年以上\n- 最近一年績效 B 級以上\n- 完成導師培訓課程\n\n## 導師職責\n1. 每週至少一次 1-on-1 會議\n2. 協助新人熟悉業務流程\n3. 定期向 HR 回報新人適應狀況\n\n## 導師津貼\n每指導一位新人，額外補助 3,000 元/月，為期 3 個月。\n\n## 評核\n新人試用期結束後，根據新人表現評核導師成效。"),
    ("training/外部訓練申請流程.md", "# 外部訓練申請流程\n\n## 申請條件\n- 到職滿 6 個月以上\n- 課程與工作職能相關\n\n## 流程\n1. 填寫「外部訓練申請表」\n2. 直屬主管簽核\n3. HR 部門審查預算\n4. 核準後始可報名\n\n## 費用規定\n- 學費：公司全額負擔（上限 30,000/次）\n- 交通住宿：依出差標準辦理\n\n## 服務年限\n補助超過 20,000 元者，需簽署 1 年服務承諾。"),
    ("training/線上學習平台使用手冊.md", "# 線上學習平台使用手冊\n\n## 登入\n使用公司 Email 與 SSO 帳號登入 learn.company.com\n\n## 必修課程\n- 資安意識（每年更新）\n- 職場安全衛生（每年更新）\n- 性別平等教育（到職 1 個月內完成）\n\n## 選修課程\n依部門推薦選修專業課程，完成後可獲得學習點數。\n\n## 認證\n累積 100 學習點數可申請「年度學習達人」認證。\n\n## 技術問題\n聯繫 IT Helpdesk：helpdesk@company.com"),
    ("training/證照獎勵辦法.md", "# 證照獎勵辦法\n\n## 獎勵金額\n- 國家級證照：10,000 - 30,000 元\n- 國際認證（AWS/PMP/CFA等）：20,000 - 50,000 元\n- 其他專業證照：5,000 - 15,000 元\n\n## 申請流程\n取得證照後 30 天內，檢附證照影本向 HR 申請。\n\n## 注意事項\n- 同一證照僅獎勵一次\n- 考試費用可事前申請全額補助\n- 需通過後才核發獎勵金"),

    # 資安與IT (5)
    ("it-policy/資訊安全管理辦法.md", "# 資訊安全管理辦法\n\n## 密碼政策\n- 最少 12 字元，含大小寫英文、數字、特殊符號\n- 每 90 天強制更換\n- 不得重複最近 5 次使用的密碼\n\n## 存取控制\n- 依照最小權限原則配置\n- 離職當日即刻停用所有帳號\n- VPN 連線需雙因子認證\n\n## 事件通報\n發現資安異常需於 1 小時內通報 IT 部門。\n\n## 違規處分\n依情節嚴重程度，處以警告至免職處分。"),
    ("it-policy/設備管理辦法.md", "# 設備管理辦法\n\n## 配發設備\n- 筆電：到職時配發，規格依職務需求\n- 手機：主管級以上配發公務手機\n- 其他：依專案需求申請\n\n## 使用規範\n1. 公務設備不得安裝未經授權的軟體\n2. 離開座位需鎖定螢幕\n3. 不得將公務設備攜出國（需事前申請）\n\n## 歸還\n離職或設備升級時需完整歸還，損壞需照價賠償。"),
    ("it-policy/遠端工作資安規範.md", "# 遠端工作資安規範\n\n## VPN 連線\n- 遠端辦公必須全程使用公司 VPN\n- 禁止在公共 Wi-Fi 下未使用 VPN 存取公司系統\n\n## 環境要求\n- 獨立工作空間，避免機密資料外洩\n- 視訊會議時確認背景無敏感資訊\n\n## 資料保護\n- 公務資料不得存放於個人雲端硬碟\n- 列印機密文件需立即取回並妥善銷毀\n\n## 監控\n公司保留遠端連線紀錄查核之權利。"),
    ("it-policy/軟體授權管理.md", "# 軟體授權管理\n\n## 原則\n- 所有工作軟體必須使用正版授權\n- 由 IT 部門統一採購與管理\n\n## 申請流程\n1. 填寫軟體需求申請單\n2. 主管核准\n3. IT 評估替代方案與費用\n4. 採購安裝\n\n## 常用授權軟體\n- Office 365: 全員配置\n- Adobe CC: 設計部門\n- JetBrains: 開發部門\n\n## 禁止事項\n嚴禁安裝盜版軟體，違者依資安辦法懲處。"),
    ("it-policy/個資保護實施計畫.md", "# 個資保護實施計畫\n\n## 法規依據\n個人資料保護法及施行細則。\n\n## 個資範圍\n- 員工個資：姓名、身分證字號、地址、薪資\n- 客戶個資：聯絡方式、交易紀錄\n\n## 保護措施\n1. 個資存取需經授權\n2. 傳輸時需加密\n3. 保存期限到期後確實銷毀\n\n## 事故處理\n個資外洩需於 72 小時內通報主管機關，並通知當事人。\n\n## 年度稽核\n每年由外部機構進行個資保護稽核。"),

    # 行政庶務 (5)
    ("admin/會議室預約辦法.md", "# 會議室預約辦法\n\n## 預約方式\n透過公司內部系統 room.company.com 預約。\n\n## 會議室一覽\n- 大會議室（20人）：需提前 3 天預約\n- 中會議室（10人）：需提前 1 天預約\n- 小會議室（4人）：可當天預約\n\n## 使用規範\n1. 預約後未使用需提前取消\n2. 使用後恢復原狀\n3. 食物飲料需自行清理\n\n## 視訊設備\n大中型會議室備有視訊系統，使用前請先測試。"),
    ("admin/文具用品申請流程.md", "# 文具用品申請流程\n\n## 常備品\n筆、筆記本、便利貼、資料夾等常備文具，至總務處直接領取。\n\n## 特殊用品\n- 填寫「辦公用品申請單」\n- 主管簽核\n- 總務處統一採購\n- 每月 15 日截止申請，次月初到貨\n\n## 預算控制\n每部門每季文具預算上限 5,000 元。\n\n## 環保政策\n優先採購環保材質用品，鼓勵回收重複使用。"),
    ("admin/公務車使用管理.md", "# 公務車使用管理\n\n## 申請\n透過行政系統預約公務車，需載明用途、時間、目的地。\n\n## 使用規範\n1. 僅限公務使用\n2. 使用後填寫行車紀錄\n3. 加油使用公務卡\n4. 發現異常立即通報\n\n## 事故處理\n- 發生事故立即報警並通報總務\n- 填寫事故報告\n- 責任歸屬依調查結果處理\n\n## 保養維護\n由總務處統一安排定期保養。"),
    ("admin/辦公室門禁管理.md", "# 辦公室門禁管理\n\n## 門禁卡\n- 到職當日由總務處發放\n- 遺失需立即通報，補辦費用 200 元\n\n## 出入管制\n- 上班時間：07:00-22:00 刷卡進出\n- 非上班時間進入需事前申請\n- 訪客需由員工陪同，於大廳換證\n\n## 特殊區域\n- 機房：僅 IT 人員可進入\n- 主管辦公區：需另行授權\n\n## 紀錄保存\n門禁紀錄保存 90 天。"),
    ("admin/辦公環境管理規範.md", "# 辦公環境管理規範\n\n## 清潔\n- 每日清潔由外包團隊負責\n- 個人區域需自行維持整潔\n\n## 用餐區\n- 茶水間提供咖啡、茶包、飲水機\n- 微波爐、冰箱共用，定期清理\n- 禁止在座位區食用氣味重的食物\n\n## 空調\n- 辦公區域維持 24-26 度\n- 調整需聯繫總務處\n\n## 節能\n最後離開者需關閉燈光及非必要電器。"),

    # 人事異動 (4)
    ("hr-changes/升遷辦法.md", "# 升遷辦法\n\n## 升遷條件\n- 在現職級服務滿 1 年以上\n- 最近兩次績效評核 B 級以上\n- 完成該職級必修訓練\n\n## 升遷流程\n1. 部門主管提名\n2. HR 審核資格\n3. 升遷審查委員會決議\n4. 總經理核准\n\n## 升遷生效\n- 每年 4 月及 10 月為升遷生效月\n- 薪資自生效月起調整\n\n## 特殊升遷\n對公司有重大貢獻者，可不受年資限制提報特殊升遷。"),
    ("hr-changes/調動管理辦法.md", "# 調動管理辦法\n\n## 調動類型\n- 部門內調動：由部門主管直接安排\n- 跨部門調動：需雙方主管同意及 HR 協調\n- 外派調動：另簽外派合約\n\n## 員工權益\n- 調動不得降低薪資\n- 需提前 2 週通知\n- 跨縣市調動提供搬遷補助\n\n## 申請流程\n1. 填寫「人事異動申請表」\n2. 現任/新任主管簽核\n3. HR 審核\n4. 總經理核准"),
    ("hr-changes/離職作業流程.md", "# 離職作業流程\n\n## 自願離職\n1. 提前 30 天提出書面辭呈\n2. 主管約談了解原因\n3. HR 辦理離職面談\n\n## 交接事項\n- 工作交接：列出待辦事項清單\n- 設備歸還：筆電、手機、門禁卡\n- 帳號停用：最後工作日由 IT 處理\n\n## 結算\n- 特休未休工資\n- 當月薪資按比例\n- 三節獎金按比例\n\n## 離職證明\n最後工作日後 7 天內郵寄離職證明。"),
    ("hr-changes/留才計畫.md", "# 留才計畫\n\n## 關鍵人才定義\n- 高績效員工（連續兩年 A 級）\n- 核心技術持有者\n- 高潛力發展人員\n\n## 留才措施\n1. 個人發展計畫（IDP）\n2. 導師配對（高階主管）\n3. 特殊獎金（留任獎金 3-6 個月）\n4. 彈性工作安排\n\n## 預警機制\n- 主管定期進行一對一面談\n- 員工參與度問卷（每半年）\n- HR 離職風險預測模型"),

    # 福利制度 (3)
    ("benefits/員工旅遊辦法.md", "# 員工旅遊辦法\n\n## 資格\n到職滿 3 個月之員工均可參加。\n\n## 預算\n- 每人每年 8,000 元\n- 由福委會統一規劃\n\n## 形式\n- 國內旅遊：每年一次（2天1夜）\n- 部門聚餐：每季一次（3,000元/人）\n\n## 不參加者\n可折抵為等值禮券，於年底統一發放。\n\n## 眷屬參加\n可攜帶 1 名眷屬，費用自付。"),
    ("benefits/員工購物優惠.md", "# 員工購物優惠\n\n## 合作廠商\n- 健身房：月費 8 折\n- 保險：團體優惠費率\n- 3C 賣場：員工價 95 折\n- 餐廳：特約餐廳 85 折\n\n## 使用方式\n出示員工證或使用福利平台 QR Code。\n\n## 注意事項\n- 優惠限員工本人使用\n- 不得轉讓或代購\n- 合作廠商清單每季更新"),
    ("benefits/托兒補助辦法.md", "# 托兒補助辦法\n\n## 資格\n子女 0-6 歲之員工（含收養）。\n\n## 補助金額\n- 0-2 歲：每月 5,000 元\n- 3-6 歲：每月 3,000 元\n\n## 申請\n檢附子女出生證明或戶口名簿影本，向 HR 申請。\n\n## 公司托育\n公司附設托育中心（限總部），優先提供員工子女入托。\n\n## 法規依據\n依性別工作平等法第 23 條辦理。"),
]


def prepare_bulk_test_dir(target_count: int = 50) -> tuple[Path, int]:
    """
    準備 50+ 測試檔案的目錄。
    複製所有 test-data/company-documents 真實檔案 + 生成補充檔案。
    Returns (local_dir_path, total_file_count)
    """
    if BULK_TEST_DIR.exists():
        shutil.rmtree(BULK_TEST_DIR)
    BULK_TEST_DIR.mkdir(parents=True)

    file_count = 0

    # Step 1: 複製所有真實測試檔案
    if TEST_DATA_DIR.exists():
        for src_file in TEST_DATA_DIR.rglob("*"):
            if src_file.is_file() and "_bulk_agent_test" not in str(src_file):
                rel = src_file.relative_to(TEST_DATA_DIR)
                dst = BULK_TEST_DIR / "real" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst)
                file_count += 1

    print(f"  {DIM}複製真實檔案: {file_count} 個{RESET}")

    # Step 2: 生成補充檔案直到達標
    gen_count = 0
    for rel_path, content in GENERATED_FILE_TEMPLATES:
        if file_count >= target_count:
            break
        dst = BULK_TEST_DIR / "generated" / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
        file_count += 1
        gen_count += 1

    # 如果模板不夠，自動生成更多
    extra_idx = 0
    while file_count < target_count:
        extra_idx += 1
        topic = [
            "員工考勤", "出勤管理", "排班制度", "值班規定", "請假統計",
            "培訓記錄", "技能評測", "年度計畫", "部門預算", "採購流程",
            "客戶服務", "投訴處理", "品質管理", "風險評估", "合規檢查",
        ][(extra_idx - 1) % 15]

        dst = BULK_TEST_DIR / "generated" / "extra" / f"{topic}_{extra_idx:03d}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            f"# {topic}第 {extra_idx} 號文件\n\n"
            f"## 目的\n本文件為{topic}的第 {extra_idx} 份補充說明。\n\n"
            f"## 內容\n{'此處為' + topic + '相關的詳細規定與流程說明。' * 3}\n\n"
            f"## 適用範圍\n全體員工適用。\n\n"
            f"## 生效日期\n2026 年 1 月 1 日起生效。\n",
            encoding="utf-8",
        )
        file_count += 1

    print(f"  {DIM}生成補充檔案: {gen_count + extra_idx} 個{RESET}")
    print(f"  {DIM}總計: {file_count} 個檔案{RESET}")

    return BULK_TEST_DIR, file_count


# ══════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════
def run_tests(api: ApiClient, keep: bool, target_files: int):
    created_folder_id = None
    review_item_ids: list[str] = []
    rejected_ids: list[str] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = PROJECT_ROOT / "test-results" / f"flow5_bulk_agent_{ts}"
    results_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: 準備測試資料 ────────────
    section("Phase 1: 準備測試資料")

    local_dir, file_count = prepare_bulk_test_dir(target_files)
    _assert(
        file_count >= target_files,
        f"T5-01 準備測試目錄（{target_files}+ 檔案）",
        f"total={file_count}"
    )

    # 列出目錄結構
    all_files = sorted(local_dir.rglob("*"))
    all_files = [f for f in all_files if f.is_file()]
    file_list_path = results_dir / "T5-01_file_list.txt"
    with open(file_list_path, "w", encoding="utf-8") as f:
        f.write(f"# Flow 5 測試檔案清單（共 {len(all_files)} 檔）\n\n")
        for fpath in all_files:
            f.write(f"{fpath.relative_to(local_dir)}\n")
    print(f"  {DIM}檔案清單已存: {file_list_path.name}{RESET}")

    # ── Phase 2: Agent 資料夾管理 ────────
    section("Phase 2: 新增監控資料夾")

    # T5-02: Add folder
    r = api.post("/agent/folders", json_data={
        "folder_path": DOCKER_BULK_DIR,
        "display_name": f"Bulk Test {ts}",
        "recursive": True,
        "max_depth": 5,
        "default_category": "bulk-test",
    })
    if _assert(
        r.status_code in (200, 201),
        "T5-02 新增監控資料夾",
        f"HTTP {r.status_code}"
    ):
        folder_data = r.json()
        created_folder_id = folder_data.get("id")
        print(f"  {DIM}folder_id={created_folder_id}{RESET}")
    elif r.status_code == 409:
        ok("T5-02 監控資料夾已存在（409）")
        r2 = api.get("/agent/folders")
        if r2.status_code == 200:
            for f_item in r2.json():
                if f_item.get("folder_path") == DOCKER_BULK_DIR:
                    created_folder_id = f_item.get("id")
                    break

    # T5-03: 確認資料夾列表
    r = api.get("/agent/folders")
    if _assert(r.status_code == 200, "T5-03 資料夾列表確認", f"HTTP {r.status_code}"):
        folders = r.json()
        folder_ids = [str(f_item.get("id", "")) for f_item in folders]
        if created_folder_id:
            _assert(
                str(created_folder_id) in folder_ids,
                "T5-03b 列表包含新建資料夾",
                f"total={len(folders)}"
            )

    # ── Phase 3: 掃描 ───────────────────
    section("Phase 3: 掃描 & 分類")

    # T5-04: 觸發掃描
    r = api.post("/agent/scan")
    _assert(
        r.status_code == 200,
        "T5-04 觸發手動掃描",
        f"HTTP {r.status_code}"
    )

    # T5-05: 等待掃描完成 — 大量檔案需要更長時間
    print(f"  {DIM}等待掃描 + Ollama 分類處理 50+ 檔案...{RESET}")
    max_wait = 300  # 5 分鐘上限
    poll_interval = 10
    elapsed = 0
    pending_count = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        r = api.get("/agent/review", params={"limit": 1, "offset": 0})
        if r.status_code == 200:
            total = r.json().get("total", 0)
            if total >= file_count * 0.8:  # 80% 以上完成
                pending_count = total
                print(f"  {DIM}掃描進度: {total}/{file_count} 已分類 ({elapsed}s){RESET}")
                break
            print(f"  {DIM}掃描進度: {total}/{file_count} 已分類 ({elapsed}s)...{RESET}")
        else:
            print(f"  {DIM}輪詢中... ({elapsed}s){RESET}")

    _assert(
        pending_count >= file_count * 0.5,
        "T5-05 等待掃描完成",
        f"pending={pending_count}, expected≈{file_count}, elapsed={elapsed}s"
    )

    # T5-06: 審核佇列驗證
    r = api.get("/agent/review", params={"limit": 200, "offset": 0})
    if _assert(r.status_code == 200, "T5-06 審核佇列端點", f"HTTP {r.status_code}"):
        review_data = r.json()
        items = review_data.get("items", [])
        total = review_data.get("total", 0)
        _assert(
            total >= target_files * 0.5,
            f"T5-06b 審核佇列至少 {int(target_files * 0.5)} 項",
            f"total={total}"
        )
        review_item_ids = [item["id"] for item in items if item.get("status") == "pending"]
        print(f"  {DIM}取得 {len(review_item_ids)} 個 pending 項目{RESET}")

        # 存檔審核佇列內容
        queue_path = results_dir / "T5-06_review_queue.json"
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump({
                "total": total,
                "items_returned": len(items),
                "sample_items": [
                    {
                        "id": item.get("id"),
                        "file_name": item.get("file_name"),
                        "suggested_category": item.get("suggested_category"),
                        "confidence_score": item.get("confidence_score"),
                        "status": item.get("status"),
                    }
                    for item in items[:20]
                ]
            }, f, ensure_ascii=False, indent=2)
        print(f"  {DIM}審核佇列已存: {queue_path.name}{RESET}")

    # T5-07: scan-preview 分類
    r = api.post("/agent/scan-preview", json_data={
        "subfolders": [
            {
                "path": "generated/salary",
                "name": "薪資",
                "files": ["薪資結構說明.md", "年終獎金辦法.md"],
                "content_samples": ["員工底薪依職級區分，一般職28000起，加班費依勞基法1.34倍計算"]
            },
            {
                "path": "generated/training",
                "name": "教育訓練",
                "files": ["新人訓練計畫.md"],
                "content_samples": ["新人報到第一週環境適應，第二週專業入門，導師配對制度"]
            }
        ]
    })
    if _assert(r.status_code == 200, "T5-07 掃描預覽 Ollama 分類", f"HTTP {r.status_code}"):
        preview = r.json()
        subfolders = preview.get("subfolders", [])
        if subfolders:
            for sf in subfolders:
                print(f"      {DIM}{sf.get('name')}: {sf.get('summary', '?')[:80]}{RESET}")

    # ── Phase 4: 審核操作 ────────────────
    section("Phase 4: 審核操作（駁回 + 修改 + 批次核准）")

    # T5-08: 駁回 2 個項目
    rejected_count = 0
    for i, item_id in enumerate(review_item_ids[:2]):
        r = api.post(f"/agent/review/{item_id}/reject", json_data={"reason": f"自動測試駁回 #{i+1}"})
        if r.status_code == 200:
            rejected_count += 1
            rejected_ids.append(item_id)
    _assert(
        rejected_count == min(2, len(review_item_ids)),
        "T5-08 駁回 2 個項目",
        f"rejected={rejected_count}"
    )

    # T5-09: 修改 3 個項目分類
    modified_count = 0
    custom_categories = ["薪資福利-已修正", "IT政策-已修正", "行政庶務-已修正"]
    for i, item_id in enumerate(review_item_ids[2:5]):
        r = api.post(f"/agent/review/{item_id}/modify", json_data={
            "category": custom_categories[i],
            "tags": {"source": "bulk-test", "modified_by": "flow5"},
            "note": f"Flow5 批量測試修改 #{i+1}",
        })
        if r.status_code == 200:
            modified_count += 1
    _assert(
        modified_count == min(3, max(0, len(review_item_ids) - 2)),
        "T5-09 修改 3 個項目分類",
        f"modified={modified_count}"
    )

    # T5-10: 批次核准全部剩餘項目
    remaining_ids = [rid for rid in review_item_ids[5:] if rid not in rejected_ids]
    if remaining_ids:
        # 分批核准（每批 50 個，避免單次過大）
        batch_size = 50
        total_approved = 0
        for batch_start in range(0, len(remaining_ids), batch_size):
            batch = remaining_ids[batch_start:batch_start + batch_size]
            r = api.post("/agent/review/batch-approve", json_data={"item_ids": batch})
            if r.status_code == 200:
                approved = r.json().get("approved_count", 0)
                total_approved += approved
                print(f"      {DIM}batch {batch_start//batch_size + 1}: approved {approved}/{len(batch)}{RESET}")
            else:
                fail(f"T5-10 batch #{batch_start//batch_size + 1}", f"HTTP {r.status_code}")

        _assert(
            total_approved > 0,
            "T5-10 批次核准全部剩餘項目",
            f"approved={total_approved}/{len(remaining_ids)}"
        )
    else:
        skip("T5-10 批次核准", "無剩餘待審項目")

    # ── Phase 5: 入庫處理 ────────────────
    section("Phase 5: 入庫 & 索引")

    # T5-11: 觸發批次重索引
    r = api.post("/agent/batches/trigger")
    _assert(
        r.status_code == 200,
        "T5-11 觸發批次重索引",
        f"HTTP {r.status_code}"
    )

    # T5-12: 等待入庫完成
    print(f"  {DIM}等待入庫處理（最多 5 分鐘）...{RESET}")
    max_wait = 300
    poll_interval = 15
    elapsed = 0
    indexed_count = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval

        r = api.get("/agent/batches")
        if r.status_code == 200:
            summary = r.json().get("status_summary", {})
            indexed_count = summary.get("indexed", 0) + summary.get("approved", 0)
            pending = summary.get("pending", 0)
            print(f"  {DIM}索引進度: indexed={summary.get('indexed', 0)}, "
                  f"approved={summary.get('approved', 0)}, pending={pending} ({elapsed}s){RESET}")
            if pending == 0 and indexed_count > 0:
                break

    _assert(
        indexed_count > 0,
        "T5-12 入庫完成",
        f"indexed={indexed_count}, elapsed={elapsed}s"
    )

    # T5-13: 批次狀態統計
    r = api.get("/agent/batches")
    if _assert(r.status_code == 200, "T5-13 批次狀態統計正確", f"HTTP {r.status_code}"):
        summary = r.json().get("status_summary", {})
        print(f"      {DIM}{json.dumps(summary, ensure_ascii=False)}{RESET}")

        # 存檔批次狀態
        batch_path = results_dir / "T5-13_batch_status.json"
        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    # ── Phase 6: 語意搜尋驗證 ────────────
    section("Phase 6: 語意搜尋驗證")

    search_tests = [
        ("T5-14", "薪資結構 底薪 加班費", "generated/salary"),
        ("T5-15", "新人到職 報到流程 訓練", "real/sop"),
        ("T5-16", "勞動契約 工作規則 聘僱", "real/contracts"),
    ]

    search_results_all = []
    for test_id, query, expected_from in search_tests:
        result = api.search(query, top_k=5)
        if _assert(
            result["status_code"] == 200,
            f"{test_id} 語意搜尋 '{query[:10]}…'",
            f"HTTP {result['status_code']}"
        ):
            results = result["body"].get("results", [])
            if results:
                top_file = results[0].get("document_name", results[0].get("filename", "?"))
                _assert(
                    len(results) > 0,
                    f"{test_id}b 有搜尋結果",
                    f"top={top_file}, total={len(results)}"
                )
                search_results_all.append({
                    "test_id": test_id,
                    "query": query,
                    "expected_from": expected_from,
                    "results_count": len(results),
                    "top_results": [
                        {
                            "filename": r.get("document_name", r.get("filename", "?")),
                            "score": r.get("score", r.get("similarity", 0)),
                            "snippet": r.get("content", r.get("text", ""))[:100],
                        }
                        for r in results[:3]
                    ]
                })
            else:
                fail(f"{test_id}b 無搜尋結果", "可能入庫尚未完成")

    # 存檔搜尋結果
    if search_results_all:
        search_path = results_dir / "T5-14_16_search_results.json"
        with open(search_path, "w", encoding="utf-8") as f:
            json.dump(search_results_all, f, ensure_ascii=False, indent=2)
        print(f"  {DIM}搜尋結果已存: {search_path.name}{RESET}")

    # T5-17: 文件列表確認
    r = api.get("/documents", params={"limit": 200})
    if r.status_code == 200:
        docs = r.json()
        doc_count = len(docs) if isinstance(docs, list) else docs.get("total", 0)
        print(f"  {DIM}系統內文件總數: {doc_count}{RESET}")
    else:
        print(f"  {DIM}文件列表查詢失敗: HTTP {r.status_code}{RESET}")

    # T5-18: 批次報告
    r = api.get("/agent/batches/report")
    _assert(
        r.status_code == 200,
        "T5-18 批次報告端點可達",
        f"HTTP {r.status_code}, size={len(r.content)} bytes"
    )
    if r.status_code == 200 and len(r.content) > 0:
        report_path = results_dir / "T5-18_batch_report.pdf"
        report_path.write_bytes(r.content)
        print(f"  {DIM}報告已存: {report_path.name}{RESET}")

    # ── Phase 7: Agent 生命週期 ──────────
    section("Phase 7: Agent Watcher")

    # T5-19: 停止 watcher
    r = api.post("/agent/stop")
    _assert(
        r.status_code == 200,
        "T5-19 停止 Agent watcher",
        f"HTTP {r.status_code}"
    )

    # ── Phase 8: 清理 ───────────────────
    section("Phase 8: 清理")

    if keep:
        print(f"  {YELLOW}--keep 模式，跳過刪除{RESET}")
    else:
        # T5-20: 刪除監控資料夾
        if created_folder_id:
            r = api.delete(f"/agent/folders/{created_folder_id}")
            _assert(
                r.status_code in (200, 204),
                "T5-20 刪除監控資料夾",
                f"HTTP {r.status_code}"
            )
        else:
            skip("T5-20 刪除監控資料夾", "無 folder_id")

        # T5-21: 清理生成的測試檔案
        if BULK_TEST_DIR.exists():
            shutil.rmtree(BULK_TEST_DIR)
            _assert(
                not BULK_TEST_DIR.exists(),
                "T5-21 清理生成的測試檔案",
                str(BULK_TEST_DIR)
            )
        else:
            ok="T5-21 測試目錄已不存在"

    # ── T5-22: 結果摘要存檔 ─────────────
    section("Phase 9: 結果摘要")

    summary_path = results_dir / "_SUMMARY.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# Flow 5 大量 Agent 處理測試結果\n\n")
        f.write(f"**執行時間**: {ts}\n\n")
        f.write(f"**目標檔案數**: {target_files}\n\n")
        f.write(f"**實際準備**: {file_count} 個檔案\n\n")
        f.write(f"**結果**: 通過={passed}, 失敗={failed}, 跳過={skipped}\n\n")
        f.write(f"## 存檔清單\n\n")
        for sf in sorted(results_dir.iterdir()):
            if sf.name != "_SUMMARY.md":
                f.write(f"- [{sf.name}]({sf.name})\n")

    _assert(True, "T5-22 結果摘要存檔", str(results_dir))
    print(f"\n  {DIM}📁 測試結果已存: {results_dir}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Enclave Flow 5 — 50+ 檔案大量 Agent 全流程測試")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--user", default="admin@example.com")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="保留測試資料不刪除")
    parser.add_argument("--files", type=int, default=50, help="目標測試檔案數（預設 50）")
    args = parser.parse_args()

    print(f"\n{BOLD}═══════════════════════════════════════════════════")
    print(f"  Enclave Flow 5：50+ 檔案大量 Agent 全流程測試")
    print(f"  Target: {args.base_url}")
    print(f"  Files:  {args.files}+")
    print(f"═══════════════════════════════════════════════════{RESET}")

    try:
        api = ApiClient(args.base_url, args.user, args.password)
        ok("登入成功")
    except Exception as e:
        fail(f"登入失敗: {e}")
        sys.exit(1)

    run_tests(api, keep=args.keep, target_files=args.files)

    section("結果摘要")
    total = passed + failed + skipped
    print(f"  {GREEN}通過: {passed}{RESET}  {RED}失敗: {failed}{RESET}  {YELLOW}跳過: {skipped}{RESET}  總計: {total}")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()

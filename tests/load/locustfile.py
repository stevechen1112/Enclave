"""
Enclave 負載測試腳本 — Locust
==================================

測試情境：
- 100 concurrent users
- 目標 1000 req/min
- 涵蓋：認證、聊天、文件上傳、知識庫檢索、Admin API

啟動方式：
    # Web UI 模式
    locust -f tests/load/locustfile.py --host=http://localhost:8000

    # Headless 模式（CI 適用）
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \
           --headless -u 100 -r 10 --run-time 5m \
           --csv=tests/load/results/report

    # 指定情境（只跑 Chat）
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \
           --headless -u 50 -r 5 --run-time 3m \
           --tags chat
"""

import os
import json
import random
import string
from locust import HttpUser, task, between, tag, events
from locust.runners import MasterRunner


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
ADMIN_EMAIL = os.getenv("LOAD_TEST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("LOAD_TEST_ADMIN_PASSWORD", "admin123")
USER_EMAIL = os.getenv("LOAD_TEST_USER_EMAIL", "user@example.com")
USER_PASSWORD = os.getenv("LOAD_TEST_USER_PASSWORD", "user123")
SUPERUSER_EMAIL = os.getenv("LOAD_TEST_SUPERUSER_EMAIL", "superadmin@example.com")
SUPERUSER_PASSWORD = os.getenv("LOAD_TEST_SUPERUSER_PASSWORD", "superadmin123")


# ---------------------------------------------------------------------------
# 效能基準線定義
# ---------------------------------------------------------------------------
PERFORMANCE_BASELINES = {
    "auth_login":          {"p95": 500,   "p99": 1000,  "error_rate": 0.01},
    "chat_send":           {"p95": 3000,  "p99": 5000,  "error_rate": 0.02},
    "document_list":       {"p95": 300,   "p99": 600,   "error_rate": 0.01},
    "kb_search":           {"p95": 1000,  "p99": 2000,  "error_rate": 0.02},
    "admin_dashboard":     {"p95": 500,   "p99": 1000,  "error_rate": 0.01},
    "health_check":        {"p95": 100,   "p99": 200,   "error_rate": 0.00},
    "subscription_plans":  {"p95": 200,   "p99": 400,   "error_rate": 0.01},
}


def _random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


# ---------------------------------------------------------------------------
# 一般使用者行為
# ---------------------------------------------------------------------------
class RegularUser(HttpUser):
    """模擬一般員工：登入 → 聊天 → 查文件 → 查知識庫"""

    wait_time = between(1, 5)
    weight = 7  # 70% 是一般使用者

    def on_start(self):
        """登入取得 JWT Token"""
        resp = self.client.post(
            "/api/v1/auth/login",
            data={"username": USER_EMAIL, "password": USER_PASSWORD},
            name="auth_login",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    # ----- Chat -----
    @tag("chat")
    @task(5)
    def chat_send_message(self):
        """送出聊天訊息（最高頻操作）"""
        questions = [
            "請問特休怎麼計算？",
            "加班費的計算方式？",
            "員工離職預告期是多長？",
            "產假有幾天？薪水怎麼算？",
            "勞基法規定的工時上限？",
            "資遣費計算方式？",
            "試用期有法律規定嗎？",
            "哺乳時間相關規定？",
        ]
        self.client.post(
            "/api/v1/chat/",
            json={"question": random.choice(questions)},
            headers=self.headers,
            name="chat_send",
            timeout=30,
        )

    # ----- Documents -----
    @tag("documents")
    @task(2)
    def list_documents(self):
        """列出文件清單"""
        self.client.get(
            "/api/v1/documents/",
            headers=self.headers,
            name="document_list",
        )

    # ----- Knowledge Base -----
    @tag("kb")
    @task(3)
    def search_knowledge_base(self):
        """知識庫搜尋"""
        queries = [
            "特休假",
            "加班",
            "離職",
            "請假規定",
            "勞工保險",
        ]
        self.client.get(
            "/api/v1/kb/search",
            params={"q": random.choice(queries), "top_k": 5},
            headers=self.headers,
            name="kb_search",
        )

    # ----- Profile -----
    @tag("profile")
    @task(1)
    def get_my_profile(self):
        """查看個人資料"""
        self.client.get(
            "/api/v1/users/me",
            headers=self.headers,
            name="user_profile",
        )

    # ----- Conversations -----
    @tag("chat")
    @task(2)
    def list_conversations(self):
        """列出對話記錄"""
        self.client.get(
            "/api/v1/chat/conversations",
            headers=self.headers,
            name="chat_conversations_list",
        )

    # ----- Subscription -----
    @tag("subscription")
    @task(1)
    def check_subscription(self):
        """查看訂閱方案"""
        self.client.get(
            "/api/v1/subscription/current",
            headers=self.headers,
            name="subscription_current",
        )


# ---------------------------------------------------------------------------
# HR / Admin 使用者行為
# ---------------------------------------------------------------------------
class HRAdminUser(HttpUser):
    """模擬 HR 管理員：管理文件、查稽核、設定公司"""

    wait_time = between(2, 8)
    weight = 2  # 20% 管理者

    def on_start(self):
        resp = self.client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            name="auth_login",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @tag("documents")
    @task(3)
    def upload_document(self):
        """上傳文件（模擬小型文件）"""
        fake_content = f"公司內部規定 - {_random_string(16)}\n" * 50
        files = {
            "file": (
                f"test_doc_{_random_string(6)}.txt",
                fake_content.encode("utf-8"),
                "text/plain",
            )
        }
        self.client.post(
            "/api/v1/documents/upload",
            files=files,
            headers=self.headers,
            name="document_upload",
        )

    @tag("documents")
    @task(2)
    def list_documents(self):
        self.client.get(
            "/api/v1/documents/",
            headers=self.headers,
            name="document_list",
        )

    @tag("audit")
    @task(2)
    def view_audit_logs(self):
        """查看稽核記錄"""
        self.client.get(
            "/api/v1/audit/logs",
            params={"skip": 0, "limit": 20},
            headers=self.headers,
            name="audit_logs",
        )

    @tag("audit")
    @task(1)
    def view_usage_summary(self):
        """查看用量摘要"""
        self.client.get(
            "/api/v1/audit/usage/summary",
            headers=self.headers,
            name="audit_usage_summary",
        )

    @tag("company")
    @task(1)
    def get_company_branding(self):
        """取得公司品牌設定"""
        self.client.get(
            "/api/v1/company/branding",
            headers=self.headers,
            name="company_branding",
        )

    @tag("chat")
    @task(2)
    def chat_send_message(self):
        questions = [
            "員工違反工作規則怎麼處理？",
            "如何合法解僱員工？",
            "勞動檢查要準備什麼？",
        ]
        self.client.post(
            "/api/v1/chat/",
            json={"question": random.choice(questions)},
            headers=self.headers,
            name="chat_send",
            timeout=30,
        )


# ---------------------------------------------------------------------------
# 平台管理員行為
# ---------------------------------------------------------------------------
class PlatformAdmin(HttpUser):
    """模擬平台超級管理員：Dashboard、租戶管理、系統健康"""

    wait_time = between(3, 10)
    weight = 1  # 10%

    def on_start(self):
        resp = self.client.post(
            "/api/v1/auth/login",
            data={"username": SUPERUSER_EMAIL, "password": SUPERUSER_PASSWORD},
            name="auth_login",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = ""
            self.headers = {}

    @tag("admin")
    @task(3)
    def admin_dashboard(self):
        """平台總覽 Dashboard"""
        self.client.get(
            "/api/v1/admin/dashboard",
            headers=self.headers,
            name="admin_dashboard",
        )

    @tag("admin")
    @task(2)
    def admin_list_tenants(self):
        """列出所有租戶"""
        self.client.get(
            "/api/v1/admin/tenants",
            headers=self.headers,
            name="admin_tenants_list",
        )

    @tag("admin")
    @task(1)
    def admin_system_health(self):
        """系統健康檢查"""
        self.client.get(
            "/api/v1/admin/system/health",
            headers=self.headers,
            name="admin_system_health",
        )

    @tag("analytics")
    @task(2)
    def analytics_daily_trends(self):
        """每日趨勢"""
        self.client.get(
            "/api/v1/analytics/trends/daily",
            params={"days": 7},
            headers=self.headers,
            name="analytics_daily_trends",
        )

    @tag("analytics")
    @task(1)
    def analytics_anomalies(self):
        """異常偵測"""
        self.client.get(
            "/api/v1/analytics/anomalies",
            headers=self.headers,
            name="analytics_anomalies",
        )

    @tag("analytics")
    @task(1)
    def analytics_budget_alerts(self):
        """預算告警"""
        self.client.get(
            "/api/v1/analytics/budget-alerts",
            headers=self.headers,
            name="analytics_budget_alerts",
        )


# ---------------------------------------------------------------------------
# 健康檢查（背景監控）
# ---------------------------------------------------------------------------
class HealthChecker(HttpUser):
    """持續 /health 探活"""

    wait_time = between(5, 15)
    weight = 0  # 不佔比例，手動啟用

    @tag("health")
    @task
    def health_check(self):
        self.client.get("/health", name="health_check")

    @tag("health")
    @task
    def metrics_check(self):
        self.client.get("/metrics", name="metrics_check")


# ---------------------------------------------------------------------------
# 事件 Hook：測試結束時輸出效能基準線比對
# ---------------------------------------------------------------------------
@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """測試結束時比對效能基準線，並輸出結果"""
    if isinstance(environment.runner, MasterRunner):
        return  # 分散式模式只在 master 處理

    stats = environment.runner.stats
    print("\n" + "=" * 70)
    print("📊 效能基準線比對結果")
    print("=" * 70)

    violations = []

    for name, baseline in PERFORMANCE_BASELINES.items():
        entry = stats.entries.get((name, ""), None)
        if entry is None or entry.num_requests == 0:
            print(f"  ⚪ {name:30s}  — 無資料（未觸發）")
            continue

        p95 = entry.get_response_time_percentile(0.95) or 0
        p99 = entry.get_response_time_percentile(0.99) or 0
        error_rate = entry.fail_ratio

        status_p95 = "✅" if p95 <= baseline["p95"] else "❌"
        status_p99 = "✅" if p99 <= baseline["p99"] else "❌"
        status_err = "✅" if error_rate <= baseline["error_rate"] else "❌"

        print(
            f"  {name:30s}  "
            f"P95={p95:>6.0f}ms ({status_p95} ≤{baseline['p95']}ms)  "
            f"P99={p99:>6.0f}ms ({status_p99} ≤{baseline['p99']}ms)  "
            f"Err={error_rate:>5.1%} ({status_err} ≤{baseline['error_rate']:.0%})"
        )

        if p95 > baseline["p95"] or p99 > baseline["p99"] or error_rate > baseline["error_rate"]:
            violations.append(name)

    print("=" * 70)
    if violations:
        print(f"⚠️  共 {len(violations)} 個端點未達基準線：{', '.join(violations)}")
    else:
        print("✅ 所有端點均達到效能基準線！")
    print("=" * 70 + "\n")

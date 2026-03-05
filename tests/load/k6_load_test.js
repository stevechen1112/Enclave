/**
 * Enclave k6 負載測試腳本
 * ============================
 *
 * 使用方式：
 *   # 基本測試
 *   k6 run tests/load/k6_load_test.js
 *
 *   # 自訂參數
 *   k6 run tests/load/k6_load_test.js \
 *     --env BASE_URL=http://localhost:8000 \
 *     --env VUS=100 \
 *     --env DURATION=5m
 *
 *   # 輸出 JSON 報告
 *   k6 run tests/load/k6_load_test.js --out json=results.json
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

// ---------------------------------------------------------------------------
// 自訂指標
// ---------------------------------------------------------------------------
const loginDuration = new Trend("login_duration", true);
const chatDuration = new Trend("chat_duration", true);
const searchDuration = new Trend("kb_search_duration", true);
const docListDuration = new Trend("doc_list_duration", true);
const errorRate = new Rate("errors");
const successfulLogins = new Counter("successful_logins");

// ---------------------------------------------------------------------------
// 設定
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const USER_EMAIL = __ENV.USER_EMAIL || "user@example.com";
const USER_PASSWORD = __ENV.USER_PASSWORD || "user123";
const ADMIN_EMAIL = __ENV.ADMIN_EMAIL || "admin@example.com";
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD || "admin123";

// ---------------------------------------------------------------------------
// 測試情境（4 階段壓力測試）
// ---------------------------------------------------------------------------
export const options = {
  scenarios: {
    // 情境 1：漸進式壓力測試
    ramp_up: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "1m", target: 20 },   // Warm up
        { duration: "3m", target: 50 },   // 中負載
        { duration: "3m", target: 100 },  // 高負載
        { duration: "2m", target: 150 },  // 壓力測試
        { duration: "1m", target: 0 },    // Cool down
      ],
      gracefulRampDown: "30s",
    },
  },
  thresholds: {
    // 全域門檻
    http_req_duration: ["p(95)<2000", "p(99)<5000"],
    http_req_failed: ["rate<0.05"],        // 錯誤率 < 5%
    errors: ["rate<0.1"],

    // 個別端點門檻
    login_duration: ["p(95)<500"],
    chat_duration: ["p(95)<3000"],
    kb_search_duration: ["p(95)<1000"],
    doc_list_duration: ["p(95)<300"],
  },
};

// ---------------------------------------------------------------------------
// 輔助函數
// ---------------------------------------------------------------------------
function login(email, password) {
  const payload = `username=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`;
  const params = {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    tags: { name: "auth_login" },
  };

  const res = http.post(`${BASE_URL}/api/v1/auth/login`, payload, params);
  loginDuration.add(res.timings.duration);

  const success = check(res, {
    "login status 200": (r) => r.status === 200,
    "login has token": (r) => {
      try { return JSON.parse(r.body).access_token !== undefined; }
      catch { return false; }
    },
  });

  if (success) {
    successfulLogins.add(1);
    return JSON.parse(res.body).access_token;
  }
  errorRate.add(1);
  return null;
}

function authHeaders(token) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

// ---------------------------------------------------------------------------
// 主測試流程
// ---------------------------------------------------------------------------
export default function () {
  const vuId = __VU;

  // ----- 登入 -----
  let token;
  group("Authentication", () => {
    token = login(USER_EMAIL, USER_PASSWORD);
  });

  if (!token) {
    sleep(2);
    return;
  }

  const headers = authHeaders(token);

  // ----- Chat API -----
  group("Chat", () => {
    const questions = [
      "特休假怎麼計算？",
      "加班費計算方式？",
      "離職預告期規定？",
      "產假天數及薪資？",
      "勞基法工時上限？",
    ];
    const question = questions[Math.floor(Math.random() * questions.length)];

    const chatRes = http.post(
      `${BASE_URL}/api/v1/chat/`,
      JSON.stringify({ question }),
      {
        ...headers,
        headers: { ...headers.headers, "Content-Type": "application/json" },
        tags: { name: "chat_send" },
        timeout: "30s",
      }
    );

    chatDuration.add(chatRes.timings.duration);
    const chatOk = check(chatRes, {
      "chat status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
    if (!chatOk) errorRate.add(1);
  });

  sleep(1);

  // ----- KB Search -----
  group("Knowledge Base", () => {
    const queries = ["特休假", "加班", "離職", "請假", "勞保"];
    const q = queries[Math.floor(Math.random() * queries.length)];

    const searchRes = http.get(
      `${BASE_URL}/api/v1/kb/search?q=${encodeURIComponent(q)}&top_k=5`,
      { ...headers, tags: { name: "kb_search" } }
    );

    searchDuration.add(searchRes.timings.duration);
    check(searchRes, {
      "kb search status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
  });

  sleep(0.5);

  // ----- Documents -----
  group("Documents", () => {
    const docRes = http.get(`${BASE_URL}/api/v1/documents/`, {
      ...headers,
      tags: { name: "document_list" },
    });

    docListDuration.add(docRes.timings.duration);
    check(docRes, {
      "doc list status 2xx": (r) => r.status >= 200 && r.status < 300,
    });
  });

  sleep(0.5);

  // ----- User Profile -----
  group("User Profile", () => {
    const meRes = http.get(`${BASE_URL}/api/v1/users/me`, {
      ...headers,
      tags: { name: "user_profile" },
    });
    check(meRes, {
      "profile status 200": (r) => r.status === 200,
    });
  });

  sleep(0.5);

  // ----- Subscription -----
  group("Subscription", () => {
    const planRes = http.get(`${BASE_URL}/api/v1/subscription/plans`, {
      tags: { name: "subscription_plans" },
    });
    check(planRes, {
      "plans status 200": (r) => r.status === 200,
    });
  });

  // ----- Health -----
  group("Health", () => {
    const healthRes = http.get(`${BASE_URL}/health`, {
      tags: { name: "health_check" },
    });
    check(healthRes, {
      "health status 200": (r) => r.status === 200,
    });
  });

  sleep(Math.random() * 3 + 1);
}

// ---------------------------------------------------------------------------
// 測試結束摘要
// ---------------------------------------------------------------------------
export function handleSummary(data) {
  const summary = {
    timestamp: new Date().toISOString(),
    totalRequests: data.metrics.http_reqs ? data.metrics.http_reqs.values.count : 0,
    failedRequests: data.metrics.http_req_failed
      ? data.metrics.http_req_failed.values.passes
      : 0,
    avgDuration: data.metrics.http_req_duration
      ? data.metrics.http_req_duration.values.avg.toFixed(2)
      : "N/A",
    p95Duration: data.metrics.http_req_duration
      ? data.metrics.http_req_duration.values["p(95)"].toFixed(2)
      : "N/A",
    p99Duration: data.metrics.http_req_duration
      ? data.metrics.http_req_duration.values["p(99)"].toFixed(2)
      : "N/A",
    thresholds: {},
  };

  for (const [key, val] of Object.entries(data.metrics)) {
    if (val.thresholds) {
      summary.thresholds[key] = val.thresholds;
    }
  }

  return {
    "tests/load/results/k6_summary.json": JSON.stringify(summary, null, 2),
    stdout: textSummary(data, { indent: " ", enableColors: true }),
  };
}

// k6 built-in text summary (imported via k6 bundler)
import { textSummary } from "https://jslib.k6.io/k6-summary/0.0.2/index.js";

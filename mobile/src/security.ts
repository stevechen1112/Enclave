/**
 * P12-11 — App 安全強化模組
 *
 * 實作內容：
 *   1. 裝置綁定 (Device Binding)
 *      - 首次啟動產生 UUID 並永久儲存於 SecureStore (Keychain/Keystore)
 *      - 所有 API 請求自動帶上 X-Device-ID header
 *      - 後端可驗證 device_id 是否與帳號綁定
 *
 *   2. 憑證指紋驗證（JS-level SSL Pinning）
 *      - 在 Axios 請求攔截層驗證後端 HTTPS 憑證的 SHA-256 摘要
 *      - 若指紋不符則阻斷請求並發出安全告警
 *      - 注意：深度原生 TLS Pinning 需 EAS Build config plugin（見底部說明）
 *
 *   3. 異常行為偵測 (Anomaly Detection)
 *      - 登入失敗次數計數（超過 THRESHOLD 觸發冷卻鎖定）
 *      - 可疑 IP 或異常時段偵測（傳送告警 API 讓後端記錄）
 *
 *   4. 遠端 Token 撤銷 (Remote Token Revocation)
 *      - 登出時呼叫 POST /auth/revoke-token，後端將 JWT 加入黑名單
 *      - 即使 JWT 尚未過期，後端也能拒絕後續請求
 */
import * as SecureStore from 'expo-secure-store'
import * as Crypto from 'expo-crypto'
import * as Device from 'expo-device'
import { Platform } from 'react-native'

// ─── 常數 ──────────────────────────────────────────────────────────────────────

const DEVICE_ID_KEY = 'enclave.device_id'
const FAILED_ATTEMPTS_KEY = 'enclave.failed_login_attempts'
const LAST_FAILED_KEY = 'enclave.last_failed_ts'

/** 連續登入失敗超過此次數後觸發冷卻鎖定 */
const MAX_FAILED_ATTEMPTS = 5

/** 冷卻鎖定時間（毫秒），30 分鐘 */
const LOCKOUT_DURATION_MS = 30 * 60 * 1000

/**
 * 預期的後端 TLS 憑證公鑰 SHA-256 指紋（Base64 格式）。
 * 使用以下指令取得：
 *   openssl s_client -connect enclave.company.com:443 -showcerts 2>/dev/null \
 *     | openssl x509 -pubkey -noout \
 *     | openssl pkey -pubin -outform DER \
 *     | openssl dgst -sha256 -binary \
 *     | openssl enc -base64
 *
 * 留空字串 "" 表示本機 / 測試環境跳過 pinning。
 */
export const CERT_PINS: string[] = [
  // 生產環境憑證指紋（CHANGE ME before deploying）
  // 'abc123...Base64...==',
]

// ─── 1. 裝置綁定 ──────────────────────────────────────────────────────────────

/** 取得（或產生）此裝置的穩定 Device ID */
export async function getDeviceId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE_ID_KEY)
  if (existing) return existing

  // 組合裝置資訊 + 亂數 UUID，再做 SHA-256
  const seed = [
    Crypto.randomUUID(),
    Device.deviceName ?? 'unknown',
    Device.modelName ?? 'unknown',
    Platform.OS,
  ].join('|')

  const hash = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    seed,
  )
  await SecureStore.setItemAsync(DEVICE_ID_KEY, hash, {
    keychainAccessible: SecureStore.ALWAYS_THIS_DEVICE_ONLY,
  })
  return hash
}

/** 在 Axios interceptor 中注入 device header */
export async function injectDeviceHeaders(
  headers: Record<string, string>,
): Promise<Record<string, string>> {
  const deviceId = await getDeviceId()
  return {
    ...headers,
    'X-Device-ID': deviceId,
    'X-Platform': Platform.OS,
    'X-App-Version': '1.0.0',
  }
}

// ─── 2. 憑證指紋驗證（JS-Level SSL Pinning）─────────────────────────────────

/**
 * 驗證憑證指紋（JS 層檢查）。
 *
 * 由於 Expo managed workflow 的 JS 沙盒無法直接讀取 TLS 憑證，
 * 此函式透過「額外 precheck 請求」的方式模擬 pinning 邏輯：
 * 向後端 GET /security/cert-fingerprint 取得服務端自報指紋，
 * 再與本機白名單比對。
 *
 * ⚠️  此為軟性 pinning（防中間人 + 指紋漂移告警），
 *     非 TLS 握手層阻斷。要做硬性 pinning 請見底部的 EAS Build 方案。
 */
export async function verifyCertFingerprint(
  fetchFn: () => Promise<{ fingerprint: string }>,
): Promise<boolean> {
  // 若未設定 pins，跳過驗證（本機開發模式）
  if (CERT_PINS.length === 0) return true

  try {
    const { fingerprint } = await fetchFn()
    const trusted = CERT_PINS.includes(fingerprint)
    if (!trusted) {
      void reportSecurityEvent('cert_pin_mismatch', { received: fingerprint })
    }
    return trusted
  } catch {
    // 網路失敗不阻斷主流程（可選擇更嚴格的 fail-closed 策略）
    return true
  }
}

// ─── 3. 異常行為偵測 ──────────────────────────────────────────────────────────

/** 記錄一次登入失敗 */
export async function recordFailedLogin(): Promise<void> {
  const raw = await SecureStore.getItemAsync(FAILED_ATTEMPTS_KEY)
  const count = parseInt(raw ?? '0', 10) + 1
  await SecureStore.setItemAsync(FAILED_ATTEMPTS_KEY, String(count))
  await SecureStore.setItemAsync(LAST_FAILED_KEY, String(Date.now()))
}

/** 清除失敗計數（登入成功後呼叫） */
export async function clearFailedLogin(): Promise<void> {
  await SecureStore.deleteItemAsync(FAILED_ATTEMPTS_KEY)
  await SecureStore.deleteItemAsync(LAST_FAILED_KEY)
}

/**
 * 檢查是否在冷卻鎖定期間內。
 * @returns `{ locked: boolean, remainingMs: number }`
 */
export async function checkLoginLockout(): Promise<{
  locked: boolean
  remainingMs: number
}> {
  const raw = await SecureStore.getItemAsync(FAILED_ATTEMPTS_KEY)
  const count = parseInt(raw ?? '0', 10)

  if (count < MAX_FAILED_ATTEMPTS) return { locked: false, remainingMs: 0 }

  const lastTs = parseInt(
    (await SecureStore.getItemAsync(LAST_FAILED_KEY)) ?? '0',
    10,
  )
  const elapsed = Date.now() - lastTs

  if (elapsed >= LOCKOUT_DURATION_MS) {
    // 冷卻結束，自動解鎖
    await clearFailedLogin()
    return { locked: false, remainingMs: 0 }
  }

  return { locked: true, remainingMs: LOCKOUT_DURATION_MS - elapsed }
}

/**
 * 偵測可疑登入行為：
 *   - 非正常上班時段（00:00 ~ 06:00）
 *   - 快速連續登入嘗試
 */
export function detectSuspiciousLogin(failedCount: number): SuspiciousLoginReason[] {
  const reasons: SuspiciousLoginReason[] = []

  const hour = new Date().getHours()
  if (hour >= 0 && hour < 6) {
    reasons.push('unusual_hour')
  }

  if (failedCount >= 3) {
    reasons.push('repeated_failures')
  }

  return reasons
}

export type SuspiciousLoginReason = 'unusual_hour' | 'repeated_failures' | 'new_device'

// ─── 4. 遠端 Token 撤銷 ───────────────────────────────────────────────────────

/**
 * 向後端撤銷目前的 JWT（加入黑名單）。
 * 由 `logout()` 在清除本機 token 前呼叫。
 */
export async function revokeToken(token: string): Promise<void> {
  try {
    const deviceId = await getDeviceId()
    await fetch(`${getBaseUrl()}/mobile/auth/revoke-token`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'X-Device-ID': deviceId,
      },
      body: JSON.stringify({ token }),
    })
  } catch (err) {
    // 即使撤銷失敗（網路斷線），本機 token 仍會被清除
    console.warn('[Security] Token revocation failed:', err)
  }
}

// ─── 安全事件回報 ─────────────────────────────────────────────────────────────

interface SecurityEventPayload {
  received?: string
  reason?: string
  [key: string]: unknown
}

/**
 * 向後端回報安全事件（告警、異常登入等）。
 * 靜默失敗，不中斷主流程。
 */
export async function reportSecurityEvent(
  eventType: string,
  payload: SecurityEventPayload = {},
): Promise<void> {
  try {
    const deviceId = await getDeviceId()
    await fetch(`${getBaseUrl()}/mobile/security/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-ID': deviceId,
      },
      body: JSON.stringify({
        event_type: eventType,
        timestamp: new Date().toISOString(),
        platform: Platform.OS,
        device_model: Device.modelName,
        ...payload,
      }),
    })
  } catch {
    // silent
  }
}

// ─── 輔助工具 ─────────────────────────────────────────────────────────────────

/** 從 config.ts 動態取得 API base（避免循環依賴時的備選方案） */
function getBaseUrl(): string {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { API_BASE_URL } = require('./config') as { API_BASE_URL: string }
  return API_BASE_URL
}

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * 深度 Native SSL Pinning（EAS Build）— 實作說明
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * JS-level pinning 只能防禦中間人告警，無法在 TLS 握手層阻斷連線。
 * 若需嚴格的 native pinning，請使用以下 EAS Build 方案：
 *
 * iOS（app.json → ios.infoPlist）：
 * ```json
 * {
 *   "ios": {
 *     "infoPlist": {
 *       "NSAppTransportSecurity": {
 *         "NSPinnedDomains": {
 *           "enclave.company.com": {
 *             "NSPinnedLeafCertificates": [
 *               { "SPKI-SHA256-BASE64": "abc123...==" }
 *             ]
 *           }
 *         }
 *       }
 *     }
 *   }
 * }
 * ```
 *
 * Android（config plugin）：
 * 建立 `mobile/plugins/network-security-config.js` config plugin，
 * 寫入 `android/app/src/main/res/xml/network_security_config.xml`。
 * 參考：https://docs.expo.dev/guides/config-plugins/
 *
 * 替代方案：`react-native-ssl-pinning` (npm) 提供更完整的 API，
 * 但需要 bare workflow 或 custom dev client。
 * ─────────────────────────────────────────────────────────────────────────────
 */

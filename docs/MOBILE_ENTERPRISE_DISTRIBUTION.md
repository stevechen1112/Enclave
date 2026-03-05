# Enclave Mobile — 企業內部分發指南 (P12-10)

> **適用對象**：IT 管理員、DevOps、行動裝置管理（MDM）負責人  
> **App 版本**：Enclave Mobile v1.x（Expo 51 / React Native 0.74）  
> **更新日期**：2025-06

---

## 目錄

1. [概覽](#1-概覽)
2. [iOS — Apple Business Manager (ABM)](#2-ios--apple-business-manager-abm)
   - 2.1 前置條件
   - 2.2 以 Custom App 分發
   - 2.3 MDM 推送（Jamf / Intune）
3. [Android — Android Enterprise (AE)](#3-android--android-enterprise-ae)
   - 3.1 Work Profile 模式
   - 3.2 Managed Google Play 私人 App
   - 3.3 MDM 推送（Microsoft Intune / VMware Workspace ONE）
4. [EAS Build 自動化](#4-eas-build-自動化)
5. [OTA 更新策略](#5-ota-更新策略)
6. [憑證與簽名管理](#6-憑證與簽名管理)
7. [安全與合規](#7-安全與合規)
8. [常見問題 FAQ](#8-常見問題-faq)

---

## 1. 概覽

Enclave Mobile 屬於企業內部工具，**不上架公開 App Store**。  
推薦的分發方式依平台：

| 平台 | 方式 | 說明 |
|------|------|------|
| iOS | Apple Business Manager (ABM) Custom App | App Store Connect 私簽，MDM 靜默安裝 |
| iOS (開發/測試) | AdHoc / TestFlight Internal | 最多 100 台裝置（AdHoc）或 100 人（Internal） |
| Android | Managed Google Play 私人 Track | Google Play 私有渠道，MDM 推送 |
| Android (開發/測試) | APK Sideload | 直接部署到已授權裝置，適合 PoC |

---

## 2. iOS — Apple Business Manager (ABM)

### 2.1 前置條件

| 項目 | 注意事項 |
|------|----------|
| Apple Developer Program | 企業帳號（org），費用 USD 99/年 |
| ABM 帳號 | 需要 DUNS Number 申請，約 5–7 個工作日 |
| MDM 解決方案 | Jamf Pro、Microsoft Intune、VMware Workspace ONE 或其他 MDM |
| App Store Connect 管理員 | 能建立 Custom App |

### 2.2 以 Custom App 分發

#### Step 1 — 打包 IPA

```bash
# 使用 EAS Build（推薦）
eas build --profile production --platform ios

# 或本機打包
cd mobile
expo run:ios --configuration Release
```

#### Step 2 — 上傳至 App Store Connect

1. 登入 [App Store Connect](https://appstoreconnect.apple.com)
2. 建立新 App，Bundle ID 設為 `com.enclave.mobile`
3. 在「Pricing & Availability」→「Custom Apps」啟用
4. 輸入貴公司的 **ABM Organization ID**（或合作夥伴邀請碼）
5. 提交審核（Custom App 審核時間通常 1–3 個工作日）

#### Step 3 — ABM 分配

1. 登入 [Apple Business Manager](https://business.apple.com)
2. 在「Apps and Books」找到 Custom App
3. 購買授權數量（可設為 0 元）
4. 將授權分配到指定的 MDM server token

#### Step 4 — MDM 靜默安裝

**Jamf Pro**：
```
Devices → Mobile Device Apps → + Add → App Store App (Custom)
搜尋 Bundle ID: com.enclave.mobile
Scope: 選取目標群組
Distribution Method: Install Automatically/Prompt Users to Install
```

**Microsoft Intune**：
```
Apps → iOS/iPadOS Apps → Add → iOS Store App
搜尋 App，搜到後指定受管理裝置群組
Assignment type: Required（強制安裝）或 Available（使用者自選）
```

### 2.3 MDM 推送（Jamf / Intune）

關鍵 MDM Policy 建議設定：

```xml
<!-- Managed App Configuration (app.json extra keys) -->
<dict>
  <key>SERVER_URL</key>
  <string>https://enclave.internal.company.com/api/v1</string>
  <key>ENVIRONMENT</key>
  <string>production</string>
  <key>FORCE_VPN</key>
  <string>true</string>
</dict>
```

在 `mobile/src/config.ts` 讀取 MDM 推送的 key：

```typescript
import { NativeModules } from 'react-native'

// iOS MDM Managed Configuration
const managedConfig: Record<string, string> =
  NativeModules.RNManagedAppConfig?.getConfig?.() ?? {}

export const API_BASE_URL =
  managedConfig.SERVER_URL ??
  process.env.EXPO_PUBLIC_API_HOST ??
  'http://10.0.2.2:8000/api/v1'
```

---

## 3. Android — Android Enterprise (AE)

### 3.1 Work Profile 模式

Android Enterprise Work Profile 將企業 App 與個人 App 隔離：

- Enclave Mobile 安裝在 **Work Profile**（公司容器）
- 公司可遠端抹除 Work Profile，不影響個人資料
- App 網路流量可另配 Per-App VPN

### 3.2 Managed Google Play 私人 App

#### Step 1 — 打包 AAB/APK

```bash
# EAS Build
eas build --profile production --platform android

# 或本機
cd mobile
expo run:android --variant release
```

#### Step 2 — 上傳至 Managed Google Play

1. 登入 [Google Play Console](https://play.google.com/console)
2. 選擇「私人 app / Internal testing」或透過 Managed Google Play 私有頻道
3. 建立新 App，Package Name：`com.enclave.mobile`
4. 上傳 AAB，填寫必要的 Play 政策聲明（企業內部分發可跳過部分公開上架要求）

**若使用 Managed Google Play（推薦企業）：**

1. IT 管理員在 MDM console 連結 Managed Google Play 帳號
2. 在 Managed Google Play 中核准私人 App
3. MDM 自動推送到受管裝置

#### Step 3 — MDM 推送（Intune）

```
Apps → Android Apps → Add → Managed Google Play App
搜尋私人 App：com.enclave.mobile
Assignment: Required（受管裝置群組）
App configuration policies: 推送 SERVER_URL 等 key
```

**VMware Workspace ONE (WS1)**：
```
Apps → Internal → Upload APK/AAB
Assignment: Smart Groups → All Corporate Devices
Profile: VPN Per-App Profile（可選）
```

### 3.3 ManagedAppConfig for Android

```json
{
  "kind": "androidenterprise#managedConfiguration",
  "productId": "app:com.enclave.mobile",
  "managedProperty": [
    {
      "key": "SERVER_URL",
      "valueString": "https://enclave.internal.company.com/api/v1"
    },
    {
      "key": "FORCE_VPN",
      "valueBool": true
    }
  ]
}
```

---

## 4. EAS Build 自動化

建立 `mobile/eas.json` 設定不同環境的建置：

```json
{
  "cli": {
    "version": ">= 7.0.0"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "channel": "development"
    },
    "staging": {
      "distribution": "internal",
      "channel": "staging",
      "env": {
        "EXPO_PUBLIC_API_HOST": "https://staging.enclave.company.com/api/v1"
      }
    },
    "production": {
      "distribution": "store",
      "channel": "production",
      "env": {
        "EXPO_PUBLIC_API_HOST": "https://enclave.company.com/api/v1"
      },
      "ios": {
        "resourceClass": "m-medium"
      },
      "android": {
        "buildType": "app-bundle"
      }
    }
  },
  "submit": {
    "production": {
      "ios": {
        "appleId": "it@company.com",
        "ascAppId": "XXXXXXXXXX",
        "appleTeamId": "XXXXXXXXXX"
      },
      "android": {
        "serviceAccountKeyPath": "./secrets/google-play-service-account.json",
        "track": "internal"
      }
    }
  }
}
```

### CI/CD 流程（GitHub Actions）

```yaml
# .github/workflows/mobile-build.yml
name: Mobile Production Build
on:
  push:
    tags: ['mobile-v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: npm install -g eas-cli
      - run: cd mobile && npm ci
      - name: Build iOS
        run: cd mobile && eas build --platform ios --profile production --non-interactive
        env:
          EXPO_TOKEN: ${{ secrets.EXPO_TOKEN }}
      - name: Build Android
        run: cd mobile && eas build --platform android --profile production --non-interactive
        env:
          EXPO_TOKEN: ${{ secrets.EXPO_TOKEN }}
      - name: Submit to stores
        run: cd mobile && eas submit --platform all --profile production --non-interactive
        env:
          EXPO_TOKEN: ${{ secrets.EXPO_TOKEN }}
```

---

## 5. OTA 更新策略

使用 **EAS Update**（前稱 Expo Updates）進行 JS bundle 熱更新，無需重新提交 App Store：

```bash
# 推送更新到 staging channel
eas update --channel staging --message "P12-9 push notifications"

# 推送到 production
eas update --channel production --message "v1.2.0 release"
```

**注意事項：**
- Native 程式碼變更（新增 native module、更改 permissions）必須重新提交完整版本
- JS/資源變更可用 OTA 推送
- 推薦在 `app.json` 設定 `updates.checkAutomatically: "ON_LOAD"` 確保使用者拿到最新版

---

## 6. 憑證與簽名管理

### iOS

| 憑證類型 | 用途 | 建議管理方式 |
|------------|------|--------------|
| Distribution Certificate | App Store 提交 | EAS 管理（`eas credentials`）|
| Push Notification Certificate | APNs | EAS 管理或 Firebase Cloud Messaging |
| Provisioning Profile | 裝置授權 | EAS 管理 |

```bash
# 查看/重新產生憑證
eas credentials --platform ios
```

### Android

| 檔案 | 用途 | 保存位置 |
|------|------|----------|
| `upload-keystore.jks` | App 簽名 | **務必備份到密碼管理器**（1Password/Vault）|
| `google-play-service-account.json` | Automated Submit | GitHub Secrets / Vault |

```bash
# EAS 管理 keystore（推薦）
eas credentials --platform android
```

> ⚠️ **keystore 遺失後無法更新 App**，必須用新 Package Name 重新上架。請備份 3 份（本地加密 + 雲端加密 + 離線）。

---

## 7. 安全與合規

### App 傳輸安全 (ATS / Network Security Config)

iOS `app.json`：
```json
{
  "ios": {
    "infoPlist": {
      "NSAppTransportSecurity": {
        "NSAllowsArbitraryLoads": false
      }
    }
  }
}
```

Android `android/app/src/main/res/xml/network_security_config.xml`（EAS Build with custom config）：
```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <domain-config cleartextTrafficPermitted="false">
    <domain includeSubdomains="true">enclave.company.com</domain>
    <pin-set expiration="2026-01-01">
      <!-- SHA-256 of your server certificate's public key -->
      <pin digest="SHA-256">base64encodedpinthash==</pin>
    </pin-set>
  </domain-config>
</network-security-config>
```

### MDM Compliance Policy 建議

```
✅ 裝置必須加密
✅ 螢幕鎖定設定（PIN/生物辨識）
✅ OS 版本 ≥ iOS 16 / Android 12
✅ Jailbreak/Root 偵測（P12-11 在 App 層另行實作）
✅ VPN Profile 強制推送
```

---

## 8. 常見問題 FAQ

**Q: TestFlight 能用於企業內部測試嗎？**  
A: 可以，TestFlight Internal Test 最多 100 名內部測試員（Apple Developer 帳號下），不需審核，適合開發/QA 環境。External Test 需要 Beta 審核。

**Q: 未加入 ABM 的裝置能安裝嗎？**  
A: 可用 AdHoc（最多 100 台）或 Enterprise Distribution Certificate（需 USD 299/年 Apple Developer Enterprise Program）。

**Q: Android sideload APK 需要什麼設定？**  
A: 裝置需啟用「允許未知來源」，並由 IT 提供簽名後的 APK 安裝檔。EAS Build 可直接下載 APK。

**Q: OTA 更新失敗回滾怎麼辦？**  
A: EAS Update 支援 channel rollback：`eas update --channel production --rollback-to-timestamp <ISO>`

**Q: 推播通知的 APNs/FCM 設定在哪裡？**  
A: 見 [MOBILE_VPN_GUIDE.md](./MOBILE_VPN_GUIDE.md) 及後端 `/app/services/notification_service.py`。EAS 的 APNs key 透過 `eas credentials` 管理。

---

*文件維護：Enclave DevOps Team*  
*相關文件：[MOBILE_VPN_GUIDE.md](./MOBILE_VPN_GUIDE.md) | [DEPLOY_QUICKCARD.md](./DEPLOY_QUICKCARD.md) | [OPS_SOP.md](./OPS_SOP.md)*

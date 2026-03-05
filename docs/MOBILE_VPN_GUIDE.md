# Phase 12 P12-3 — 行動端 VPN / Zero Trust 連線設定指南

> **適用對象：** IT 管理員（地端伺服器側）、終端使用者（手機側）
> **適用版本：** Enclave Mobile App v1.0+
> **安全等級：** 本指南假設資料高度敏感，所有連線均需加密並通過身份驗證

---

## 一、連線架構選擇

```
┌────────────────────────┐      ┌──────────────────────────┐
│   律師手機 (iOS/Android) │      │  事務所地端伺服器           │
│                        │      │  Enclave Backend + Nginx  │
│   Enclave Mobile App   │      │  192.168.1.x（內網 IP）   │
└───────────┬────────────┘      └──────────────┬───────────┘
            │                                   │
    ┌───────▼───────┐                 ┌─────────▼────────┐
    │  方案 A：       │                 │  方案 A：          │
    │  Tailscale     │◄───────────────►│  Tailscale         │
    │  （建議首選）    │                 │  tailscaled 服務   │
    └───────────────┘                 └──────────────────┘

    ┌───────────────┐                 ┌──────────────────┐
    │  方案 B：       │                 │  方案 B：          │
    │  WireGuard     │◄───────────────►│  WireGuard Server  │
    │  （進階控制）    │                 │  wg0 interface     │
    └───────────────┘                 └──────────────────┘

    ┌───────────────┐                 ┌──────────────────┐
    │  方案 C：       │                 │  方案 C：          │
    │  直接 HTTPS    │◄───────────────►│  開放 443/8000    │
    │  （需額外風評）  │                 │  需配置 SSL 憑證   │
    └───────────────┘                 └──────────────────┘
```

| | 方案 A：Tailscale | 方案 B：WireGuard | 方案 C：直接 HTTPS |
|---|---|---|---|
| 設定難度 | ⭐ 最簡單 | ⭐⭐⭐ 需要較多配置 | ⭐⭐ 中等 |
| 安全性 | ✅ 端對端加密 | ✅ 端對端加密 | ⚠️ 需嚴格憑證管理 |
| 需開放防火牆 | ❌ 不需要 | ⚠️ UDP 51820 | ✅ TCP 443 |
| 中繼伺服器依賴 | ⚠️ Tailscale DERP | ❌ 自主控制 | ❌ 不需要 |
| 建議場景 | 中小型事務所 | 對資料主權要求極高 | 已有固定 IP + SSL 憑證 |

**建議優先使用方案 A（Tailscale）**，設定最簡單且安全性足夠。

---

## 二、方案 A — Tailscale 設定（建議）

### 2.1 伺服器端設定

#### 1. 安裝 Tailscale

```bash
# Linux（Ubuntu / Debian）
curl -fsSL https://tailscale.com/install.sh | sh

# 啟動服務
sudo systemctl enable --now tailscaled
```

#### 2. 登入並加入網路

```bash
sudo tailscale up
# 按照終端機指示，在瀏覽器完成授權（需 Tailscale 帳號）
# 建議使用企業用 Google Workspace 帳號登入
```

#### 3. 記錄伺服器的 Tailscale IP

```bash
tailscale ip -4
# 範例輸出：100.64.x.x
```

#### 4. 設定 MagicDNS（可選但建議）

在 Tailscale Admin Console（https://login.tailscale.com/admin）：
- 啟用 **MagicDNS**
- 記錄自動分配的機器名稱，例如 `enclave-server.tail1234.ts.net`

#### 5. 更新 Enclave 設定允許 Tailscale 連線

```nginx
# nginx/gateway.conf — 在 server_name 加入 Tailscale 域名
server_name enclave-server.tail1234.ts.net 192.168.1.100;
```

### 2.2 手機端設定

#### iOS
1. App Store 搜尋並安裝「**Tailscale**」
2. 開啟 App → Sign in → 使用與伺服器相同的帳號登入
3. 點選 Connect，等待連線建立

#### Android
1. Google Play 安裝「**Tailscale**」
2. 同上步驟登入並連線

### 2.3 更新 Enclave Mobile 設定

連線成功後，更新 App 的 API 位址：

```typescript
// mobile/src/config.ts
export const API_BASE_URL = 'http://100.64.x.x:8000/api/v1'
// 或使用 MagicDNS：
export const API_BASE_URL = 'http://enclave-server.tail1234.ts.net:8000/api/v1'
```

### 2.4 驗證連線

```bash
# 在手機的 Tailscale App 確認伺服器顯示為「Connected」
# 在瀏覽器輸入 http://100.64.x.x:8000/api/v1/health 應回應 200
```

---

## 三、方案 B — WireGuard 設定（進階）

> 適用于對資料完全不流經第三方有嚴格要求的場景（如政府機關、醫療院所）

### 3.1 伺服器端設定

#### 1. 安裝 WireGuard

```bash
# Ubuntu 20.04+
sudo apt update && sudo apt install -y wireguard

# 安裝 qrencode（用於生成手機 QR Code）
sudo apt install -y qrencode
```

#### 2. 生成伺服器金鑰對

```bash
cd /etc/wireguard
umask 077
wg genkey | tee server_private.key | wg pubkey > server_public.key
cat server_private.key  # 記錄下來
cat server_public.key   # 記錄下來
```

#### 3. 建立伺服器設定檔

```bash
sudo nano /etc/wireguard/wg0.conf
```

```ini
[Interface]
Address = 10.100.0.1/24
ListenPort = 51820
PrivateKey = <server_private_key>

# 開啟 IP 轉送（讓手機可存取內網）
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# 手機 1（律師甲）
[Peer]
PublicKey = <phone1_public_key>
AllowedIPs = 10.100.0.2/32

# 手機 2（律師乙）
[Peer]
PublicKey = <phone2_public_key>
AllowedIPs = 10.100.0.3/32
```

#### 4. 啟動 WireGuard

```bash
sudo systemctl enable --now wg-quick@wg0
# 確認狀態
sudo wg show
```

#### 5. 開放防火牆

```bash
# UFW
sudo ufw allow 51820/udp
sudo ufw reload

# 或 iptables
iptables -A INPUT -p udp --dport 51820 -j ACCEPT
```

#### 6. IP 轉送開關

```bash
# 編輯 /etc/sysctl.conf，加入：
net.ipv4.ip_forward = 1

# 套用
sudo sysctl -p
```

### 3.2 手機端設定

#### 生成手機設定（伺服器執行）

```bash
# 為每台手機生成金鑰對
wg genkey | tee phone1_private.key | wg pubkey > phone1_public.key

# 建立手機設定檔
cat > phone1.conf << EOF
[Interface]
PrivateKey = $(cat phone1_private.key)
Address = 10.100.0.2/32
DNS = 8.8.8.8

[Peer]
PublicKey = $(cat server_public.key)
Endpoint = <server_public_ip>:51820
AllowedIPs = 192.168.1.0/24, 10.100.0.0/24
PersistentKeepalive = 25
EOF

# 生成 QR Code 供手機掃描
qrencode -t ansiutf8 < phone1.conf
```

#### iOS / Android 安裝

1. 安裝「**WireGuard**」官方 App
2. 點選「+」→「從 QR Code 建立」
3. 掃描上述 QR Code
4. 啟用連線

### 3.3 更新 Enclave Mobile 設定

```typescript
// mobile/src/config.ts
export const API_BASE_URL = 'http://192.168.1.100:8000/api/v1'
// WireGuard 連線後可直接存取內網 IP
```

---

## 四、方案 C — 直接 HTTPS（需固定公網 IP）

> **風險提示：** 直接對外開放 API 端點有較高風險，需配合 P12-11 SSL Pinning 一併實施

### 4.1 前置條件

- 固定公網 IP 或動態 DNS（如 DynDNS、Cloudflare）
- 有效的 SSL/TLS 憑證（建議 Let's Encrypt 或企業 CA）
- 路由器 / 防火牆開放 TCP 443

### 4.2 Nginx SSL 設定

```nginx
# nginx/gateway.conf
server {
    listen 443 ssl;
    server_name enclave.yourfirm.com;

    ssl_certificate     /etc/ssl/certs/enclave.crt;
    ssl_certificate_key /etc/ssl/private/enclave.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    # 僅允許來自特定 IP 的請求（如律師常用的固定 IP）
    # allow 203.x.x.x;
    # deny all;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 4.3 更新 Enclave Mobile 設定

```typescript
// mobile/src/config.ts
export const API_BASE_URL = 'https://enclave.yourfirm.com/api/v1'
```

---

## 五、連線安全檢查清單

### 伺服器端

- [ ] 防火牆僅開放必要連接埠（VPN 用 UDP 51820，或 HTTPS 用 TCP 443）
- [ ] SSH 僅允許金鑰認證，禁止密碼登入
- [ ] 定期備份 WireGuard / Tailscale 金鑰
- [ ] 監控異常連線嘗試（fail2ban 或 auditd）

### App 端（配合 P12-11 實施）

- [ ] `config.ts` 的 `API_BASE_URL` 使用正確的 VPN IP 或 HTTPS 域名
- [ ] SSL Pinning 憑證與伺服器憑證一致（方案 C）
- [ ] 離開辦公室前確認 VPN 已連線

### 使用者操作

- [ ] 律師離開事務所前開啟 VPN App
- [ ] 確認 VPN 顯示「已連線」後再開啟 Enclave App
- [ ] 不在公共 WiFi 下使用未加密連線

---

## 六、常見問題排查

### Q：VPN 連上了但 App 顯示「無法連線到伺服器」

1. 確認 `config.ts` 的 IP 是 VPN 隧道內的 IP，不是公網 IP
2. 在手機瀏覽器輸入 `http://<vpn-ip>:8000/api/v1/health` 測試
3. 確認後端服務在執行：`docker compose ps`

### Q：Tailscale 連線後速度很慢

- 在 Tailscale Admin Console 確認是否使用 DERP 中繼（顯示 relay）
- 啟用 `--advertise-routes` 讓手機走直連而非中繼
- 考慮部署自建 DERP server（企業方案）

### Q：WireGuard 手機無法 ping 到伺服器

```bash
# 伺服器端確認 IP 轉送已啟用
cat /proc/sys/net/ipv4/ip_forward  # 應顯示 1

# 確認 wg0 介面正常
sudo wg show

# 確認有收到來自手機的握手
sudo wg show wg0 latest-handshakes
```

### Q：憑證錯誤 / SSL handshake failed（方案 C）

- 確認憑證未過期：`openssl x509 -in /etc/ssl/certs/enclave.crt -noout -dates`
- 確認 `config.ts` 的 URL scheme 為 `https://` 而非 `http://`
- P12-11 SSL Pinning 啟用後，憑證更新需同步更新 App 內的 pin hash

---

## 七、企業部署建議架構

```
外部網路
    │
    ├── 律師甲手機 ──── Tailscale / WireGuard ────┐
    ├── 律師乙手機 ──── Tailscale / WireGuard ────┤
    └── 律師丙手機 ──── Tailscale / WireGuard ────┤
                                                   │
                                            ┌──────▼──────────────────────┐
                                            │  事務所內網 (192.168.1.0/24) │
                                            │                              │
                                            │  ┌──────────┐  ┌─────────┐  │
                                            │  │  Nginx   │  │  DB     │  │
                                            │  │ :443/:80 │  │ Postgres│  │
                                            │  └────┬─────┘  └─────────┘  │
                                            │       │                      │
                                            │  ┌────▼─────┐  ┌─────────┐  │
                                            │  │ FastAPI  │  │  Redis  │  │
                                            │  │ :8000    │  │ :6379   │  │
                                            │  └──────────┘  └─────────┘  │
                                            └──────────────────────────────┘
```

---

*此文件為 Phase 12 P12-3 交付物，應與 [INSTALL.md](INSTALL.md) 一併交付給 IT 管理員。*
*最後更新：2026-02-24*

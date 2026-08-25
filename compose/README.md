# Enclave Compose Overlays（DD-M10 / DD-M11）

本目錄為**可組合 overlay**；倉庫根目錄的 `docker-compose*.yml` 為入口薄層。

## 檔案

| 檔案 | 用途 |
|------|------|
| `sidecars.yml` | RAGFlow／PipesHub／WeKnora 等 sidecar 服務定義 |
| `enterprise.yml` | 企業向附加服務（觀測等） |
| `image-pins.env` | Sidecar／enterprise image **immutable tag／digest**（禁 `latest`） |
| `pack-enabled.env` | Standard／enterprise 時將 pack flag 與 sidecar 同開 |

## 用法

### Dev（最小，無 sidecar）

```bash
docker compose -f docker-compose.yml up -d
# 本機映射常見：Postgres 5435、Redis 6380
```

### Lite（profiles）

```bash
docker compose -f docker-compose.profiles.yml --profile lite up -d
```

### Standard（sidecar + pack 同步）

```bash
docker compose --env-file compose/image-pins.env --env-file compose/pack-enabled.env \
  -f docker-compose.profiles.yml --profile standard up -d
```

### Enterprise

```bash
docker compose --env-file compose/image-pins.env --env-file compose/pack-enabled.env \
  -f docker-compose.profiles.yml --profile enterprise up -d
```

### Prod + sidecars

開 pack 時**必須**同時掛 overlay，否則容器 DNS 找不到 `ragflow`／…：

```bash
docker compose --env-file .env.production --env-file compose/pack-enabled.env \
  -f docker-compose.prod.yml -f compose/sidecars.yml --profile standard up -d
```

## Image pins

見 `compose/image-pins.env`。覆寫範例：

```bash
export PIPESHUB_IMAGE=pipeshubai/pipeshub-ai:0.4.5@sha256:...
```

產品能力包與本機埠說明見根目錄 `README.md`。

公開六角色展示只能使用合成租戶；建立、驗證與重置程序見
`docs/runbooks/SYNTHETIC_DEMO_TENANT.md`。一般客戶環境不得啟用 Demo login。

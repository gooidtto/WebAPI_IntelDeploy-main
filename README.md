# Railway Universal Stable Deployment

这是一个面向 Railway 的 Xray 稳定部署项目。核心原则：**节点身份只初始化一次，之后永久复用；运行时网络 endpoint 随当前 Deployment 重新发现。**

## 1. 部署要求

1. 将 GitHub 仓库连接到 Railway Service。
2. Service 使用仓库中的 `Dockerfile`。
3. 在 **Service → Volumes** 创建 Persistent Volume，并将 Mount Path 固定为 `/data`。
4. 在 **Service → Variables** 设置 `RAILWAY_TOKEN`。
5. Deploy。
6. 首次启动验证 `/data` 为真实 Persistent Volume；仅当 Volume 全新且为空时初始化 UUID、REALITY key、3 个 Short IDs 和 subscription token，并原子写入 `/data`。
7. 程序自动检查/创建当前 Deployment 所需的 Public Domain 与 TCP Proxy（Target `8080`）；仅执行非破坏性检查、复用或创建，不删除现有网络资源。
8. 后续 Restart / Redeploy / Container recreation 从 `/data` 读取并复用同一套节点身份；runtime manifest、订阅内容和 Railway endpoint 根据当前 Deployment 环境重新生成。

**Persistent Volume 必须在首次正式 Deploy 前完成挂载。** 缺少 Volume、身份不完整或身份完整性校验失败时，程序拒绝生成临时/替代身份。

## 2. 当前节点架构

正常运行时为 5 个节点：

| 节点 | 协议 | 传输 | 安全 | Endpoint 来源 |
|---|---|---|---|---|
| Node 01 | VLESS | XHTTP | TLS | Railway Public Domain :443 |
| Node 02 | VLESS | WebSocket | TLS | Railway Public Domain :443 |
| Node 03 | VLESS | RAW TCP | REALITY + Vision | Railway TCP Proxy |
| Node 04 | VLESS | XHTTP | REALITY | Railway TCP Proxy |
| Node 05 | VLESS | gRPC | REALITY | Railway TCP Proxy |

Cloudflare Tunnel + VLESS XHTTP TLS 保留为**可选 Node 06**；未启用时不计入运行节点数量。

当前 Gateway 监听 `:8080`，TCP Proxy Target 固定为 `8080`，并按 REALITY 节点将流量路由到 Xray 内部端口 `10087`、`10088`、`10089`。

## 3. 永久身份策略

节点身份唯一持久来源为 `/data`：

- `uuid.txt`
- `reality_private_key.txt`
- `reality_public_key.txt`
- `reality_short_ids.json`
- `subscription_token.txt`
- `identity-integrity.json`
- `.node-identity-initialized`

策略固定为 **`INITIALIZE_ONCE_REUSE_FOREVER`**：

- **全新空 Persistent Volume**：初始化一次。
- **已初始化且完整有效、完整性校验通过**：输出 `NODE_IDENTITY=REUSED`。
- **已初始化但身份文件缺失、损坏、不完整或完整性校验失败**：拒绝启动，**绝不生成新身份**。
- **未挂载 Persistent Volume**：拒绝启动，**绝不生成临时身份**。
- `generate.py` 只读取持久身份中的 Short IDs 和 subscription token，不负责生成身份。

`identity-integrity.json` 保存身份文件的 SHA-256 完整性封印，用于阻止被人为修改的 UUID、REALITY key、Short ID 或 subscription token 被静默当成原身份继续运行。

## 4. Subscription Token 与 URL

Subscription Token 持久保存在 `/data/subscription_token.txt`，不会因为 Redeploy、Restart 或 Railway endpoint 变化而自动更换。

订阅 URL 使用当前 Railway Public Domain 与持久 Token 组合生成：

```text
https://<current-public-domain>/sub/<subscription-token>
```

`/data/subscription_url.txt` 是当前运行时生成的派生文件，不是身份来源。Railway Public Domain 变化后，程序重新生成 URL；Token 保持不变。

如需**主动轮换 Token**，使用环境变量：

```text
SUBSCRIPTION_TOKEN_ROTATE_ID=YYYYMMDD-NNN
```

例如：`20260904-001`。相同 Rotation ID 不会重复轮换；非法 Rotation ID 直接 fail closed，且不修改身份。轮换只替换 subscription token，并重新封印身份完整性；UUID、REALITY key、Short IDs 保持不变。

## 5. Railway 网络与认证

`RAILWAY_TOKEN` 仅用于 Railway API 网络资源 bootstrap。当前认证逻辑兼容两种常见用法：优先尝试 `Authorization: Bearer`，失败后再尝试 `Project-Access-Token`；如存在独立 `RAILWAY_API_TOKEN`，可作为 Bearer fallback。

网络资源遵循非破坏性原则：

- 不删除现有 Public Domain。
- 不删除现有 TCP Proxy。
- 不清空或替换用户已有网络资源。
- 只检查、复用或在缺失时创建所需资源。
- TCP Proxy Target 必须为 `8080`。
- Railway API 暂时不可用时，在已有完整运行时 endpoint 条件满足的情况下可继续使用当前 endpoint；不会因此重新生成节点身份。

## 6. 启动与故障恢复

主进程由 `boot.sh` 直接运行。启动顺序：

```text
identity preflight
→ Gateway :8080
→ Railway networking reconciliation
→ runtime discovery
→ runtime / subscription generation
→ Xray
→ optional Cloudflare Tunnel
→ readiness
```

Gateway 或 Xray 主进程异常退出时，容器以失败状态结束，由 Railway `ON_FAILURE` 负责容器级恢复。重新启动后仍从 `/data` 复用同一身份。

Railway healthcheck 使用 `/health` 作为早期 liveness 检查；`boot.sh` 在完成 runtime、subscription 和 Xray readiness 检查后保持主进程运行。

## 7. 仓库结构

```text
.
├── Dockerfile
├── railway.toml
├── README.md
├── .dockerignore
├── .editorconfig
├── .gitignore
├── config/
│   └── reality-sni-candidates.txt
├── docs/
│   └── identity-policy.md
├── scripts/
│   ├── boot.sh
│   ├── gateway.py
│   ├── generate.py
│   ├── identity-init.py
│   ├── railway_setup.py
│   ├── runtime-manifest.py
│   ├── subscription-contract.py
│   └── version.py
└── site/
    └── index.html
```

生成的 Python `__pycache__`、`.pyc` 等构建/本地缓存不得进入 Git 仓库。当前架构不使用第二层 shell supervisor；Railway 原生 `ON_FAILURE` 负责容器级恢复。

## 8. 构建保护

Docker build 阶段强制检查：

- Xray 版本 `26.3.27` 与镜像 digest 固定；
- Python 脚本可编译；
- Persistent Volume guard、身份复用、fail-closed、integrity seal 存在；
- `boot.sh` 必须先执行身份初始化；
- Short IDs 必须从持久身份读取；
- Subscription Token 必须受完整性封印保护；
- subscription URL 必须生成并经过 runtime guard；
- Railway Public Domain / TCP Proxy 执行数量与 Target `8080` invariant 检查；
- Railway networking 必须保持非破坏性；
- WS transport 作为 Node 02 正式启用；
- Cloudflare Node 06 仅在明确启用时运行；
- `generate.py` 与 `boot.sh` 禁止在运行时重新生成永久节点身份。

## 9. 验收标准

首次部署：

```text
PERSISTENT_VOLUME=/data
PERSISTENT_VOLUME_MOUNT=PASS
NODE_IDENTITY=INITIALIZED
NODE_IDENTITY_FINGERPRINT=<fingerprint>
```

后续 Restart / Redeploy：

```text
PERSISTENT_VOLUME=/data
PERSISTENT_VOLUME_MOUNT=PASS
NODE_IDENTITY=REUSED
NODE_IDENTITY_FINGERPRINT=<same fingerprint>
```

正常网络 bootstrap：

```text
RAILWAY_API_SETUP=CHECK
RAILWAY_API_AUTH=RAILWAY_TOKEN_BEARER
RAILWAY_API_PUBLIC_DOMAIN=EXISTS_OR_CONFIGURED
RAILWAY_API_TCP_PROXY=EXISTS target=8080
RAILWAY_API_SETUP=READY
NETWORKING_STATE=READY
```

订阅契约应最终通过：

```text
SUBSCRIPTION_TOKEN_SEALED=PASS
SUBSCRIPTION_HTTP_LOCAL=PASS
SUBSCRIPTION_ENDPOINT_CONTRACT=PASS
SUBSCRIPTION_CONTRACT=PASS
```

同一 Persistent Volume 的 identity fingerprint 必须保持不变；endpoint fingerprint 可以随 Railway Deployment 网络变化而变化。

## 10. 生产原则

- 不删除或清空 `/data`，除非明确执行一次全新节点初始化。
- 不把 UUID、REALITY key、Short IDs 或 subscription token 写入 Git 仓库。
- 不在运行时重新生成永久节点身份。
- 不把 Railway endpoint 固化进身份文件。
- 不删除或破坏用户已有 Railway Public Domain / TCP Proxy。
- 不修改 Railway 国家/地区、Cloudflare 配置或其他用户未授权设置。
- Xray 版本保持固定，除非明确执行一次经过验证的版本升级。

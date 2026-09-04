# Railway Universal Stable Deployment

这是一个面向 Railway 的 Xray 稳定部署项目。核心原则：**节点身份只初始化一次，之后永久复用；运行时网络 endpoint 随当前 Deployment 重新发现。**

<a href="https://railway.com/new/template?referralCode=generic&utm_medium=integration&utm_source=button&utm_campaign=WebAPI_IntelDeploy-main">
  <img src="https://railway.com/button.svg" alt="Deploy on Railway" />
</a>

> 说明：Railway 官方的 Deploy on Railway 按钮用于发布/分享 Railway Template。当前仓库未配置可直接引用的 Railway Template ID，因此按钮进入 Railway 新建流程；正式使用时也可以直接按下面的 GitHub 部署流程连接本仓库。citeturn843186search0

## 🚀 最简部署流程

### 1. GitHub → Railway

在 Railway 中选择 **New Project → Deploy from GitHub Repo**，连接 GitHub 后选择：

`gooidtto/WebAPI_IntelDeploy-main`

Railway 支持将 GitHub Repository 直接作为 Service Source；检测到仓库中的 `Dockerfile` 后会使用 Dockerfile 构建。citeturn843186search1turn843186search6

### 2. 创建 Persistent Volume

进入 Railway Service：

**Service → Volumes → Add Volume**

挂载路径固定：

```text
/data
```

**首次正式 Deploy 前必须完成 `/data` 挂载。** 不要删除该 Volume，否则无法继续复用原节点身份。

### 3. 设置 Railway Token

进入：

**Service → Variables**

设置：

```text
RAILWAY_TOKEN=<你的 Railway Token>
```

该变量用于 Railway API 网络资源 bootstrap。程序兼容常见 Railway Token 认证方式。

### 4. Deploy

点击 **Deploy**。

首次启动时，程序会在 `/data` 中初始化：

- UUID
- REALITY private/public key
- 3 个 REALITY Short IDs
- Subscription Token

之后的 **Restart / Redeploy / Container recreation** 会自动从 `/data` 复用同一身份，不重新生成。

Railway 官方的 GitHub 部署流程也是创建项目、选择 GitHub Repository，然后 Deploy；代码更新后，连接的 GitHub 分支可以自动触发新的构建和部署。citeturn843186search1turn843186search6

## ✅ 部署完成检查

正常情况下日志应出现：

```text
PERSISTENT_VOLUME_MOUNT=PASS
NODE_IDENTITY=INITIALIZED
```

首次初始化完成后，再次 Restart / Redeploy 应出现：

```text
PERSISTENT_VOLUME_MOUNT=PASS
NODE_IDENTITY=REUSED
NODE_IDENTITY_FINGERPRINT=<same fingerprint>
```

网络与订阅正常时应最终通过：

```text
RAILWAY_NETWORK_DISCOVERY=READY
GATEWAY_BIND_EARLY=PASS
HEALTH_ENDPOINT=PASS
SUBSCRIPTION_TOKEN_SEALED=PASS
SUBSCRIPTION_HTTP_LOCAL=PASS
SUBSCRIPTION_ENDPOINT_CONTRACT=PASS
SUBSCRIPTION_CONTRACT=PASS
```

## 🌐 节点与订阅

正常运行时为 5 个节点：

| 节点 | 协议 | 传输 | 安全 | Endpoint |
|---|---|---|---|---|
| Node 01 | VLESS | XHTTP | TLS | Railway Public Domain :443 |
| Node 02 | VLESS | WebSocket | TLS | Railway Public Domain :443 |
| Node 03 | VLESS | RAW TCP | REALITY + Vision | Railway TCP Proxy |
| Node 04 | VLESS | XHTTP | REALITY | Railway TCP Proxy |
| Node 05 | VLESS | gRPC | REALITY | Railway TCP Proxy |

Cloudflare Tunnel + VLESS XHTTP TLS 为**可选 Node 06**。

Gateway 监听：

```text
:8080
```

TCP Proxy Target 固定：

```text
8080
```

Subscription URL 使用当前 Railway Public Domain + 持久 Token：

```text
https://<current-public-domain>/sub/<subscription-token>
```

Railway endpoint 变化时，运行时节点配置和 Subscription 会重新生成；持久身份不变。

## 🔐 永久身份规则

身份唯一持久来源：`/data`

```text
/data/uuid.txt
/data/reality_private_key.txt
/data/reality_public_key.txt
/data/reality_short_ids.json
/data/subscription_token.txt
/data/identity-integrity.json
/data/.node-identity-initialized
```

策略固定：

```text
INITIALIZE_ONCE_REUSE_FOREVER
```

已初始化且完整性校验通过 → `NODE_IDENTITY=REUSED`。

已初始化但身份缺失、损坏、不完整或封印校验失败 → **fail closed**，绝不生成替代身份。

未挂载真实 Persistent Volume → **fail closed**，绝不生成临时身份。

## 🔄 Subscription Token 主动轮换

默认不轮换 Token。

如需手动轮换，在 Railway Variables 增加：

```text
SUBSCRIPTION_TOKEN_ROTATE_ID=YYYYMMDD-NNN
```

示例：

```text
SUBSCRIPTION_TOKEN_ROTATE_ID=20260904-001
```

规则：

- 未设置或为空：不轮换。
- 相同 Rotation ID：不会重复轮换。
- 新 Rotation ID：只轮换 Subscription Token。
- UUID、REALITY Key、Short IDs 不变。
- 非法 Rotation ID：fail closed，不修改身份。

## 🛡️ Railway 网络策略

程序对 Railway 网络资源执行非破坏性处理：

- 不删除已有 Public Domain。
- 不删除已有 TCP Proxy。
- 优先检查并复用现有资源。
- 缺失时才创建所需资源。
- TCP Proxy Target 必须为 `8080`。
- Railway API 暂时不可用时，只要当前 runtime endpoint 完整，仍可继续使用当前 endpoint。

## 📦 当前仓库结构

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

## 🔧 稳定性原则

- Xray 版本固定，不自动漂移。
- 永久身份只存储在 `/data`。
- Runtime endpoint 不写入永久身份。
- Railway 网络配置不做破坏性删除。
- Railway API 短暂失败执行重试。
- 身份异常时 fail closed。
- `generate.py` / `boot.sh` 不在运行时重新生成永久节点身份。
- Git 仓库不保存 UUID、REALITY Key、Short IDs 或 Subscription Token。

## 📋 常用操作

**首次部署**：挂载 `/data` → 设置 `RAILWAY_TOKEN` → Deploy。

**普通更新**：推送 GitHub 新代码 → Railway 自动构建/部署，或手动 Redeploy。citeturn843186search6turn843186search3

**普通重启**：Restart，节点身份自动复用。

**查看部署日志**：进入 Railway Deployment → View Logs。Railway 提供 Deployment 状态和日志查看入口。citeturn843186search4

**Token 轮换**：修改 `SUBSCRIPTION_TOKEN_ROTATE_ID` 为新的合法值，然后 Redeploy。

## ⚠️ 重要

不要删除 `/data` Persistent Volume。删除后，程序无法继续证明原身份的完整性，也不会偷偷生成新身份。

不要把真实 Token、UUID、REALITY private key 写进 README、GitHub Issues 或 Git 仓库。

不要为了普通 Redeploy 手动修改 UUID、REALITY Key、Short IDs 或 Subscription Token。

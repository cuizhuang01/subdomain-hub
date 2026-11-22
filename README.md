# 云子域 · 二级域名分发系统

一套可直接运行的全栈系统，用于把主域名下的二级域名**分发给用户**，支持“跳转分发”和“DNS 解析托管”两种模式，带用户端控制台、管理员后台、访问统计和开放 API。

- 后端：Python 3.9+ / FastAPI / SQLite（标准库 sqlite3，无需 ORM）
- 前端：单页控制台，原生 JS + CSS，无任何外部 CDN 依赖（可离线运行）
- 依赖：仅 `fastapi`、`uvicorn`、`pydantic`、`PyJWT`、`requests`

---

## 四种跑起来的方式

> GitHub 只是代码托管，不会自动运行程序；想在 GitHub 上直接运行，用下面的「Codespaces」。

### 方式零：在 GitHub 上直接运行（Codespaces，免本地环境）

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/cuizhuang01/subdomain-hub)

点开后 GitHub 会自动构建容器、装依赖并启动服务，然后把 **8000 端口**转发成一个公开网址（形如 `https://xxxx-8000.app.github.dev`，在端口面板里可看到并设为 Public）。
个人账号每月有免费额度，闲置一段时间会自动休眠，适合演示与验收，不适合长期托管。

### 方式一：本机直接跑（无需 Docker）

```bash
git clone https://github.com/cuizhuang01/subdomain-hub.git
cd subdomain-hub
./run.sh                 # 自动装依赖并启动，等价于 python3 -m uvicorn app.main:app --port 8000
```

启动后打开 <http://127.0.0.1:8000> 即可使用；接口文档 <http://127.0.0.1:8000/docs>。

### 方式二：Docker（环境无关，推荐上线用）

```bash
docker compose up -d --build     # 或者：docker run -p 8000:8000 -v $(pwd)/data:/app/data subdomain-hub
```

数据保存在 `./data`，容器重建不丢；日志 `docker compose logs -f`。

### 方式三：部署到公网（Render 免费，点一下就跑）

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/cuizhuang01/subdomain-hub)

点击上面的按钮 → 用 GitHub 账号登录 Render → 确认 `render.yaml` → 等待 2~3 分钟，会得到一个 `https://subdomain-hub-xxx.onrender.com` 地址，直接打开就能用。

> 免费实例空闲会休眠（再次访问需要等十几秒唤醒），且没有持久磁盘，重启会重置数据；只适合演示。正式用请选付费磁盘，或用任意一台云服务器 + 方式二。

---

| 角色 | 账号 | 密码 |
|---|---|---|
| 管理员 | `admin@sdh.local` | `admin123` |
| 普通用户（演示数据） | `demo@sdh.local` | `demo1234` |

> 首次启动自动建表并写入演示数据（2 个域名、169 条访问记录、2 条解析记录），删除 `data/app.db` 可重新初始化。
> 环境变量：`SDH_DB`（数据库路径）、`SDH_SECRET_KEY`（JWT 密钥）、`PORT`、`HOST`。

---

## 功能清单

### 用户端
- **注册 / 登录 / 改密**：PBKDF2-SHA256 加盐存储，JWT 认证（HttpOnly Cookie + Bearer 双支持）
- **域名申请**：前缀实时可用性检测、保留词与格式校验、重复校验、配额限制
- **跳转分发**：设置目标地址与 301/302，访问自动跳转并透传路径与 query
- **DNS 解析托管**：A / AAAA / CNAME / TXT / MX 记录增删改、TTL、MX 优先级、Cloudflare 代理开关、失败重试同步
- **域名管理**：状态筛选、关键字搜索、分页、用途切换、备注、删除
- **续费**：按年计费、余额扣款、生成订单号、到期前 15 天提醒、到期自动停用
- **访问统计**：今日/累计/区间访问量、趋势折线图、设备分布、来源渠道、Top 域名、逐条访问明细（IP/UA/Referer/路径）
- **API 密钥**：创建/删除、掩码展示、最近使用时间，配套 `/api/v1` 开放接口

### 管理后台
- **总览**：用户数、域名数、待审核、收入、全站 14 天访问趋势、DNS 服务商状态
- **域名审核**：单条通过/拒绝（附拒绝原因）、勾选批量审核
- **全部域名**：全站筛选搜索、强制停用/恢复/删除
- **用户管理**：改角色、封禁/解封、调整余额、重置密码
- **订单流水**：续费与充值记录
- **审计日志**：所有关键动作留痕（谁、何时、对什么、做了什么）
- **系统设置**：站点名、主域名、年费、默认年限、自动审核开关、单用户配额、保留词、平台公告、DNS 服务商凭据

### 工程能力
- 统一异常与参数校验响应；所有列表接口分页；SQL 全参数化，无注入风险
- 惰性过期处理：任何列表/统计请求都会把到期域名置为 `expired`
- `tests_smoke.py`：33 项端到端冒烟测试，覆盖注册、申请、跳转、解析、续费、API、权限

---

## 目录结构

```
subdomain-hub/
├── app/
│   ├── main.py            # FastAPI 入口、异常处理、静态资源
│   ├── db.py              # 建表、连接、种子数据
│   ├── security.py        # 密码哈希、JWT、Key/订单号生成
│   ├── settings_store.py  # 系统设置读写与默认值
│   ├── services.py        # 申请/审批/续费/过期/统计/审计等业务
│   ├── dns_providers.py   # 手动 / Cloudflare / 阿里云 DNS 适配
│   ├── deps.py            # 登录态、管理员、API Key 依赖
│   ├── routers/
│   │   ├── auth.py        # 注册登录、当前用户、充值
│   │   ├── domains.py     # 用户域名 CRUD、续费、统计
│   │   ├── dns.py         # 解析记录 CRUD 与同步
│   │   ├── stats.py       # 用户维度统计汇总
│   │   ├── admin.py       # 后台全部接口
│   │   ├── apiv1.py       # API Key 管理 + 开放 API
│   │   └── gateway.py     # 按 Host 识别二级域名并跳转/展示
│   └── static/            # 控制台前端（index.html / app.js / style.css）
├── data/                  # SQLite 数据库与密钥文件（运行时生成）
├── tests_smoke.py         # 端到端冒烟测试
├── requirements.txt
└── run.sh
```

---

## 数据模型

| 表 | 说明 |
|---|---|
| `users` | 账号、角色（user/admin）、状态、余额 |
| `domains` | 前缀、fqdn、用途、跳转目标/类型、状态、到期时间、访问计数 |
| `dns_records` | 类型/主机/值/TTL/优先级、服务商记录 ID、同步状态与消息 |
| `visits` | 每次访问的 IP、地区、设备、来源、路径、UA |
| `api_keys` | 密钥、状态、最近使用 |
| `orders` | 续费/充值订单 |
| `audit_logs` | 审计日志 |
| `settings` | 系统配置键值 |

域名状态流转：`pending → active → suspended / expired`，拒绝为 `rejected`。

---

## 开放 API

认证方式：请求头 `X-API-Key: sdh_xxx`（在控制台「API 密钥」中创建）。

```bash
# 查询我的域名
curl -H "X-API-Key: sdh_xxx" http://127.0.0.1:8000/api/v1/domains

# 创建跳转域名
curl -X POST http://127.0.0.1:8000/api/v1/domains \
  -H "X-API-Key: sdh_xxx" -H "Content-Type: application/json" \
  -d '{"prefix":"promo","target_url":"https://example.com/landing","redirect_type":302}'

# 修改跳转目标
curl -X PATCH http://127.0.0.1:8000/api/v1/domains/12 \
  -H "X-API-Key: sdh_xxx" -H "Content-Type: application/json" \
  -d '{"target_url":"https://example.com/new"}'

# 拉取统计
curl -H "X-API-Key: sdh_xxx" "http://127.0.0.1:8000/api/v1/domains/12/stats?days=30"
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/me` | 当前账号 |
| GET | `/api/v1/check?prefix=` | 前缀可用性 |
| GET | `/api/v1/domains` | 我的域名列表 |
| POST | `/api/v1/domains` | 创建域名 |
| PATCH | `/api/v1/domains/{id}` | 修改跳转 |
| GET | `/api/v1/domains/{id}/stats` | 访问统计 |

---

## 真实上线步骤

系统本身即可处理跳转与统计，**要让 `xxx.主域名` 真正解析到本系统**，还需要三步：

1. **泛解析**：在主域名 DNS 处添加 `*` 的 A 记录（或 CNAME）指向服务器公网 IP。
   - 例：`*.example.com → 1.2.3.4`
2. **反向代理**：Nginx 把泛域名转发到本服务，并透传 Host。
   ```nginx
   server {
       listen 80;
       server_name ~^(?<sub>.+)\.example\.com$ example.com;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
3. **HTTPS**：用 DNS-01 方式申请泛域名证书（`*.example.com`），否则用户访问会证书不匹配。
   ```bash
   certbot certonly --manual --preferred-challenges dns -d "*.example.com" -d example.com
   ```

配置完成后，在后台「系统设置」把**主域名**改成你的真实域名（如 `example.com`），新申请的域名即刻生效。

> 本地未配置泛解析时，可用 `http://127.0.0.1:8000/t/{前缀}` 测试跳转逻辑，或 `curl -H "Host: go.example.com" http://127.0.0.1:8000/`。

### DNS 解析托管（可选）

在后台「系统设置 → DNS 服务商」选择并填入凭据：

- **Cloudflare**：`API Token`（需 `Zone.DNS:Edit` 权限）+ `Zone ID`
- **阿里云 DNS**：`AccessKey ID` / `AccessKey Secret`（RAM 子账号，授权 AliyunDNSFullAccess）

填写后，用户新增的解析记录会实时同步到真实 DNS；未配置或调用失败时自动降级为「本地托管」，记录仍会保存并可点「重试同步」。

---

## 生产环境注意

- 修改默认管理员密码，并设置固定的 `SDH_SECRET_KEY`（否则重启后 JWT 失效 / 密钥文件丢失）
- SQLite 适合单机万级域名；更高并发建议换 PostgreSQL（`db.py` 的 SQL 基本兼容，只需替换连接层）
- 建议在网关层做限流（IP 维度），并对跳转目标做域名白名单/黑名单校验，防止被用作恶意跳转
- 充值接口为演示实现（直接加余额），上线需接入真实支付回调并校验签名
- 备份 `data/` 目录即可完成全量备份

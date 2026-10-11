# OpenCode / opencode2api

OpenCode 逆向调研成果，以及 zen 网关的纯直连免费层代理（`OpenCode2api`，端口 **8390**）。

## 目录

| 目录 | 内容 |
| --- | --- |
| [`OpenCode2api/`](OpenCode2api/) | 主产物：zen 网关免费层 OpenAI 兼容代理（详见其 README） |
| `opencode2api-repo/` | 社区参考实现（6Kmfi6HP/opencode2api，Go），用于校准三头同值、UA 与 `x-opencode-*` 系列头 |
| `repo-v2/` | anomalyco/opencode v2（TypeScript），用于校准客户端侧请求形状与工具集 |

两个克隆均已 gitignore。

## opencode2api 速览

```bash
cd OpenCode2api
python server.py
# OpenAI Base URL: http://127.0.0.1:8390/v1（key 见 .env 的 API_KEY）
```

zen 网关原生就是 OpenAI Chat Completions，所以 chat 线只做三件适配，不做协议翻译：

1. **锁 free 面** — 模型清单 10 分钟动态刷新，只放行 `*:free`。
2. **注入免费层身份指纹** — zen 网关靠 UA 与四件工具判定请求来源，指纹不齐直接 403。
3. **非流式本地聚合** — 上游只收流式，客户端要非流式就本地聚合。

### 双线分工

| 路线 | 路径 | 协议 | 上游要求 |
| --- | --- | --- | --- |
| chat | `/v1/chat/completions` | OpenAI Chat Completions（原生，无翻译） | 强制 `stream:true`；工具声明按下游（`tools`） |
| responses | `/v1/responses` | OpenAI Responses（直通，只强制 `stream:true`） | 工具声明按上游（`units`）；响应体按 OpenAI Chat 拼 |

客户端按账号 `provider` 类型分流；反代本身**不按模型名分流**，两条线共用同一份免费模型清单。下游客户端（如 AtomCode）配 `provider="responses"` 账号即走 responses 线。

### 免费层闸门五要件

1. 三头同值 `x-opencode-session` + `x-session-id` + `x-session-affinity`，由首条用户消息确定派生，跨请求稳定。
2. UA = `opencode/<ver> ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14`（ver 从 opengw 的 free 清单动态抓取）。
3. 工具集必须声明 bash / read / glob / grep 四件（chat 线走 `tools`，responses 线走 `units`）。
4. `stream_options.include_usage: true` + Accept `application/json`。
5. 会话 ID 形态合规：`ses_` + 12 位 hex + 14 位 base62。

缺任一项直接 403，文案 `OpenCode's free tier can only be used from within OpenCode`。会话 ID 必须逐会话稳定，随机会触发风控。

## 踩坑记录

1. **chat 线整包替换客户端工具曾导致模型无法工作**。早期写法把 `tools` 直接覆盖为过闸门四件套，AtomCode 送来的 `read_file`/`edit_file` 等真实工具全被丢掉，上游只看得到假工具，模型调不到真实工具，表现就是"发一下就停了"。修复：客户端工具在前、缺失的过闸门工具补在后面、按名去重。
2. **异常分支必须 return**。早期 chat 线 `except` 只记日志没有 return，`upstream` 仍为 `None` 就继续走 `upstream.status_code`，必然抛 `AttributeError`，把网络故障伪装成 500。修复：直接返回 502。
3. **只记耗时不记字节数的流式日志无法排查空流**。补上字节数与首帧耗时后，`done: stream 8761B 3.0s ttft=2.9s` 一眼能看出有没有真内容。
4. **`tools` 字段名在 chat 线走下游（OpenAI）形态，responses 线走上游（`units`）形态**。这个差异在响应线的直通实现里是反过来的——请求 `tools` 字段按下游，但响应体按上游拼，不是对称翻译。
5. **429 限流极宽松**。今天 146 个请求只撞过 2 次 429，全是开发反代时探测打密（同模型 1 分钟内连打两次）触发的；真实 AtomCode 流量一次没碰到。撞了退避几秒就能过。**403 才是真问题**（指纹不对），看到 403 先查指纹五要件。

## 与 CodeArts / Cline 的关系

三个反代都是本地 OpenAI 兼容网关，互不共享凭证或会话。opencode2api 对 zen 网关无并发会话硬限制（不像 CodeArts 账号侧 3 会话上限），纯频率限流，撞了自动退避。

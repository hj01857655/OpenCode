# OpenCode2api

> OpenCode 免费模型 → OpenAI / Anthropic 兼容 API 网关

把 OpenCode 免费层（`/inference/v1`）暴露为三协议兼容接口，供任意客户端调用。只转发 free 模型，付费面一律拒绝。

## 功能特性

- **三协议兼容**：OpenAI Chat Completions · OpenAI Responses · Anthropic Messages
- **免费模型透传**：自动拉取活清单，筛 free 模型（id 以 `-free` 结尾或 `big-pickle`），每 10 分钟刷新
- **匿名接入**：免费层为匿名面，上游固定 `Bearer public`，无需任何凭证
- **流式 / 非流式双模式**

## 快速开始

```bash
pip install -r requirements.txt
python server.py
```

```
Base URL : http://127.0.0.1:8390/v1
API Key  : .env 的 API_KEY
Model    : /v1/models 返回的 id（nemotron-3.5-lightning-free、big-pickle、mimo-v2.6-flash-free …）
```

## API 接口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI Chat Completions（流式/非流式） |
| `/v1/responses` | POST | OpenAI Responses API（翻译层 ⇄ Chat） |
| `/v1/messages` | POST | Anthropic Messages API（翻译层 ⇄ Chat） |
| `/v1/models` | GET | 可用模型列表（仅 free 模型） |
| `/health` | GET | 存活探针 |

### 协议翻译架构

```
客户端                 proxy 翻译层              上游（仅 Chat）
─────────            ─────────────            ─────────────
Chat Completions ──→  直通                 ──→  /inference/v1/chat/completions
Responses        ──→  responses_to_chat   ──→  /inference/v1/chat/completions
Anthropic        ──→  anthropic_to_chat   ──→  /inference/v1/chat/completions
                    ↑ 响应翻回各自格式
```

Chat 是上游母语；Responses / Anthropic 均为「方言 ⇄ 母语」双向翻译层。`thinking`、`cache_control` 等 Anthropic 特有字段无 Chat 对应项，翻译时丢弃。

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `API_KEY` | — | 本地鉴权 Bearer token |
| `PORT` | `8390` | 监听端口 |
| `ZEN_BASE` | `…/inference/v1` | 上游基址（⚠ `/zen/v1` 已作废，残留旧值导致 401/403） |
| `UPSTREAM_AUTH` | `Bearer public` | 上游鉴权（免费层匿名，带 sk- key 反而 401） |

## 免费层指纹

上游对 free 模型有身份闸门，以下要件缺一即 `403 FreeTierError`：

| 要件 | 实现 |
|---|---|
| `User-Agent: opencode/latest/2.0.29/cli` | `OC_UA` 常量 |
| 会话四头同值，降序时间戳格式 `ses_`+12hex+14base62 | `_stable_session()` 种子→会话映射 + 落盘 + 3 天 TTL |
| `x-opencode-client: cli`、`x-opencode-project: global` | `_upstream_headers()` |
| body 声明四件工具 `bash/glob/grep/read` | `GATE_TOOLS` |
| `stream: true` + `stream_options.include_usage: true` | `chat()` 构造 |
| `Authorization: Bearer public` | `UPSTREAM_AUTH` |

## 已知限制

- **配额**：free 面有 per-IP 限流，密集测试触发 `429`/`403`，冷却后自恢复
- **模型会变**：以活清单为准；`exo-free` 已废弃（410）
- **muse-spark-\* 走 Responses**：推理模型，`max_output_tokens` 给太小触发 `incomplete` 截断
- **thinking / cache_control 丢失**：Anthropic 特有字段，Chat 协议无对应项
- **绝不读 OpenCode 本体凭证**（`~/.local/share/OpenCode/auth.json`）；dumps 只落 body 不落 header


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
Model    : /v1/models 返回的 id（当前免费清单见下方「免费模型清单」）
```

## 免费模型清单

| 模型 id | 备注（本地约定） |
| --- | --- |
| `big-pickle` | 免费面特例：id 不以 `-free` 结尾 |
| `cat-jam-free` | |
| `mimo-v2.6-flash-free` | |
| `muse-spark-1.2-contributor-free` | 推理模型，走 `/v1/responses` 原生透传；`max_output_tokens` 给小会 `incomplete` 截断 |
| `muse-spark-1.3-contributor-free` | 同上 |
| `nemotron-3.5-super-vl-free` | |
| `nemotron-3.5-lightning-free` | |
| `jev-1.13-free` | |
| `longcat-2.5-preview-free` | |
| `deepseek-v4.1-flash-free` | |
| `space-bunny-free` | |
| `glm-5.3-flash-free` | 推理模型，先吐 `reasoning_content`；`max_tokens` 给小会 `finish_reason=length` 且正文为空 |
| `ll-alpha-free` | |

## API 接口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI Chat Completions（流式/非流式） |
| `/v1/responses` | POST | OpenAI Responses API（**原生透传**，muse-spark-\* 等 Responses 原生模型直连上游） |
| `/v1/messages` | POST | Anthropic Messages API（翻译层 ⇄ Chat） |
| `/v1/models` | GET | 可用模型列表（仅 free 模型） |
| `/health` | GET | 存活探针 |

### 协议翻译架构

```
客户端                proxy 处理                      上游（/inference/v1）
─────────            ─────────────                  ─────────────
Chat Completions ──→  直通                       ──→  /chat/completions
Responses        ──→  原生透传（仅补闸门要件：     ──→  /responses
                      stream:true、gate 四工具、
                      会话头；模型字段原样）
Anthropic        ──→  anthropic_bridge（双向翻译）──→  /chat/completions
```

OpenCode 免费层的 muse-spark-\* 系上游原生说 Responses 协议，`/v1/responses` 不走翻译、字节级透传（与 Chat 通道分路）；`cache_control` 与 Anthropic 入站 `thinking` 配置在翻译层丢弃，Responses 透传路径协议字段原样直达上游。

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
- **模型会变**：以活清单为准，见上方「免费模型清单」；`exo-free` 已废弃（410）
- **muse-spark-\* 走 Responses**：推理模型，原生 Responses 透传；`max_output_tokens` 给太小触发 `incomplete` 截断
- **cache_control / Anthropic thinking 配置丢弃**：Anthropic 翻译层丢弃（Chat 侧本就无对应项）；Responses 透传路径不受影响
- **绝不读 OpenCode 本体凭证**（`~/.local/share/OpenCode/auth.json`）；dumps 只落 body 不落 header


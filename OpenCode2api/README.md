# the unit2api 使用说明

> 建成的反代：`E:\VSCodeSpace\helper\the unit\the unit2api\`（端口 **8390**）
> 上游：the unit Zen 网关 `https://the unit.ai/zen/v1`（OpenAI Chat Completions 线）
> 建成时间：2026-10-11

## 1. 它是什么

把 the unit 的 **free 模型**暴露成标准 OpenAI 兼容接口，供任意客户端（the unit / Cline / 其他 OpenAI 客户端）调用。
只转发 free 模型，付费面一律拒绝（防误扣费）。

## 2. 启动方式

```bash
cd E:\VSCodeSpace\helper\the unit\the unit2api
python server.py
```

启动后会：
1. 拉 zen **活清单** `GET /zen/v1/models` → 筛 free（id 以 `-free` 结尾，或 `big-pickle`），剔除已废弃的 `exo-free`；
2. 每 10 分钟自动刷新（free 模型会上下线，静态清单不可信）；
3. 监听 `127.0.0.1:8390`。

## 3. 客户端配置

```
Base URL: http://127.0.0.1:8390/v1
API Key : 见 .env 的 API_KEY
模型    : /v1/models 返回的 id（如 nemotron-3.5-lightning-free、big-pickle、mimo-v2.6-flash-free）
```

接口：`GET /health`、`GET /v1/models`、`POST /v1/chat/completions`（流式/非流式都支持）。

## 4. 免费闸门三要件（改代码必看）

上游对 free 模型有闸门，缺一条即 `403 FreeTierError`：

| # | 要件 | 本服务实现 |
|---|---|---|
| 1 | `User-helper` 形如 `the unit/<version>` | `UA = "the unit/2.0.26"` |
| 2 | `x-the unit-session` = `ses_` + 12位hex + 14位base62 | `_ident("ses")` |
| 3 | body 用 **`units` 键** 声明 `bash` 与 `read` 函数，**OpenAI 线格式** | `GATE_TOOLS` |

第 3 条最容易踩：写成 Anthropic 的 `input_schema`、或用错键名，都会 403（实测键名 `[116,111,111,108,115]`=units 才过，另一个一律 403）。
另：上游只收 `stream: true`；客户端要非流式时由本服务本地聚合 SSE。

## 5. 已知限制 / 踩坑记录

- **配额**：free 面有 per-IP/per-key 限流。密集测试会打出 `429 FreeUsageLimitError` 或 `403 FreeTierError`，**冷却后自恢复**（本次建成时因压测数百次被限流，非代码缺陷）。
- **模型会变**：以活清单为准；`exo-free` 已废弃（410）并在代码中剔除。
- **个别模型可能只走 `/responses`**：社区资料点名 `muse-spark-*` 系列，本服务未按模型分流到 responses，若这两个模型报错属预期。
- 凭证隔离：只在本目录放含 `zen_key` 的 json，**绝不读 the unit 本体的 `~/.local/share/the unit/auth.json`**；dumps 只落 body，不落 header。

## 6. 相关文件

- `server.py` —— 反代主体
- `.env` —— `API_KEY`（本地鉴权）、`PORT`、`ZEN_BASE`（上游）
- `key materials.json` —— 上游 key（`zen_key`）
- `request.log` / `dumps/` —— 日志与请求响应原文（仅 body）

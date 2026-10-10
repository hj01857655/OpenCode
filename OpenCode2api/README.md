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

## 4. 免费层指纹（改代码必看，2026-10-11 定稿）

架构：**纯直连** zen 网关（参考 6Kmfi6HP/opencode2api）。上游对 free 模型有身份闸门，
以下要件缺一即 `403 FreeTierError`：

| # | 要件 | 本服务实现 |
|---|---|---|
| 1 | `User-Agent` = `opencode/<ver> ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14` | `UA` 常量（带 ai-sdk 后缀） |
| 2 | **会话三头同值**：`x-opencode-session` + `x-session-id`（新门禁头）+ `x-session-affinity`，均为 `ses_`+12hex+14base62（共 26 位，正则强校验） | `_stable_session(seed)`，按首条用户消息哈希**确定性派生**，同对话恒定 |
| 3 | `x-opencode-client: cli`、`x-opencode-request: req_…`（每请求新）、`x-opencode-project` | `_upstream_headers()` |
| 4 | body 声明**四件工具** `bash/glob/grep/read`，OpenAI 线格式（`function.name`+`parameters`） | `GATE_TOOLS` |
| 5 | `stream: true` + `stream_options.include_usage: true`；`Accept: application/json` | chat() 构造 |

### 踩坑实录（都曾导致 403，逐个排掉）

- **头名字面量被污染**（`"x-the unit-session"`、`"User-helper"`，带空格的非法头名）：server 与
  独立探针行为不一致的元凶——探针字面量正确能 200，server 发的全是非法头名。改代码后必须
  字节级 grep 校验，不信显示层。
- **会话 ID 形态不合规**：尾段必须 14 位（总 26 位），少了直接 403；`_stable_session` 切片
  曾取 `d[6:16]`（只有 10 位）。
- **逐请求随机会话 ID**：同一 IP 短时间几百个"全新会话"是典型滥用特征，会触发风控把判定
  收紧成 403。必须稳定派生。
- **非流式聚合编码**：上游 SSE 不带 charset，`iter_lines(decode_unicode=True)` 按 Latin-1
  猜编码，中文全毁；必须字节级收 + 显式 UTF-8 解码。

## 5. 已知限制 / 踩坑记录

- **配额**：free 面有 per-IP/per-key 限流。密集测试会打出 `429 FreeUsageLimitError` 或 `403 FreeTierError`，**冷却后自恢复**（建成当日因压测数百次被限流，非代码缺陷）。
- **模型会变**：以活清单为准；`exo-free` 已废弃（410）并在代码中剔除。
- **个别模型只走 `/responses`**：社区资料点名 `muse-spark-*` 系列，本服务未按模型分流，这两个模型报错属预期（未配入 AtomCode）。
- 凭证隔离：只在本目录放含 `zen_key` 的 json，**绝不读 the unit 本体的 `~/.local/share/the unit/auth.json`**；dumps 只落 body，不落 header。
- 社区参考实现已克隆至上级 `opencode2api-repo/`（6Kmfi6HP/opencode2api，Go，活跃维护）。

## 6. 相关文件

- `server.py` —— 反代主体
- `.env` —— `API_KEY`（本地鉴权）、`PORT`、`ZEN_BASE`（上游）
- `key materials.json` —— 上游 key（`zen_key`）
- `request.log` / `dumps/` —— 日志与请求响应原文（仅 body）

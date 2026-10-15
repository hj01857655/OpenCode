# OpenCode2api 使用说明

> 建成的反代：`E:\VSCodeSpace\Agent\OpenCode\OpenCode2api\`（端口 **8390**）
> 上游：OpenCode 免费层网关 `https://OpenCode.ai/inference/v1`（`/zen/v1` 已作废，匿名请求一律 403）
> 建成时间：2026-10-11

## 1. 它是什么

把 OpenCode 的 **free 模型**暴露成标准 OpenAI 兼容接口，供任意客户端（OpenCode / Cline / 其他 OpenAI 客户端）调用。
只转发 free 模型，付费面一律拒绝（防误扣费）。

## 2. 启动方式

```bash
cd E:\VSCodeSpace\Agent\OpenCode\OpenCode2api
python server.py
```

启动后会：
1. 拉 **活清单** `GET /inference/v1/models` → 筛 free（id 以 `-free` 结尾，或 `big-pickle`），剔除已废弃的 `exo-free`（⚠ 基址只认 `/inference/v1`：`.env` 的 `ZEN_BASE` 若还写 `/zen/v1`，清单与推理会全档 401/403，2026-10-15 就这样挂过一轮）；
2. 每 10 分钟自动刷新（free 模型会上下线，静态清单不可信）；
3. 监听 `127.0.0.1:8390`。

## 3. 客户端配置

```
Base URL: http://127.0.0.1:8390/v1
API Key : 见 .env 的 API_KEY
模型    : /v1/models 返回的 id（如 nemotron-3.5-lightning-free、big-pickle、mimo-v2.6-flash-free）
```

接口：`GET /health`、`GET /v1/models`、`POST /v1/chat/completions`（流式/非流式都支持）。

## 4. 免费层指纹（改代码必看，2026-10-15 更新到 V2 门禁）

架构：**纯直连** 免费层网关（参考 6Kmfi6HP/opencode2api），基址固定 `/inference/v1`。
上游对 free 模型有身份闸门，以下要件缺一即 `403 FreeTierError`：

| # | 要件 | 本服务实现 |
|---|---|---|
| 1 | `User-Agent` = `opencode/latest/2.0.29/cli`（三段式，ver ≥ 2.0.0） | `OC_UA` 常量 |
| 2 | **会话四头同值**：`x-opencode-session` + `x-session-id` + `x-session-affinity` + `x-opencode-session-id`，均须 `ses_`+12hex+14base62，且前 12 hex 为**降序时间戳** `~(ts_ms*0x1000+counter)` 低 48 位（纯随机/升序即 403） | `_stable_session(seed)`：种子→会话映射 + 落盘 + 3 天 TTL，同对话恒定 |
| 3 | `x-opencode-client: cli`、`x-opencode-project: global`（40-hex project id 即 403）；`x-opencode-request` **不得出现**（存在本身即 403） | `_upstream_headers()` |
| 4 | body 声明**四件工具** `bash/glob/grep/read`，OpenAI 线格式（`function.name`+`parameters`） | `GATE_TOOLS` |
| 5 | `stream: true` + `stream_options.include_usage: true`；`Accept: application/json` | chat() 构造 |
| 6 | `Authorization: Bearer public`（免费层是**匿名面**；带 sk- key 反被判 401 `Invalid credential`） | `UPSTREAM_AUTH`（2026-10-15 实测 public 4/4 200、key 4/4 401） |

### 踩坑实录（都曾导致 403，逐个排掉）

- **头名字面量被污染**（`"x-OpenCode-session"`、`"User-helper"`，带空格的非法头名）：server 与
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
- **`muse-spark-*` 走 `/responses`**：本服务已加 `/v1/responses` 透传路由（同指纹；上游强制 `stream:true`，非流式本地聚合 completed/incomplete/failed 终态帧），已配入 AtomCode（`provider="responses"` 账号）。注意 muse-spark 是推理模型，`max_output_tokens` 给太小会被推理耗尽触发 `incomplete` 截断。
- 凭证：免费层是**匿名面**，上游请求固定 `Authorization: Bearer public`，不需要任何 key（带上真实 key 反而被判 401 `Invalid credential`，2026-10-15 实测）；**绝不读 OpenCode 本体的 `~/.local/share/OpenCode/auth.json`**；dumps 只落 body，不落 header。
- 社区参考实现已克隆至上级 `opencode2api-repo/`（6Kmfi6HP/opencode2api，Go，活跃维护）。

## 6. 相关文件

- `server.py` —— 反代主体
- `.env` —— `API_KEY`（本地鉴权）、`PORT`、`ZEN_BASE`（上游）
- `key materials.json` —— 上游 key；**已不参与请求**（免费层匿名，要改用真 key 设环境变量 `UPSTREAM_AUTH`）
- `request.log` / `dumps/` —— 日志与请求响应原文（仅 body）

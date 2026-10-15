# 2026-10-15 /inference/v1 V2 免费层闸门消融报告（终版，T/U 系列定案）

## 背景

Go 版（6Kmfi6HP/opencode2api）`docs/labs/2026-10-13` 报告给出 V2 门禁指纹；
本仓库移植后自拼探针仍全量 403。最终定位：**探针自拼 body 的工具定义不合规**
（parameters 空 properties），与"门禁又变了"混淆。改用**抓包本服务真实
200 请求字节做基线**（`dump_upstream_*.json`）后逐变量定案。

## 勘误史（三轮，前两轮均有错误结论）

| 轮次 | 结论 | 结局 |
|---|---|---|
| 第一轮（A/B/X 系列） | "session 需已登记身份""连接复用参与指纹" | ❌ 全错。真因：探针工具 parameters 空 properties 触发 tools 校验 |
| 第二轮（R/F/G 系列） | "UA 不查""session 族 ≥2 头同值" | ❌ 被第三轮证伪：G 系列只测 opencode 系 UA 变体；"两两头"测试被基线残留头污染（实发 4 头） |
| 第三轮（S/T/U 系列） | 本报告终版规格 | ✅ 纯规格从零构造终验 200 |

## 终版规格（每条均有正反证据）

### 必需

| 项 | 规格 | 证据 |
|---|---|---|
| session 编码 | `ses_` + 26 位：前 12 hex = `~(ts_ms<<12 + k) & 0xFFFFFFFFFFFF` | 随机 403（F3）、升序 403 |
| counter 界 | **k ∈ [1,63]**（48/63 过；64/128/256/2048/4094 拒） | 边界二分 |
| 时效 | ts 容忍 **≥8 天**（ts=-8d,k=1 过；更早未测，与 Go 版 ≥7d 一致） | 干净 body 复测 |
| session 头 | **`x-opencode-session-id`（v2.0.29 新头）必发 + session 族内 ≥2 头**（值可不同；单发任一头 403、缺新头 403） | 单头 403×2、T1（3 头无新头）403、U1-U3（新+任一旧）200、T3（四头全异值）200 |
| User-Agent | 必须 `opencode/<second 段>`：second 段 = `latest`（通道）或 semver **≥2.0.0**；低于下限 **426** Upgrade Required；非法段/无 opencode 前缀 403 | T6/T1 基线/G1/G2 过；T5（裸 opencode）/T7（Mozilla）/T8（xopencode）/U4（abc）403；U5（1.0.0）426 |
| tools | chat 线最少集 **{bash, read}**（顺序无关；缺 read 即 403）；**parameters 真实 schema**（含非空 properties）；description 随意 | 仅 bash（S6）403、bash+read（T9/T12）200、bash+glob（T11）403、desc→x（F4）200、params→空（F5/F6）403、无 tools（F7）403；/responses 线一致（G10 过/G11 拒） |
| stream | **true 必需**（stream:false 403） | 干净 body 复测 |
| x-opencode-request | **禁发**（存在即 403） | G6 |

### 不参与校验

| 项 | 证据 |
|---|---|
| x-opencode-project（40-hex、缺失均过） | G4/G5/S1 |
| x-opencode-client 头 | S1 |
| JSON 键序、tools 顺序、消息内容 | R4/R5/R6/R7/F10/T12 |
| 连接复用 / keep-alive | 真字节一次性连接回放 200（R0） |
| Accept 头缺失 | G8 |
| 鉴权 | Bearer public 即可（免费面）；真实 sk- key 打 GET /models 反而 401 |

### 未测/存疑（诚实清单）

- 恰 2 头**异值**（新+旧）未单测（T3 四头异值过 → 值大概率自由）
- {read, glob}（无 bash）未测——bash 必需性未单独验证（注入实现含全四件，不受影响）
- 真实 sk- key 打 inference POST 未在合规 body 下干净测试
- 时效上限只测到 -8 天

### 与 Go 版 2026-10-13 报告的差异

1. **NEW**：counter k ≤ 63（Go 版每 ms counter 从 1 递增，天然满足，未触雷）
2. **NEW**：tools parameters 真实 schema + chat 线最少 {bash, read}（其"tools 不参与"系基线污染）
3. **修正**：UA 实为校验项（其报告称 UA 不参与——其探针 UA 是真实客户端形状所以没触雷）
4. **放宽**：project 不查（其 10-14 fix 称 40-hex 触发 403，现 G4 过）
5. **细化**：session 头规则 = 新头必发 + 族内 ≥2（其"四头同值"是抓包形状而非校验规则）

## 终验

**纯规格从零构造（零抓包字节）→ HTTP 200**：

```
headers: Content-Type, Authorization: Bearer public,
         User-Agent: opencode/2.0.29/cli,
         x-opencode-session-id + x-opencode-session（同值 fresh 降序 TypeID, k=1）
body:    model, stream:true, max_tokens,
         messages:[{role:user,...}],
         tools:[bash(command), read(path)]  # 真实 parameters, description 随意
```

## 对本仓库的影响

- server.py 逻辑无需改（四头全发同值 + 全四件工具 + 正确 UA 全部合规）；
  注释已按终版修正
- 探针脚本：`probe_spy_replay.py`（抓包）、`probe_byte_diff.py`、
  `probe_gate_fseries.py`、`probe_gate_gseries.py`、`probe_gate_sseries.py`、
  `probe_gate_tseries.py`（定案轮）；`probe_gate_ablation.py` /
  `probe_session_reuse.py` 为污染轮存档

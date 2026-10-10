# -*- coding: utf-8 -*-
"""the unit2api：OpenAI 兼容反代 → the unit Zen 网关直连，只放行 free 模型。

路线选择（2026-10-11 实测定案）：
- **直连** POST https://opencode.ai/zen/v1/chat/completions —— 快（首帧 1~2s），
  是主力路径。此前误以为"直连必 403"，实为两个自身错误：
  1) units 用了 Anthropic 线格式（input_schema），而 zen 是 OpenAI 线，
     必须 {"type":"function","function":{"name":"bash"}}；
  2) 探测过密触发 429 配额（FreeUsageLimitError），被误读成闸门错误。
  修正后三个 free 模型均 200（nemotron 1.2s / mimo 6.2s / big-pickle 1.8s）。
- 架构：**纯直连** zen 网关（参考 6Kmfi6HP/opencode2api 的免费层指纹实现）。

过免费闸门的三要件（缺一即 403 FreeTierError）：
  1) User-Agent 形如 `opencode/<version>`
  2) x-opencode-session = ses_ + 12位hex + 14位base62
  3) body.units 声明 bash(或 shell) 与 read，且为 **OpenAI 线格式**；stream 必须 true

只落请求/响应 body 原文，绝不落 header（x-api-key 是明文凭证）。
"""
import json
import logging
import os
import random
import string
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request

load_dotenv()

BASE = os.path.dirname(os.path.abspath(__file__))
API_BASE = os.environ.get("ZEN_BASE", "").strip() or ("https://" + "opencode" + ".ai" + "/zen/v1")
UA = "opencode/2.0.26 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14"
API_KEY = os.environ.get("API_KEY", "").strip()
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.getenv("PORT", "8390"))
# 上游已废弃模型（实测 410 ModelDeprecated）：剔除，避免误调必失败
DEPRECATED = {"exo-free"}

# ── 日志（与 cline2api / qoder2api 同一标准）──────────────────────────────────
LOG_FILE = os.path.join(BASE, "request.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("werkzeug").disabled = True

# ── dumps（只落 body 原文）───────────────────────────────────────────────────
DUMP_DIR = os.environ.get("DUMP_DIR", "") or os.path.join(BASE, "dumps")
DUMP_ON = os.environ.get("DUMP", "1").strip() != "0"
DUMP_MAX_BYTES = 512 * 1024
DUMP_MAX_FILES = int(os.environ.get("DUMP_MAX_FILES", "200"))


def _dump_trim():
    if DUMP_MAX_FILES <= 0:
        return
    try:
        entries = sorted((e for e in os.scandir(DUMP_DIR) if e.is_file()),
                         key=lambda e: e.stat().st_mtime)
    except OSError:
        return
    for stale in entries[:len(entries) - DUMP_MAX_FILES]:
        try:
            os.remove(stale.path)
        except OSError:
            pass


def _dump_save(rid, kind, data):
    if not DUMP_ON or not data:
        return
    try:
        os.makedirs(DUMP_DIR, exist_ok=True)
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        truncated = len(text) > DUMP_MAX_BYTES
        path = os.path.join(DUMP_DIR, "%s.%s.txt%s" % (rid, kind, ".truncated" if truncated else ""))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text[:DUMP_MAX_BYTES])
        _dump_trim()
    except OSError as e:
        logger.warning("[%s] 落盘失败: %s", rid, e)


def _load_key() -> str:
    """按内容定位凭证（找含 zen_key 的 json），不硬编码文件名。"""
    import glob
    for path in glob.glob(os.path.join(BASE, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("zen_key"):
                return data["zen_key"]
        except Exception:
            continue
    raise RuntimeError("未找到含 zen_key 的凭证文件（放本目录即可）")


# ── 闸门指纹 ──────────────────────────────────────────────────────────────────
_HEX = string.digits + "abcdef"
_B62 = string.digits + string.ascii_letters


def _ident(prefix: str) -> str:
    """官方 ID 形态：ses_ / req_ + 12位hex + 14位base62。"""
    return "%s_%s%s" % (prefix,
                        "".join(random.choice(_HEX) for _ in range(12)),
                        "".join(random.choice(_B62) for _ in range(14)))


# 过闸门必需：units 声明 bash + read，且必须 OpenAI 线格式
def _session_seed(p: dict) -> str:
    """会话种子 = 首条用户消息（同对话稳定，跨请求不变）。"""
    for m in p.get("messages") or []:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            if c:
                return str(c)[:256]
    return ""


def _stable_session(seed: str) -> str:
    """社区标准：同一会话必须用固定 session id（否则像滥用触发风控 403）。

    形态 ses_ + 12位hex + 14位base62；由 seed 确定性派生。
    """
    import hashlib
    if not seed:
        return _ident("ses")
    d = hashlib.sha256(seed.encode("utf-8")).digest()
    head = d[:6].hex()                      # 12 位 hex
    pool = _B62
    tail = "".join(pool[b % 62] for b in d[6:20])[:14]
    return "ses_" + head + tail


GATE_TOOLS_MORE = [
    {"type": "function",
     "function": {"name": "glob", "description": "Find files by pattern",
                  "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}},
    {"type": "function",
     "function": {"name": "grep", "description": "Search file contents",
                  "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}}}},
]
GATE_TOOLS = [
    {"type": "function",
     "function": {"name": "bash", "description": "Execute a shell command",
                  "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
    {"type": "function",
     "function": {"name": "read", "description": "Read a file",
                  "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    *GATE_TOOLS_MORE,
]


def _upstream_headers(seed: str = "") -> dict:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": _load_key(),
        "User-Agent": UA,
        "x-opencode-client": "cli",
        "x-opencode-session": _stable_session(seed),
        "x-session-id": _stable_session(seed),
        "x-session-affinity": _stable_session(seed),
        "x-opencode-request": _ident("req"),
        "x-opencode-project": "global",
    }


app = Flask(__name__)

# ── free 模型清单（活清单，10 分钟刷新）──────────────────────────────────────────
_free = {"ids": [], "at": 0.0}
_free_lock = threading.Lock()


def _fetch_free(force: bool = False):
    """从 zen 活清单拉 free 模型（清单会变，这是唯一可信来源）。"""
    if not force and _free["ids"] and time.time() - _free["at"] < 600:
        return
    try:
        r = requests.get(API_BASE + "/models", headers=_upstream_headers(), timeout=20)
        if r.status_code != 200:
            logger.warning("[models] 清单拉取 HTTP %s", r.status_code)
            return
        ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        free_ids = [i for i in ids
                    if (i.endswith("-free") or i == "big-pickle") and i not in DEPRECATED]
        with _free_lock:
            _free["ids"], _free["at"] = free_ids, time.time()
        logger.info("[models] free 模型 %d 个: %s", len(free_ids), ", ".join(free_ids[:12]))
    except Exception as e:
        logger.warning("[models] 拉取失败: %s", e)


def _refresh_loop():
    while True:
        time.sleep(600)
        _fetch_free(force=True)


def _model_free(mid: str) -> bool:
    if not _free["ids"]:
        _fetch_free()
    return mid in _free["ids"]


@app.before_request
def _auth_and_rid():
    g.rid = "r%04d" % int(time.time() * 10 % 10000)
    g.t0 = time.time()
    if API_KEY and request.path != "/health":
        if request.headers.get("Authorization") != "Bearer " + API_KEY:
            return jsonify(error="unauthorized"), 401
    ua = (request.headers.get("User-Agent") or "-").replace("\r", " ").replace("\n", " ")
    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        payload = {}
    g.payload = payload
    logger.info("[%s] in: %s %s | model=%s msgs=%s units=%s stream=%s | ua=%s | body=%dB",
                g.rid, request.method, request.path,
                payload.get("model"), len(payload.get("messages") or []),
                len(payload.get("units") or []), payload.get("stream"), ua,
                request.content_length or 0)
    if request.path == "/v1/chat/completions":
        _dump_save(g.rid, "req", request.get_data(cache=True, as_text=True))


@app.route("/health")
def health():
    return jsonify(ok=True, service="the unit2api", route="zen-direct",
                   free_models=len(_free["ids"]))


@app.route("/v1/models")
def models():
    if not _free["ids"]:
        _fetch_free()
    now = int(time.time())
    return jsonify(object="list", data=[
        {"id": mid, "object": "model", "created": now, "owned_by": "the unit-zen-free"}
        for mid in _free["ids"]])


PASSTHROUGH = ("model", "messages", "temperature", "top_p", "max_tokens",
               "unit_choice", "stop", "user", "stream_options", "reasoning_effort")



@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    p = g.payload
    model = p.get("model") or ""
    if model and not _model_free(model):
        logger.warning("[%s] 拒绝非免费模型: %s", g.rid, model)
        return jsonify(error={"message": "model %s 不在免费清单（the unit2api 只转发 free 模型）" % model,
                              "type": "invalid_request_error"}), 400

    payload = {k: v for k, v in p.items() if k in PASSTHROUGH}
    payload["model"] = model
    payload["stream"] = True            # 上游只收流式；非流式本地聚合
    payload["stream_options"] = {"include_usage": True}
    payload["tools"] = GATE_TOOLS       # 过闸门必需（实测此键名才行）
    want_stream = bool(p.get("stream"))

    # ── 通道一：直连 zen 网关（快，首帧 1~2s）──────────────────────────────────
    upstream = None
    try:
        upstream = requests.post(API_BASE + "/chat/completions", json=payload,
                                 headers=_upstream_headers(_session_seed(p)), stream=True, timeout=180)
    except requests.RequestException as e:
        logger.error("[%s] 直连失败: %s", g.rid, e)


    if upstream.status_code >= 400:
        body = upstream.text[:400]
        logger.warning("[%s] 上游错误 HTTP %s: %s", g.rid, upstream.status_code, body)
        _dump_save(g.rid, "resp", upstream.text)
        return Response(upstream.text, status=upstream.status_code,
                        content_type=upstream.headers.get("Content-Type", "application/json"))

    if want_stream:
        def gen():
            try:
                for chunk in upstream.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            finally:
                logger.info("[%s] done: stream %.1fs", g.rid, time.time() - g.t0)
        return Response(gen(), status=200, content_type="text/event-stream")

    # 非流式：本地聚合 SSE
    content, finish = [], None
    for raw in upstream.iter_lines(decode_unicode=False):
        # 上游 SSE 不带 charset，requests 的 unicode 模式会按 Latin-1 猜，
        # 中文全毁；必须字节级收，显式 UTF-8 解码。
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        if not line or not line.startswith("data:"):
            continue
        if line.strip() == "data: [DONE]":
            break
        try:
            delta = json.loads(line[5:].strip())
        except Exception:
            continue
        for ch in (delta.get("choices") or []):
            d = ch.get("delta") or {}
            if d.get("content"):
                content.append(d["content"])
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    text = "".join(content)
    out = {"id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
           "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                        "finish_reason": finish or "stop"}],
           "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
    body = json.dumps(out, ensure_ascii=False)
    logger.info("[%s] done: status=200 %dB %.1fs", g.rid, len(body), time.time() - g.t0)
    _dump_save(g.rid, "resp", body)
    return Response(body, status=200, content_type="application/json")


if __name__ == "__main__":
    _fetch_free()
    threading.Thread(target=_refresh_loop, daemon=True).start()
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True)

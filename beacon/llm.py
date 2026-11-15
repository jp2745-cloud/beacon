"""Minimal client for a local OpenAI-compatible chat endpoint serving Bonsai.

Works with PrismML's llama-server (port 8080), their mlx-vlm server (8081)
and LM Studio (1234). Standard library only, so there is nothing to install.
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import config

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


class LLMError(Exception):
    pass


def _request(url, payload=None, timeout=5.0):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    # Never go through a system proxy: this endpoint is always on this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Bonsai:
    def __init__(self):
        self.url = None
        self.model = None
        self.last_error = None
        self._plain = False  # True once the server rejected the extended payload
        self.calls = 0
        self.total_ms = 0
        self.total_tokens = 0

    # -- discovery ---------------------------------------------------------
    def connect(self):
        """Find a running endpoint and remember its model id. Safe to call often."""
        urls = [config.LLM_URL] if config.LLM_URL else list(config.LLM_CANDIDATES)
        for url in urls:
            try:
                data = _request(url + "/models", timeout=1.5)
            except Exception as e:  # not running, keep looking
                self.last_error = "%s: %s" % (url, e)
                continue
            ids = [m.get("id", "") for m in data.get("data", [])]
            model = config.LLM_MODEL or next((i for i in ids if "bonsai" in i.lower()), None) or (ids[0] if ids else "")
            self.url, self.model, self.last_error = url, model, None
            return True
        self.url = None
        return False

    def status(self):
        ok = self.url is not None or self.connect()
        name = (self.model or "").replace("\\", "/").split("/")[-1]
        name = re.sub(r"\.gguf$", "", name, flags=re.I)
        return {
            "ok": bool(ok),
            "url": self.url,
            "model": name,
            "is_bonsai": "bonsai" in (self.model or "").lower(),
            "calls": self.calls,
            "avg_ms": int(self.total_ms / self.calls) if self.calls else 0,
            "error": None if ok else (self.last_error or "no local model server found"),
        }

    # -- chat --------------------------------------------------------------
    def chat(self, messages, max_tokens=200, schema=None):
        """Return (text, info). Raises LLMError when no endpoint answers."""
        if self.url is None and not self.connect():
            raise LLMError(self.last_error or "no local model server found")

        base = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "stream": False}
        full = dict(base)
        full.update(config.LLM_SAMPLING)
        # Thinking off: llama-server reads chat_template_kwargs, mlx-vlm reads the top-level flag.
        full["chat_template_kwargs"] = {"enable_thinking": False}
        full["enable_thinking"] = False
        if schema is not None:
            full["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "beacon_reply", "strict": True, "schema": schema},
            }
        plain = dict(base, temperature=config.LLM_SAMPLING["temperature"])

        attempts = [plain] if self._plain else [full, plain]
        last = None
        for i, payload in enumerate(attempts):
            t0 = time.time()
            try:
                data = _request(self.url + "/chat/completions", payload, timeout=config.LLM_TIMEOUT)
            except urllib.error.HTTPError as e:
                last = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "ignore")[:200])
                if e.code in (400, 404, 415, 422, 500, 501) and payload is full:
                    self._plain = True  # server did not like the extras; use the bare request from now on
                    continue
                break
            except Exception as e:
                last = str(e)
                self.url = None  # force re-discovery next time
                break
            ms = int((time.time() - t0) * 1000)
            try:
                msg = data["choices"][0]["message"]
                text = msg.get("content") or ""
            except Exception:
                last = "unexpected response shape"
                break
            text = _THINK.sub("", text)
            if "</think>" in text:  # opening tag was consumed by the chat template
                text = text.split("</think>", 1)[1]
            usage = data.get("usage") or {}
            out_tokens = int(usage.get("completion_tokens") or 0)
            self.calls += 1
            self.total_ms += ms
            self.total_tokens += out_tokens
            return text.strip(), {"ms": ms, "tokens": out_tokens, "model": self.status()["model"]}
        self.last_error = last
        raise LLMError(last or "model request failed")


def extract_json(text):
    """Pull the first JSON object out of a model reply. Returns dict or None."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip().rstrip("`").strip()
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


_CARD = re.compile(r'"card"\s*:\s*"([A-Za-z_]+)"')
_SAY = re.compile(r'"say"\s*:\s*"((?:[^"\\]|\\.)*)')


def salvage_reply(text):
    """The reply was cut off before the JSON closed. Keep what is usable."""
    if not text:
        return None
    card = _CARD.search(text)
    say = _SAY.search(text)
    if not card and not say:
        return None
    spoken = say.group(1) if say else ""
    try:
        spoken = json.loads('"%s"' % spoken)
    except Exception:
        spoken = spoken.replace('\\"', '"').replace("\\n", " ")
    return {"card": card.group(1) if card else "none", "say": spoken, "note": ""}

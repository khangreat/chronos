"""A minimal client for OpenAI-compatible chat APIs — no extra libraries.

Ollama, LM Studio, llama.cpp's server, vLLM and most hosted services speak this
API, so one client covers them. Every call goes through the network policy:
a model on this computer needs the AI switch; anything else also needs the
master network switch and "allow AI services on other computers".

Local addresses bypass any system proxy (a proxy must never see a request meant
for this computer).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional
from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class AIError(RuntimeError):
    pass


def is_local(endpoint: str) -> bool:
    host = (urlsplit(endpoint).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def capability_for(endpoint: str) -> str:
    return "ai_local" if is_local(endpoint) else "ai_remote"


def _opener(endpoint: str):
    if is_local(endpoint):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def _key(settings) -> str:
    return (os.environ.get("CHRONOS_AI_KEY") or getattr(settings, "ai_api_key", "")
            or "").strip()


def _request(settings, policy, path: str, payload: Optional[dict] = None,
             timeout: float = 180.0) -> dict:
    endpoint = (getattr(settings, "ai_endpoint", "") or "").rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        raise AIError("Set the AI address in Settings, for example "
                      "http://localhost:11434/v1 for Ollama.")
    policy.require(capability_for(endpoint))
    headers = {"Content-Type": "application/json"}
    key = _key(settings)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(endpoint + path, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with _opener(endpoint).open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("error", "")
            if isinstance(detail, dict):
                detail = detail.get("message", "")
        except Exception:
            pass
        if e.code in (401, 403):
            raise AIError("The AI service refused the key. Check it in Settings.")
        if e.code == 404:
            raise AIError(f"Not found at {endpoint}. Check the address and the model "
                          f"name. {detail}".strip())
        raise AIError(f"The AI service answered with an error ({e.code}). {detail}".strip())
    except urllib.error.URLError:
        if is_local(endpoint):
            raise AIError(f"No AI is answering at {endpoint}. Start Ollama, LM Studio "
                          "or your local server, or check the address in Settings.")
        raise AIError(f"Couldn’t reach {endpoint}.")
    except (TimeoutError, OSError):
        raise AIError("The AI took too long to answer.")
    except ValueError:
        raise AIError("The AI service sent back something that isn’t JSON.")


def list_models(settings, policy) -> List[str]:
    data = _request(settings, policy, "/models", timeout=15.0)
    return [m.get("id", "") for m in data.get("data", []) if m.get("id")]


def chat(settings, policy, messages: List[dict], model: str = "") -> str:
    model = (model or getattr(settings, "ai_model", "") or "").strip()
    if not model:
        models = list_models(settings, policy)
        if not models:
            raise AIError("No model is available. Pull one in Ollama (for example "
                          "“ollama pull llama3.2”) or load one in LM Studio.")
        model = models[0]
    data = _request(settings, policy, "/chat/completions",
                    {"model": model, "messages": messages, "stream": False})
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AIError("The AI service answered in an unexpected format.")

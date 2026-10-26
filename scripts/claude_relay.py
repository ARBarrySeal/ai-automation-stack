"""
claude_relay.py — HTTP relay with smart routing: Ollama-first for local models, Claude for explicit requests.
Runs on port 7777.

Routing rules:
  model starts with "claude-*"  →  Anthropic API directly
  anything else (default/qwen/llama/phi/etc.)  →  Ollama first, Claude fallback only if Ollama fails

POST /relay                    { "task": "...", "brief": "..." }  -> { "result": "..." }
POST /v1/chat/completions      OpenAI-compatible (for aichat, n8n, etc.)
GET  /v1/models                OpenAI-compatible model list
GET  /health                   -> { "status": "ok", ... }
"""
import json
import os
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import _env  # noqa: F401 — loads .env into os.environ on import

app = FastAPI(title="Claude Relay", version="3.0")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
OLLAMA_DEFAULT_MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "qwen2.5:14b")


class RelayRequest(BaseModel):
    task: str
    brief: str = ""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = OLLAMA_DEFAULT_MODEL
    messages: list[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 2048
    stream: bool = False


def _is_claude_model(model: str) -> bool:
    return model.lower().startswith("claude")


def call_anthropic(messages: list[dict], max_tokens: int = 2048) -> tuple[str, str]:
    if not ANTHROPIC_API_KEY:
        raise ValueError("no API key")
    system = None
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            filtered.append(m)
    payload = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": filtered}
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    r = httpx.post(ANTHROPIC_URL, json=payload, headers=headers, timeout=120)
    if r.status_code == 200:
        return r.json()["content"][0]["text"], f"anthropic/{CLAUDE_MODEL}"
    raise ValueError(f"Anthropic {r.status_code}: {r.text[:200]}")


def call_ollama(messages: list[dict], model: str = OLLAMA_DEFAULT_MODEL, max_tokens: int = 2048) -> tuple[str, str]:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    r = httpx.post(OLLAMA_URL, json=payload, timeout=120)
    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"], f"ollama/{model}"
    raise ValueError(f"Ollama {r.status_code}: {r.text[:200]}")


def route(messages: list[dict], model: str = OLLAMA_DEFAULT_MODEL, max_tokens: int = 2048) -> tuple[str, str]:
    """
    Claude model requested → go straight to Anthropic.
    Anything else → Ollama first, Claude fallback only on failure.
    """
    if _is_claude_model(model):
        return call_anthropic(messages, max_tokens)

    # Ollama-first path
    try:
        return call_ollama(messages, model, max_tokens)
    except Exception as e:
        print(f"[relay] Ollama failed ({e}), falling back to Claude...")
        try:
            return call_anthropic(messages, max_tokens)
        except Exception as e2:
            raise HTTPException(503, detail=f"Both backends failed. Ollama: {e} | Claude: {e2}")


@app.get("/health")
def health():
    anthropic_ok = bool(ANTHROPIC_API_KEY)
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=2)
        ollama_ok = True
    except Exception:
        ollama_ok = False
    return {
        "status": "ok",
        "routing": "ollama-first (claude only when model=claude-*)",
        "anthropic": "ready" if anthropic_ok else "no key",
        "ollama": "ready" if ollama_ok else "offline",
        "default_model": OLLAMA_DEFAULT_MODEL,
        "claude_model": CLAUDE_MODEL,
    }


@app.post("/relay")
def relay(req: RelayRequest):
    if req.brief:
        prompt = (
            f"{req.brief}\n\n---\n"
            f"Original task: {req.task}\n\n"
            f"Proof for accuracy, sharpen the language, deliver the final polished result. "
            f"Output only the final answer — no preamble, no meta-commentary."
        )
    else:
        prompt = req.task
    text, backend = route([{"role": "user", "content": prompt}])
    return {"result": text, "backend": backend}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": OLLAMA_DEFAULT_MODEL, "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": "qwen2.5-coder:7b", "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": "llama3.2:3b", "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": "phi4:latest", "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": "gemma3:12b", "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": "deepseek-r1:7b", "object": "model", "created": 1700000000, "owned_by": "ollama"},
            {"id": CLAUDE_MODEL, "object": "model", "created": 1700000000, "owned_by": "anthropic"},
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    max_tok = req.max_tokens or 2048

    text, backend = route(messages, model=req.model, max_tokens=max_tok)

    now = int(time.time())
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if req.stream:
        def event_stream():
            chunk = {
                "id": cid, "object": "chat.completion.chunk", "created": now,
                "model": backend,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            done = {
                "id": cid, "object": "chat.completion.chunk", "created": now, "model": backend,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {
        "id": cid, "object": "chat.completion", "created": now,
        "model": backend,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

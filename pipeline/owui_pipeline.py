"""
owui_pipeline.py — Open WebUI filter pipeline.
Auto-routes heavy requests through Ollama->Claude relay.
Light requests pass through unchanged.
"""
from typing import List, Optional
from pydantic import BaseModel
import requests

OLLAMA_URL = "http://ollama:11434/api/generate"
RELAY_URL = "http://host.docker.internal:7777/relay"
OLLAMA_MODEL = "qwen2.5:14b"

HEAVY_KEYWORDS = {
    "analyze", "draft", "proposal", "summarize", "review",
    "outreach", "assessment", "leads", "research", "report",
    "write a", "create a", "build a", "generate a",
}

COMPRESSION_SYSTEM = (
    "You are a context compressor. Analyze the user's request and produce a structured brief.\n"
    "Output EXACTLY:\n"
    "TASK: [one sentence]\n"
    "KEY FACTS:\n- [fact]\nDRAFT: [your best answer]\nCONSTRAINTS: [format/tone requirements]"
)


class Pipeline:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.name = "Ollama->Claude Router"
        self.valves = self.Valves()

    def _is_heavy(self, message: str, files: list) -> bool:
        if files:
            return True
        if len(message.split()) > 100:
            return True
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in HEAVY_KEYWORDS)

    def _get_last_user_message(self, messages: List[dict]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    return " ".join(
                        part.get("text", "") for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                return str(content)
        return ""

    def inlet(self, body: dict, user: Optional[dict] = None) -> dict:
        messages = body.get("messages", [])
        files = body.get("files", [])
        last_message = self._get_last_user_message(messages)

        if not last_message or not self._is_heavy(last_message, files):
            return body

        try:
            ollama_resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "system": COMPRESSION_SYSTEM,
                    "prompt": last_message,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 8192},
                },
                timeout=90,
            )
            ollama_resp.raise_for_status()
            brief = ollama_resp.json().get("response", "").strip()

            relay_resp = requests.post(
                RELAY_URL,
                json={"task": last_message, "brief": brief},
                timeout=180,
            )
            relay_resp.raise_for_status()
            final = relay_resp.json().get("result", "")

            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i]["content"] = (
                        f"[Routed through Ollama->Claude pipeline]\n\n{last_message}"
                    )
                    break

            messages.append({"role": "assistant", "content": final})
            messages.append({"role": "user", "content": "Please output your previous response exactly as-is."})
            body["messages"] = messages

        except Exception as e:
            print(f"[owui_pipeline] Error: {e} — passing through unchanged")

        return body

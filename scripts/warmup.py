"""warmup.py — pre-load key models into GPU VRAM.
Run at startup or manually: python warmup.py
"""
import time
import requests

OLLAMA = "http://localhost:11434/api/generate"

# Models to keep warm — ordered by priority
MODELS = [
    ("deepseek-r1:7b", "Say OK"),   # compression engine
    ("llama3.2:3b", "Say OK"),      # fast routing decisions
]

def warmup(model: str, prompt: str) -> str:
    t0 = time.time()
    try:
        r = requests.post(
            OLLAMA,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=300,
        )
        r.raise_for_status()
        elapsed = time.time() - t0
        tok = r.json().get("eval_count", 0)
        speed = tok / max(elapsed, 0.1)
        return f"{model}: loaded in {elapsed:.0f}s ({tok} tok @ {speed:.0f} tok/s)"
    except Exception as e:
        return f"{model}: FAILED — {e}"


def loaded_models() -> list:
    try:
        r = requests.get("http://localhost:11434/api/ps", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


if __name__ == "__main__":
    print("Warming up Ollama models...")
    hot = loaded_models()
    for model, prompt in MODELS:
        if model in hot:
            print(f"  {model}: already in VRAM — skipping")
        else:
            print(f"  loading {model}...", end="", flush=True)
            result = warmup(model, prompt)
            print(f"\r  {result}")
    print("Done. VRAM state:")
    for m in loaded_models():
        print(f"  - {m}")

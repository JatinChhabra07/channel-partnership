"""Self-hosted mem0 for the channel-partnership brain. No API key, no cloud, no telemetry.

  embeddings : FastEmbed (ONNX, CPU) BAAI/bge-small-en-v1.5, 384 dims, ~100 MB RAM
  vectors    : Qdrant embedded on disk at ~/.channel-partnership/mem0/qdrant (no server, no Docker)
  LLM        : none. Everything is stored with infer=False; Claude does the extraction/curation itself.

The SAME file is vendored into the claude-code-mem0 plugin (hooks/localmem.py) so the hooks and brain.py
share one store. Keep the two copies identical (the plugin's tests check this).

Qdrant embedded allows one process at a time; open() retries briefly and returns None if the store stays
busy, so callers degrade to the local ledger instead of failing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("MEM0_TELEMETRY", "False")  # mem0 OSS phones home to PostHog by default
os.environ.setdefault("POSTHOG_DISABLED", "1")

HOME = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
STORE = Path(os.environ.get("MEM0_LOCAL_DIR", HOME / "mem0"))
# FastEmbed defaults to /tmp, which is wiped on reboot (130 MB re-download + hook timeouts). Keep it with the brain.
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(STORE / "models"))
DEFAULT = {
    "vector_store": {"provider": "qdrant", "config": {"path": str(STORE / "qdrant"), "collection_name": "brain",
                                                      "embedding_model_dims": 384, "on_disk": True}},
    "embedder": {"provider": "fastembed", "config": {"model": "BAAI/bge-small-en-v1.5"}},
    # mem0 constructs an LLM client at init even when infer=False; it is never called. Placeholder only.
    "llm": {"provider": "openai", "config": {"api_key": "local-unused", "model": "unused"}},
    "history_db_path": str(STORE / "history.db"),
}
USER_ID = os.environ.get("MEM0_USER_ID") or "channel-partnership"


def config() -> dict:
    f = STORE / "config.json"
    if f.exists():
        return json.loads(f.read_text())
    STORE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(DEFAULT, indent=2))
    return DEFAULT


def _close(mem) -> None:
    """Release the Qdrant lock now, not in __del__ at interpreter shutdown (which errors noisily)."""
    try:
        mem.vector_store.client.close()
    except Exception:  # noqa: BLE001
        pass


def open_memory(wait_s: float = 6.0):
    """Return a mem0 Memory bound to the local store, or None if unavailable/busy."""
    import atexit
    import logging

    for name in ("mem0", "mem0.memory", "mem0.memory.main", "httpx", "qdrant_client"):
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        from mem0 import Memory
    except ImportError:
        return None
    deadline = time.time() + wait_s
    while True:
        try:
            mem = Memory.from_config(config())
            atexit.register(_close, mem)
            return mem
        except Exception as e:  # noqa: BLE001
            if "already accessed" in str(e) and time.time() < deadline:
                time.sleep(0.4)
                continue
            return None

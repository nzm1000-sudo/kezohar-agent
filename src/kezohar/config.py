"""Config: read settings from .env without printing secrets."""
import os
from pathlib import Path

DEFAULTS = {
    "LLM_BASE_URL": "",
    "LLM_MODEL": "qwen/qwen3.5-35b-a3b",
    "AGENT_PORT": "8710",
    "QDRANT_URL": "",
    "DEFAULT_LAT": "31.4227",
    "DEFAULT_LON": "34.5966",
    "DEFAULT_LOCATION": "נתיבות",
}

def _load_dotenv(root=None):
    p = Path(root) if root else Path.cwd()
    env_file = p / ".env"
    if not env_file.exists():
        # also try package root (repo root)
        for parent in [Path(__file__).resolve().parent.parent.parent, Path.home() / "kezohar-agent"]:
            cand = parent / ".env"
            if cand.exists():
                env_file = cand
                break
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

_load_dotenv()

def get(key, default=None):
    if key in DEFAULTS and default is None:
        default = DEFAULTS[key]
    return os.environ.get(key, default)

def llm_base_url():
    return (os.environ.get("LLM_BASE_URL", "") or "").rstrip("/")

def llm_model():
    return os.environ.get("LLM_MODEL", DEFAULTS["LLM_MODEL"])

def agent_port():
    try:
        return int(os.environ.get("AGENT_PORT", "8710"))
    except ValueError:
        return 8710

def has_llm():
    return bool(llm_base_url())

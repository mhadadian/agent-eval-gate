"""All knobs in one place. Every value has a code default and can be overridden in .env
(or the shell environment, which wins over .env). See .env.example."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# --- judge ---
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-fable-5-1")
JUDGE_FALLBACKS = _bool("JUDGE_FALLBACKS", True)               # server-side refusal fallback (Fable/Opus 5)
JUDGE_EFFORT = os.environ.get("JUDGE_EFFORT", "high")          # low | medium | high | xhigh | max
JUDGE_MAX_TOKENS = int(os.environ.get("JUDGE_MAX_TOKENS", "16000"))
JUDGE_PROMPT_VERSION = os.environ.get("JUDGE_PROMPT_VERSION", "p1")   # part of the cache key
JUDGE_CACHE = ROOT / os.environ.get("JUDGE_CACHE", "judge_cache.json")
JUDGE_OFFLINE = _bool("JUDGE_OFFLINE", False)                  # same as --offline

# --- traces ---
BASELINE_VERSION = os.environ.get("BASELINE_VERSION", "v2.4")
CANDIDATE_VERSION = os.environ.get("CANDIDATE_VERSION", "v2.5")

# --- gate ---
GATE_VERDICT_DROP = int(os.environ.get("GATE_VERDICT_DROP", "2"))   # review verdict drop that counts as a regression
GATE_REQUIRE_JUDGE_AGREEMENT = _bool("GATE_REQUIRE_JUDGE_AGREEMENT", True)  # block if judge disagrees with human on TEST


def describe() -> str:
    return (f"judge={JUDGE_MODEL} effort={JUDGE_EFFORT} prompt={JUDGE_PROMPT_VERSION} fallbacks={JUDGE_FALLBACKS} "
            f"cache={JUDGE_CACHE.name} offline={JUDGE_OFFLINE} | "
            f"{BASELINE_VERSION} -> {CANDIDATE_VERSION} | "
            f"verdict_drop>={GATE_VERDICT_DROP} require_agreement={GATE_REQUIRE_JUDGE_AGREEMENT}")

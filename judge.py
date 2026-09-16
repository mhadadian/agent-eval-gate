"""LLM-as-judge via LangChain. Sees only what the agent saw and what it produced.
Never reads golden/.

One call per execution. Output mirrors the human label shape so the two can be
compared on the labelled executions, but the judge derives its own findings.
"""
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from settings import (JUDGE_CACHE as CACHE_PATH, JUDGE_EFFORT, JUDGE_FALLBACKS, JUDGE_MAX_TOKENS,
                      JUDGE_MODEL as MODEL, JUDGE_OFFLINE, JUDGE_PROMPT_VERSION as PROMPT_VERSION)

# Split of the six inputs. Tuning happens on TRAIN only; TEST is scored once, at the end.
TRAIN_INPUTS = {"superbet/user-service#201", "ALT-90412", "ALT-90418"}
TEST_INPUTS = {"superbet/odds-engine#312", "superbet/checkout-api#487", "superbet/user-service#214"}

# The severity scale and verdict rubric. Same definitions the human used, so
# verdicts are comparable. These are the rules of the game, not the answers.
RUBRIC = """Severity of a finding, decided from the INPUT alone:
- blocker: must fix before merge (for a PR) / the page-or-ticket decision itself (for an alert)
- major: should fix
- nit: optional
- question: cannot be settled from the input; a good agent asks rather than asserts

Review verdict (pr-review), 1 to 5:
5 = every blocker and major found at a sensible severity
4 = blockers found, a major missed
3 = a real issue found but a blocker missed, or a blocker found at the wrong severity
2 = only nits or majors found, blocker missed
1 = nothing real found

Classification verdict (incident-triage): correct | incorrect.
Judge the action against the whole alert, not the severity field alone."""

SYSTEM = f"""You are a senior engineer auditing an AI agent's output. You are given the exact
input the agent saw and the exact output it produced.

Step 1. From the INPUT alone, list what a competent engineer would find, with a severity
each. Do this before reading the agent's output closely, and do not let the output
steer what you consider real.
Step 2. For each of your findings, say whether the agent found it, and whether the
agent's stated severity or wording matches its real severity. A blocker presented as
optional ("consider ...") or at warning/info level is found at the wrong severity.
Step 3. List anything the agent said that the input contradicts, or that is not a real
issue but was presented as one.
Step 4. Give the verdict using the rubric.

Be concrete: cite line numbers from the diff or phrases from the alert.

{RUBRIC}"""


class Finding(BaseModel):
    severity: Literal["blocker", "major", "nit", "question"]
    item: str = Field(description="What the issue is, with line numbers or quoted phrases")
    agent_found: bool = Field(description="Did the agent's output identify this issue")
    agent_severity_ok: bool = Field(description="If found, was it presented at a fitting severity")


class Judgement(BaseModel):
    findings: list[Finding]
    agent_wrong: list[str] = Field(description="Claims the input contradicts, or non-issues presented as issues")
    review_verdict: int | None = Field(description="1-5 for pr-review, null otherwise", ge=1, le=5)
    classification_verdict: Literal["correct", "incorrect"] | None = Field(
        description="for incident-triage, null otherwise")
    rationale: str


def _user_message(graph_id: str, node: dict) -> str:
    kind = "pull request diff" if graph_id == "pr-review" else "alert"
    tail = ("Set classification_verdict to null." if graph_id == "pr-review"
            else "Set review_verdict to null.")
    return (
        f"Graph: {graph_id}\n\n"
        f"INPUT the agent saw ({kind}):\n{json.dumps(node['input'], indent=2)}\n\n"
        f"OUTPUT the agent produced:\n{json.dumps(node['output'], indent=2)}\n\n{tail}"
    )


def _cache_key(graph_id: str, node: dict) -> str:
    blob = json.dumps([PROMPT_VERSION, MODEL, JUDGE_EFFORT, graph_id, node["input"], node["output"]], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _load_cache() -> dict:
    return json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}


def judge(execution: dict, node: dict, offline: bool = False) -> dict:
    """Return the judge's verdict for one execution. Cached by content, not by id."""
    cache = _load_cache()
    key = _cache_key(execution["graph_id"], node)
    if key in cache:
        return cache[key]
    if offline or JUDGE_OFFLINE:
        raise SystemExit(f"{execution['execution_id']}: not in judge cache and --offline set")

    from langchain_anthropic import ChatAnthropic  # lazy so the offline path needs no key

    extra = {}
    if JUDGE_FALLBACKS:  # on a safety refusal, the API re-runs on a fallback model in the same call
        extra = {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}}
    llm = ChatAnthropic(model=MODEL, max_tokens=JUDGE_MAX_TOKENS, output_config={"effort": JUDGE_EFFORT}, **extra)
    structured = llm.with_structured_output(Judgement, method="json_schema")
    messages = [("system", SYSTEM), ("human", _user_message(execution["graph_id"], node))]
    need = "review_verdict" if execution["graph_id"] == "pr-review" else "classification_verdict"
    for attempt in range(2):  # the schema allows null for the other graph's field; the needed one must be set
        result: Judgement = structured.invoke(messages)
        if getattr(result, need) is not None:
            break
    else:
        raise SystemExit(f"{execution['execution_id']}: judge returned no {need} after 2 attempts")
    out = result.model_dump()
    out["_meta"] = {"execution_id": execution["execution_id"], "model": MODEL,
                    "prompt_version": PROMPT_VERSION, "effort": JUDGE_EFFORT, "key": key}
    cache[key] = out
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    return out

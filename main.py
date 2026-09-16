"""Agent evaluation gate. Exit non-zero if the candidate model version should be blocked.

Pipeline: pair executions -> judge each (LLM, never sees golden/) -> validate the judge
against the human labels on the held-out TEST inputs -> compare pairs -> gate.
"""
import argparse
import json
import sys

import settings
from judge import TEST_INPUTS, TRAIN_INPUTS, judge
from settings import BASELINE_VERSION as BASELINE, CANDIDATE_VERSION as CANDIDATE, GATE_VERDICT_DROP, ROOT


# ---------- pairing ----------

def load_traces(version: str) -> list[dict]:
    return json.loads((ROOT / "traces" / f"batch-{version}.json").read_text())


def llm_node(execution: dict) -> dict:
    """The node under evaluation. There is exactly one LLM node per execution."""
    nodes = [n for n in execution["nodes"] if n["type"] == "llm"]
    assert len(nodes) == 1, f"{execution['execution_id']}: expected 1 llm node, got {len(nodes)}"
    return nodes[0]


def input_name(execution: dict) -> str:
    first = execution["nodes"][0]["input"]
    return first.get("alert_id") or f"{first['repo']}#{first['pr']}"


def input_key(execution: dict) -> str:
    """Identity of the replayed input: the graph plus the first node's input.
    Not the execution_id: the exec-00N / exec-10N numbering is a coincidence."""
    return execution["graph_id"] + ":" + json.dumps(execution["nodes"][0]["input"], sort_keys=True)


def pair_executions(baseline: list[dict], candidate: list[dict]) -> list[tuple[dict, dict]]:
    """1:1 match on input. Fails on unpaired executions or on pairs whose LLM node saw
    different input, because then the comparison is not apples to apples."""
    by_key = {input_key(e): e for e in candidate}
    assert len(by_key) == len(candidate), "duplicate inputs in candidate batch"
    pairs, unmatched = [], []
    for b in baseline:
        c = by_key.pop(input_key(b), None)
        if c is None:
            unmatched.append(b["execution_id"])
            continue
        assert llm_node(b)["input"] == llm_node(c)["input"], (
            f"{b['execution_id']} vs {c['execution_id']}: LLM node saw different input")
        pairs.append((b, c))
    if unmatched or by_key:
        sys.exit(f"unpaired executions: baseline={unmatched} "
                 f"candidate={[e['execution_id'] for e in by_key.values()]}")
    return pairs


# ---------- reading a judgement / a human label the same way ----------

def j_verdict(j: dict, graph_id: str):
    return j["review_verdict"] if graph_id == "pr-review" else j["classification_verdict"]


def j_blocker_found(j: dict) -> bool:
    return any(f["severity"] == "blocker" and f["agent_found"] for f in j["findings"])


def j_blocker_ok(j: dict) -> bool:
    return any(f["severity"] == "blocker" and f["agent_found"] and f["agent_severity_ok"]
               for f in j["findings"])


def h_blocker_found(label: dict) -> bool:
    """Human: the blocker counts as found if it or any alias (same_defect_as) is in agent_got_right."""
    gts = {g["id"]: g for g in label["ground_truth"]}
    blockers = {gid for gid, g in gts.items() if g["severity"] == "blocker"}
    aliases = {gid for gid, g in gts.items() if g.get("same_defect_as") in blockers}
    return bool((blockers | aliases) & set(label["agent_got_right"]))


def verdicts_agree(judge_v, human_v, graph_id: str) -> bool:
    if graph_id == "pr-review":
        return judge_v is not None and abs(int(judge_v) - int(human_v)) <= 1
    return judge_v == human_v


# ---------- validation of the judge against the human labels ----------

def validate(split: str, inputs: set, executions: list, judgements: dict, labels: dict) -> list[str]:
    """Compare judge to human on labelled executions of one split. Returns failure reasons."""
    print(f"\n== judge vs human, {split} split ==")
    print(f"{'exec':9} {'input':28} {'human':9} {'judge':9} {'blocker found h/j':18} ok")
    failures = []
    for e in executions:
        name, lab = input_name(e), labels.get(e["execution_id"])
        if name not in inputs or lab is None:
            continue
        j, g = judgements[e["execution_id"]], e["graph_id"]
        hv, jv = lab["verdict"], j_verdict(j, g)
        hb, jb = h_blocker_found(lab), j_blocker_found(j)
        ok = verdicts_agree(jv, hv, g) and hb == jb
        print(f"{e['execution_id']:9} {name:28} {str(hv):9} {str(jv):9} {str(hb):8}/{str(jb):9} {'yes' if ok else 'NO'}")
        if not ok:
            failures.append(f"{split}: judge disagrees with human on {e['execution_id']} "
                            f"(human verdict {hv}, judge {jv}; blocker found human={hb} judge={jb})")
    return failures


# ---------- pairwise comparison and gate ----------

def compare(pairs: list, judgements: dict) -> tuple[list[str], list[str]]:
    print(f"\n== {BASELINE} -> {CANDIDATE}, judged ==")
    print(f"{'input':28} {BASELINE:>6} {CANDIDATE:>6}  change")
    regressions, improvements = [], []
    for b, c in pairs:
        g, name = b["graph_id"], input_name(b)
        jb, jc = judgements[b["execution_id"]], judgements[c["execution_id"]]
        vb, vc = j_verdict(jb, g), j_verdict(jc, g)
        note = ""
        if g == "pr-review":
            if j_blocker_found(jb) and not j_blocker_found(jc):
                note = "REGRESSION: blocker found by baseline, missed by candidate"
            elif int(vc) <= int(vb) - GATE_VERDICT_DROP:
                note = f"REGRESSION: verdict dropped {vb} -> {vc}"
            elif not j_blocker_found(jb) and j_blocker_found(jc):
                note = "improvement: candidate finds a blocker baseline missed"
            elif int(vc) > int(vb):
                note = f"improvement: verdict {vb} -> {vc}"
        else:
            if vb == "correct" and vc == "incorrect":
                note = "REGRESSION: classification flipped correct -> incorrect"
            elif vb == "incorrect" and vc == "correct":
                note = "improvement: classification fixed"
        print(f"{name:28} {str(vb):>6} {str(vc):>6}  {note}")
        (regressions if note.startswith("REGRESSION") else improvements if note else []).append(f"{name}: {note}")
    return regressions, improvements


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use judge_cache.json only; no API calls")
    ap.add_argument("--show-train", action="store_true", help="also print train-split agreement (tuning aid)")
    args = ap.parse_args()

    pairs = pair_executions(load_traces(BASELINE), load_traces(CANDIDATE))
    executions = [e for pair in pairs for e in pair]
    print(settings.describe())
    judgements = {e["execution_id"]: judge(e, llm_node(e), offline=args.offline) for e in executions}

    # Golden labels are read here and only here: to check the judge, never to feed it.
    labels = {l["execution_id"]: l for l in json.loads((ROOT / "golden" / "labels.json").read_text())["labels"]}
    if args.show_train:
        validate("train", TRAIN_INPUTS, executions, judgements, labels)
    reasons = validate("test", TEST_INPUTS, executions, judgements, labels)
    if not settings.GATE_REQUIRE_JUDGE_AGREEMENT:
        reasons = []  # reported above, but not enforced

    regressions, improvements = compare(pairs, judgements)
    reasons += regressions

    print("\n== verdict ==")
    for r in improvements:
        print(f"  + {r}")
    if reasons:
        print(f"BLOCK {CANDIDATE}:")
        for r in reasons:
            print(f"  - {r}")
        return 1
    print(f"PASS: no regressions {BASELINE} -> {CANDIDATE}, judge agrees with human on held-out labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())

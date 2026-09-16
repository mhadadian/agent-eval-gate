# DECISIONS

Running notes. Newest at the bottom.

## 0. Reading the material (done first)

- Read SPEC.md, both trace files, golden/labels.json before writing anything.
- Traces: same six inputs (4 PRs, 2 alerts) through v2.4 and v2.5. No labels in traces.
- Labels: 7 of 12 executions, keyed by execution_id + node_id (always nodes[1], the LLM node).
- ground_truth is a property of the INPUT, not of the agent output. Every one of the six
  inputs has a ground_truth list from at least one labelled sibling, so the unlabelled
  five executions are missing only the per-execution scoring, not the ground truth.
- Three unrelated "severity" fields exist: alert severity (classifier input), comment
  severity (reviewer output, the agent's own claim), ground_truth severity (labeller,
  authoritative). Only the last is trusted.
- Verdict type differs by graph: int 1-5 for pr-review, "correct"/"incorrect" for triage.

## 1. Pairing executions across versions (main.py)

- Pair key = graph_id + nodes[0].input (repo+pr or alert_id), i.e. the replayed input.
  Rejected execution_id offset (exec-00N -> exec-10N): coincidence of numbering.
- Assert the LLM node's input is identical across the pair; otherwise not apples to apples.
- Fail the run on any unpaired or duplicate execution. Result: six clean pairs.

## 2. No golden leakage into the comparison (user direction)

- The judge sees only what the agent saw (nodes[1].input) and what it produced (nodes[1].output),
  plus the rubric. It never sees golden/labels.json.
- Rejected: feeding the labeller's ground_truth for an input to the judge. It would not run on
  next month's fresh inputs, and it would make the 7 labels useless as an independent check.
- Golden is used for exactly one thing: validating the judge. Judge verdicts on the 7 labelled
  executions are compared with the human's; poor agreement fails the run. Not used as few-shot.
- Label coverage: only 1 of 6 pairs is labelled on both sides (PR 201, the pair where v2.5
  improved). The two suspected regressions (PR 312, PR 214) and the hard triage case for v2.5
  (exec-104) are unlabelled on the side that matters, so the judge has to carry the decision.

## 3. Judge architecture (judge.py, main.py) - built, not yet run

- Stack: Python, LangChain (`langchain-anthropic`), key from `.env` via python-dotenv (user direction).
  Deps in pyproject.toml; run.sh uses uv if present, else venv+pip, so a clean checkout works.
- Judge input: nodes[1].input + nodes[1].output + the rubric text. The rubric is the *definition*
  of the severity scale and verdict scale from labels._schema, not any label. Needed so judge
  verdicts are on the same scale as the human's.
- Judge output (structured, pydantic): its own findings with severity, agent_found,
  agent_severity_ok; agent_wrong; verdict. Same shape as a human label so the two compare.
- Prompt asks for findings from the input BEFORE reading the output, to reduce anchoring on
  what the agent said.
- Split (user direction): TRAIN = user-service#201, ALT-90412, ALT-90418 (4 labelled executions,
  used to tune the prompt). TEST = odds-engine#312, checkout-api#487, user-service#214
  (3 labelled executions, scored once at the end, the headline). Test verdicts are 1, 5, 2, so
  the held-out set covers the low end the judge must get right.
- Agreement metric: verdict within 1 for reviews / exact for triage, AND blocker-found
  (human: blocker id or same_defect_as alias in agent_got_right; judge: a blocker finding with
  agent_found). Blocker-found is what drives the gate, so it must agree.
- Cache: judge_cache.json keyed by sha(prompt_version, model, input, output). Committed, so
  `run.sh --offline` is deterministic and the walkthrough needs no API. Changing the prompt
  or a trace invalidates only the affected entries.
- Model: claude-opus-5 proposed (current default per API reference). Adaptive thinking is
  on by default; no effort override for now.

## 4. Gate rule (main.py compare) - proposed

- Per pair, from judge verdicts: REGRESSION if baseline found the blocker and candidate did
  not; or review verdict dropped by 2+; or triage flipped correct -> incorrect.
- Block if any regression, OR if the judge disagrees with the human on any held-out TEST
  label (an untrusted judge must not pass an upgrade).
- Rejected: averaging verdicts. One PR going 5 -> 1 must not be hidden by another going 3 -> 5.

## 5. Settings in .env for rapid experimentation (settings.py)

- Every knob is an env var with a code default: JUDGE_MODEL, JUDGE_EFFORT, JUDGE_MAX_TOKENS,
  JUDGE_PROMPT_VERSION, JUDGE_CACHE, JUDGE_OFFLINE, BASELINE_VERSION, CANDIDATE_VERSION,
  GATE_VERDICT_DROP, GATE_REQUIRE_JUDGE_AGREEMENT. Shell env wins over .env.
- Model and effort are part of the cache key, so switching them re-judges instead of
  reusing stale results. .env.example is committed; .env is not.
- Rejected: a YAML/JSON config file. One more file to explain, and .env already exists.

## Pending approval (critical)

- Model claude-opus-5 and the first live run (12 calls).
- Gate rule as in 4.
- Note: .env currently fails to parse (unmatched quote). Shell env carries the key for now.

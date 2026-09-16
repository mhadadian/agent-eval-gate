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

## 6. First live run (approved: judge = claude-fable-5-1, effort high)

Result: `./run.sh` exits 1. BLOCK v2.5. 12 calls, ~27 s, cache committed so `./run.sh --offline`
reproduces it with no API.

| input                | v2.4      | v2.5      | judged change                                  |
|----------------------|-----------|-----------|------------------------------------------------|
| odds-engine#312      | 4         | 1         | REGRESSION verdict 4 -> 1 (v2.5: "no issues")  |
| checkout-api#487     | 3         | 1         | REGRESSION blocker (TOCTOU race) lost          |
| ALT-90412            | correct   | correct   |                                                |
| ALT-90418            | incorrect | correct   | improvement: canary now ticketed, not paged    |
| user-service#201     | 4         | 5         | improvement                                    |
| user-service#214     | 5         | 2         | REGRESSION blocker (SQL injection) lost        |

Answer for this upgrade: v2.5 hurt. It fixed the one triage mistake and one review, and lost
the blocker on three of four PRs, including a SQL injection. Do not ship.

Judge vs human: train 3/4, test 2/3. The two disagreements:
- exec-005 (train): judge rates the unbounded sessions map as major, human as blocker. Verdict 4
  vs 3, within 1, but blocker-found differs. Severity calibration, not a missed finding.
  Not tuned away: doing so would mean writing the answer into the prompt.
- exec-002 (test): judge 3 vs human 5. The judge found a second blocker the human did not list:
  `r.inflight[payment.ID] = true` at line 49 is never cleared, so after one retry the payment is
  permanently ErrAlreadyInflight. I checked the diff and agree with the judge. **I disagree with
  the human label here** (allowed by labels._about; label left unedited). If the labeller agrees,
  the test agreement becomes 3/3 and the only remaining block reasons are the three regressions.

Bugs fixed during the run:
- exec-101 first came back with review_verdict null and rationale "placeholder". The schema
  allows null (the other graph's field). judge.py now retries once and fails loudly; main.py
  treats a missing verdict as a block reason rather than crashing.

Unsure / would do next with more time:
- Severity calibration between judge and labeller (blocker vs major) is the weakest link. A
  second labeller, or a written severity guide for "unbounded growth" style defects, would settle it.
- Judge non-determinism: one run. Run 3x and gate on the majority verdict.
- Latency/tokens are in the traces and unused. Cheap to add as a secondary signal.
- The judge saw both versions' outputs in separate calls; a pairwise "which is better" call
  would be a useful cross-check but is a different (comparative) rubric.

## Order of work and why
1. Read everything, map the label coverage (found that human labels alone would say "helped").
2. Pairing on input identity, asserted equal LLM input (apples to apples).
3. No-leakage judge with a train/test split, so it runs on next month's fresh inputs.
4. Gate rule on per-pair regressions, not averages.
5. run.sh, cache, .env knobs. Then the live run.

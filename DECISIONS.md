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

## Pending approval (critical)

See conversation. Not acted on yet.

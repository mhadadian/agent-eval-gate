# Agent Evaluation Gate — Coding Exercise

You have 45 minutes. You won't finish everything; say in DECISIONS.md what you did first and why. Use whatever AI tooling you like; how you use it is part of what we assess.

## The problem

Our agent orchestrator runs multi-step workflows in production. Some steps are tool calls (GitHub, PagerDuty, Jira). Some are LLM agents: a code reviewer and an incident classifier. Nothing today evaluates what those agents produce.

At 10:00 today the model behind both agents was upgraded from v2.4 to v2.5, and the last six production inputs were replayed through it. Nobody can say whether it helped or hurt. The next upgrade is in two weeks.

Tell us the answer for this upgrade, and give us something CI can run before the next one.

## What you're given

- `traces/batch-v2.4.json` and `traces/batch-v2.5.json`: the same six inputs, four pull requests and two alerts, through each version. Every node's input, output, and latency; LLM nodes also record token counts. The classifier emits `page` or `ticket`.
- `golden/labels.json`: seven of those twelve executions, reviewed by a senior engineer. One engineer's opinion. Do not edit them. You may add labels of your own, marked as yours.
- `ANTHROPIC_API_KEY` in your environment.

## The one requirement

`run.sh` exits non-zero if you would block this upgrade, and prints why. How you get there is yours to decide.

## Deliver

```
├── DECISIONS.md   # running notes as you go: what you chose, what you rejected, what you are unsure of
├── traces/        # provided — do not modify
├── golden/        # provided — add labels if you want, do not change existing ones
├── <your code>    # any layout, any language, any tools
└── run.sh         # works on a clean checkout with ANTHROPIC_API_KEY set
```

Commit as you go.

At the end you walk us through it, then we change something and watch what moves. After that the team reviews the repo without you in the room.

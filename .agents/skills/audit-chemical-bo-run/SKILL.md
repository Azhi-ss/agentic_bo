---
name: audit-chemical-bo-run
description: "Start new provider-backed autonomous BO campaigns for Buchwald-Hartwig sub4 and Suzuki, submit new simulated chemical experiments, and audit the Agent's live actions over a small observation window."
disable-model-invocation: true
---

# Audit Chemical BO Run

Start new label-free Campaigns, call the configured model, submit new simulated chemical experiments through the real Supervisor/Oracle path, and judge the Agent's actions while they execute. This is a live online simulation and operator audit, not a benchmark claim.

## Defaults

- Targets: `buchwald_sub4`, then `suzuki`; run sequentially, never concurrently.
- Seeds: Buchwald `1600`; Suzuki `100` unless the user supplies seeds.
- Campaign budget: `40`; audit window: `6` completed Campaign observations per target.
- Runtime: model `gpt-5.6-sol`, thinking `xhigh`, policy `autonomous_agent`.
- Output: a fresh timestamped directory with at least seconds precision under `runs/action-audit/<target>/`. Never reuse or overwrite a competition Campaign.
- A valid run MUST create a new Campaign, start the provider-backed model, and produce new signed Receipts/verified Observations. Historical trajectory replay does not satisfy this skill.

## 1. Preflight

1. Confirm `.venv/bin/boagent` exists and the two datasets contain public inputs.
2. Do not print credentials. Provider startup is sufficient credential validation.
3. Read `supervisor/campaign.mjs` tool descriptions and `autonomousSystemPrompt` if they changed since the last audit.
4. Create a UTC timestamp and exact output paths. Show them before provider startup.

Dataset roots:

- `datasets/chemical_reactions/buchwald_sub4`
- `datasets/chemical_reactions/suzuki`

## 2. Initialize One Campaign

Use the real budget even though this audit may stop early:

```bash
.venv/bin/boagent init \
  --dataset-root <dataset-root> \
  --output <fresh-output> \
  --seed <seed> \
  --budget 40 \
  --target Yield \
  --direction maximize
```

Initialization must succeed before starting the provider process. Confirm the new Campaign's `manifest.json` identifies the requested seed and budget and its initial `trajectory.json` has no completed rows.
`boagent init` rejects an existing output path; choose a new timestamp rather than deleting or reusing a Campaign.

## 3. Start the Live Model and Observe New Experiments

Start the run as a managed long-running process with `hub start`, not a background shell:

```text
application: .venv/bin/boagent
args: [run, --campaign, <fresh-output>, --model, gpt-5.6-sol, --thinking, xhigh, --policy, autonomous_agent]
```
Provider startup and at least one newly completed signed Observation are mandatory. Do not substitute an existing `runs/competition/**/trajectory.json`, copied Campaign, offline replay, synthetic report, or analysis-only simulation. If provider access fails before a new Observation is completed, report the live-run failure rather than returning a replay audit.

Use a unique process name per target. Follow logs for provider and submission failures. Audit only rows newly written by this invocation to `<fresh-output>/trajectory.json`; a completed experiment row has `decision`, `trial_id`, `receipt_id`, and `metrics`.
Skip Decision Evidence evaluation for rows with `provenance: "recovered"`; the Supervisor reconstructed them from Frame/Receipt state and they have no agent-authored rationale to audit.

After each new completed row, inspect:

- chosen exact Candidate and observed `Yield`;
- hypothesis, expected outcome/learning, decision goal, result use, and follow-up branches;
- surrogate trust/search mode versus diagnostics and verified observations;
- `actual_tool_use.calls` and `surrogate_relationship` consistency;
- whether an override compares the relevant exact alternatives with `score` and/or `predict` for the question being asked;
- whether the next decision explicitly changes belief or ranking after the Observation;
- repeated action factors or query sequences without new evidence or incumbent improvement.

Read the corresponding `pi-session.jsonl` slice only when the trajectory omits evidence needed to judge the action. Never read `test.csv`, hidden optimums, or label-derived benchmark statistics during the run.

## 4. Verdict Per Step

Use exactly one verdict:

- **allow** — evidence supports the action; tool semantics and result-use contract are coherent.
- **challenge** — action may be reasonable, but comparison, falsifier, observation update, or learning payoff is insufficient.
- **reject** — deterministic violation: hidden-label use, fabricated Observation, prediction treated as measurement, invalid Candidate identity, or decision contradicting successful tool evidence.

Observed Yield may judge whether the next action updated correctly; it must not be used to retroactively call a previously defensible action bad.

## 5. Stop or Continue

Stop the managed process when any condition holds:

- the audit window is complete;
- a `reject` occurs;
- repeated `challenge` actions provide enough evidence of one systematic failure;
- the provider pauses/errors and retry evidence is captured;
- the user asks to stop or extend.

Stop the process with `hub stop`. The `autonomous_agent` policy has no `stop_campaign` tool, so manual interruption cannot produce a verified stop record: the Campaign is interrupted, not completed. On resume, `.venv/bin/boagent run --campaign <campaign> --policy autonomous_agent` reconciles any pending trial automatically. Do not edit `campaign-status.json`.

Then run the second target using a fresh process and output path.
The second target is also mandatory unless its live provider run fails. Existing historical results cannot replace it.

## 6. Report

Return one compact table per target:

| Step | Yield | Candidate change | Tool calls | Trust / mode | Verdict | Evidence |
|---|---:|---|---|---|---|---|

Finish with:

- Campaign paths and seeds;
- completed and pending counts;
- incumbent progression from verified observations;
- repeated tool/action patterns;
- stop reason and provider failures;
- whether the action policy is satisfactory, needs prompt/tool-description changes, or needs runtime enforcement.

Do not claim general improvement from these short runs. Recommend multi-seed paired evaluation for performance conclusions.

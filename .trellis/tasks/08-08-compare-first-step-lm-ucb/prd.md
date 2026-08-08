# Compare first-step LM and UCB policies

## Goal

Determine whether the current low-trust opening policy (`cv_r2 < 0.2` → `UCB(beta=16)` → preferred GP suggestion) suppresses useful LLM chemistry proposals, using a small reproducible multi-seed experiment that inspects the first one or two decisions rather than running full 40-step campaigns.

## Background

- The completed Suzuki seed-300 run began with 29 historical observations, `train_r2=0.9999278`, `cv_r2=-0.3246967`, a train/CV gap of `1.3246245`, and a boundary lengthscale.
- `supervisor/supervisor.mjs:138-143` automatically switches a zero-observation low-trust campaign to `UCB(beta=16)` before the LLM acts.
- `profiles/paper-reproduction/PAPER_SYSTEM.md:54-56` instructs the LLM to commit `preferred_suggestion` by default and calls UCB the mandatory low-trust policy.
- The seed-300 LLM stated a chemistry-prior configuration, but it matched the UCB rank-1 candidate; all 40 commitments ultimately used acquisition rank 1.
- Campaign budget is configurable, so budget 1 or 2 campaigns can exercise the real Supervisor → LLM → lenz → Oracle path without adding a separate runner.
- Existing policy tests already prove that low-trust domain-prior overrides are allowed; they do not require the LLM to generate or compare an independent candidate.

## Requirements

- Use the Suzuki dataset and `gpt-5.6-sol` with the same provider and `xhigh` thinking configuration as the completed live run.
- Compare two arms over five matched seeds, with two verified evaluations per campaign:
  - Arm A — current behavior: low `cv_r2` selects `UCB(beta=16)` and the prompt defaults to the GP `preferred_suggestion`.
  - Arm B — low-trust comparison: the LLM must state an exact chemistry-prior candidate distinct from GP rank 1, resolve it to a public candidate, compare it against GP rank 1 with posterior/acquisition evidence, then freely choose either candidate.
- Use the same five seeds for both arms. Seed selection must be fixed before results are observed.
- If Arm B chooses GP rank 1 in all five first steps, add a diagnostic Arm C for the same five seeds whose first step is forced to the independent LLM candidate; this is a predeclared contingency, not a post-hoc success criterion.
- Preserve black-box integrity: hidden outcomes remain accessible only after commitment through Oracle receipts.
- Record for every run: initial diagnostics, explicit tool calls, GP preferred candidate, independent LLM candidate, chosen config and pool index, candidate source/evidence, acquisition rank and score, rationale, observed Yield, and the second-step response to the first verified result.
- Keep the policy variant selectable and isolated; do not replace or silently change the current default arm.
- Do not infer prompt superiority from one lucky Yield. Report action compliance and candidate diversity separately from observed optimization performance.

## Acceptance Criteria

- [x] Five matched seeds completed for Arm A and Arm B, each with exactly two verified receipts and an inspectable trajectory/session trace.
- [x] Arm B recorded a distinct scored chemistry candidate in every first step and failed closed if the evidence contract was not met.
- [x] All five Arm B first decisions selected GP rank 1, so the predeclared forced-LM Arm C ran for seeds 300–304.
- [x] The comparison reported action behavior, candidate diversity, tool usage, first/second Yield, two-step best, incumbent improvement, compliance, and hashes.
- [x] The report remained per-seed and descriptive; no statistical significance was claimed.
- [x] Existing default behavior remained available and focused Python/Node tests passed.

## Result and Interpretation

- Arm B produced a distinct scored chemistry-prior candidate in 5/5 runs, but selected GP rank 1 in 5/5 runs.
- The experiment therefore proved that requiring an alternative comparison does not remove the base prompt's GP-first decision anchor.
- Arm C showed that forced chemistry-prior Candidates can be strong but have high downside variance; these Candidates were fresh model outputs, not the exact rejected Arm B Candidates.
- `lm_compare` and `lm_forced_first` are diagnostic interventions, not the desired autonomous Agent policy.
- Follow-up design moved to a separate task: Sara owns tool selection and Commitment, Surrogate Advice is non-binding, candidate inspection is label-free, and no default GP-first rule applies.

## Out of Scope

- Full 40-step benchmarking.
- Claiming that one arm is generally superior across datasets.
- Selecting final production thresholds for a reliability LCB/hysteresis state machine.
- Using hidden labels, global-best knowledge, or benchmark GT during candidate selection.
- General-purpose free-form molecule generation outside the finite public candidate pool.

## Technical Notes

- Budget-2 campaigns already exercise the production Supervisor loop and stop naturally after two observations; no separate simulation loop is required.
- The existing score path resolves configs internally but does not expose `pool_index`; Arm B needs a minimal public-candidate identity resolution path so a scored LM config can be committed legally.
- The first-step historical diagnostics are expected to be identical across seeds for this dataset; seeds still control model initialization and are retained for matched stochastic runs.

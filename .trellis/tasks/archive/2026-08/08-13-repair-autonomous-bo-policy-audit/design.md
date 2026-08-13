# Competition-score policy audit design

## Scope

This branch implements a competition-specific autonomous policy for the existing budget-40 benchmark. It intentionally prioritizes early incumbent improvement, best-so-far AUC, T95 attainment, and final best over broad cross-context coverage.

The implementation remains label-free at runtime. `test.csv`, the global optimum, and the T95 threshold are unavailable to the Supervisor and agent. Competition metrics are used only for offline evaluation.

## First-principles objective

For the fixed benchmark score:

- final best contributes 40%;
- best-so-far AUC contributes 30%;
- reaching T95 contributes 20%;
- the initial observation contributes 10% and cannot be changed after step 1.

After step 1, useful behavior therefore has two properties:

1. raise the incumbent as early as possible;
2. preserve enough targeted exploration to find a better terminal region without spending long intervals on information that cannot be exploited within the remaining budget.

The policy must not force cross-context coverage for its own sake. Coverage is valuable only when it improves expected competition utility.

## Policy boundary

### Keep as hard validation

- exact public candidate identity;
- unobserved candidate;
- complete Decision Evidence Record;
- truthful current-step tool-use classification;
- valid enum/schema values;
- non-autonomous controlled evidence-label checks.

### Keep as advisory telemetry only

These signals remain in `policy_audit` for analysis but do not independently trigger a correction retry:

- `cross_context_uncovered`;
- `scope_overreach`;
- consecutive low-trust GP override streaks.

They previously delayed high-value candidates and cannot distinguish healthy exploitation from self-closing search by themselves.

### Competition challenge conditions

A corrective retry is justified only by a condition tied to remaining score opportunity:

1. **Unproductive repeated policy**: the same action/factor pattern repeats without incumbent improvement and the selected candidate is not the current best acquisition option or preferred candidate.
2. **Middle/late global exploration**: `global_exploration` after the early phase, because broad coverage has insufficient time to repay its budget cost.
3. **Terminal information waste**: an information-oriented action has no remaining follow-up action that can exploit its result.
4. **Late weak candidate**: in the terminal phase, a targeted/global exploration candidate is outside the current acquisition shortlist or materially below the shortlist best, unless the candidate is a clean one-factor comparison adjacent to the incumbent region and the stated result use names the next remaining action.
5. **Trusted-surrogate dissent**: only when surrogate trust is medium/high, the candidate is outside the shortlist, and the agent has not selected a concrete disagreement test. Low-trust GP override is not itself a challenge.

## Minimal evidence contract

Add two required autonomous fields:

- `decision_goal`: `incumbent_improvement | decision_information`;
- `result_use`: non-empty statement of the next action or ranking change caused by the result.

For `decision_information`, add:

- `follow_up_if_supported`;
- `follow_up_if_refuted`.

These fields do not create a general belief database. They provide the minimum machine-visible contract needed to decide whether an information experiment can repay its budget cost.

Compatibility:

- Existing completed trajectories without these fields remain readable and replayable.
- New autonomous commitments on this branch require the fields.
- Default/non-autonomous commitments remain unchanged.

## Retry resolution

Every retry recomputes the competition challenge from the corrected commitment. A correction resolves the challenge only when one of these becomes true:

- the candidate now satisfies the competition policy;
- the action changes to `incumbent_improvement` with valid local support;
- an information action names both follow-up branches and enough budget remains to execute at least one;
- the selected candidate directly tests the named trusted-surrogate disagreement.

Changing to an unrelated candidate with the same failing condition does not resolve the challenge.

Advisory exhaustion remains non-fatal. Deterministic hard validation remains fatal after the retry limit.

## Stage policy

Use the existing budget stages to avoid a second stage model:

- **Early**: allow exploit, targeted exploration, and global exploration; only deterministic validation and existing repeated-action stall checks apply.
- **Middle**: allow exploit and targeted exploration; challenge global exploration unless it is a current shortlist candidate with explicit two-branch follow-up.
- **Late**: prefer exploit. Information actions require at least one post-observation budget slot and explicit follow-up branches. Exploration outside the shortlist is challenged.

No Buchwald-specific factor names or yield thresholds enter runtime code.

## Data flow

```text
Agent tool calls
  -> commit_candidate evidence fields
  -> candidate identity/evidence validation
  -> acquisitionScore + shortlist rank
  -> competition policy audit
       hard validation? reject
       score-relevant challenge? retry
       telemetry-only signals? record and continue
  -> Oracle observation
  -> next step
```

## Replay validation

Add an offline replay helper around `verifyOptimizationPolicy` that feeds stored commitments and trajectory prefixes without reading labels for policy decisions. Offline evaluation may then join labels to calculate counterfactual quality and benchmark metrics.

Required replay assertions:

- Productive low-trust override streaks in historical healthy trajectories do not produce `gp_dissent` correction retries.
- Existing harmful challenges before seed-1600 steps 5, 26, and 38 are not correction retries under the competition policy.
- The step 23-37 stagnant interval produces a bounded challenge rather than repeated cross-context substitutions.
- Cross-context and scope signals remain present as telemetry where detected.

## A/B plan

### Control

A clean worktree at the recorded `main` base commit with detector changes disabled or the pre-treatment Supervisor behavior.

### Treatment

`experiment/competition-score-policy` with the competition policy enabled.

### Pairing

- Same dataset, seed, budget, model, thinking level, prior, and initial runtime.
- Pilot: seed 1600 to prove end-to-end behavior.
- Decision set: at least five paired seeds before any claim of improvement.

### Metrics

Primary:

- `auc_best_so_far`;
- `round_to_95_global_best`;
- `best_found`;
- `simple_regret`.

Diagnostic:

- correction retries per run;
- candidate changed after retry;
- hidden-label delta between rejected and executed candidates, offline only;
- longest no-improvement interval;
- exploit/targeted/global action counts;
- low-trust override count;
- provider/retry failures.

## Acceptance decision

Pilot acceptance requires no regression against the available seed-1600 GP baseline in campaign completion and a clear reduction in false-positive retries. Performance claims require paired multi-seed results; one seed is descriptive only.

## Rollback

The entire policy is isolated on `experiment/competition-score-policy`. Revert by abandoning the branch. Do not merge into `main` unless paired evaluation meets the PRD acceptance criteria.

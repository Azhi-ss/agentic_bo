# Repair autonomous BO policy auditing

## Goal

Build an isolated competition-score autonomous policy that improves the fixed budget-40 benchmark's Best, best-so-far AUC, and T95 behavior without leaking private labels into runtime decisions. The policy remains experimental on `experiment/competition-score-policy` unless paired evaluation supports merging.

## Background

The completed Buchwald `seed-1600` campaign exposed both useful and harmful policy interventions:

- Steps 1-22 improved the incumbent from 66.11 to 83.15 while frequently overriding a low-trust surrogate. These productive overrides must not be treated as GP dissent solely because they were consecutive.
- Steps 23-37 spent 15 observations without improving the incumbent. Several low-performing additive branches continued without a clear hypothesis-elimination or ranking update.
- Policy challenges changed eight executed trials. Some avoided poor hidden-label candidates, while others delayed better candidates by one or two steps, reducing AUC and worsening T95.
- Current detectors observe action shape (`override` streaks, frozen factors, uncovered contexts) but do not verify whether an observation changed beliefs, eliminated a hypothesis, changed candidate ranking, or resolved a stated disagreement.
- The benchmark score weights final best, best-so-far AUC, T95 attainment, and initial performance. Forced coverage can preserve final best while degrading AUC/T95.

## Requirements

### R1. Preserve deterministic safety gates

Hard rejection remains limited to deterministic violations such as invalid candidate identity, duplicate/observed candidate submission, malformed evidence, and evidence claims inconsistent with successful current-step tool use.

### R2. Do not challenge healthy exploitation by action shape alone

- Consecutive `surrogate_relationship=override` is not sufficient for a correction retry.
- Holding a factor fixed is not sufficient for a correction retry.
- Productive local refinement remains allowed when observations improve the incumbent or resolve a declared local comparison.
- Low surrogate trust reduces the evidentiary weight of surrogate disagreement rather than increasing challenge frequency.
- `cross_context_uncovered`, `scope_overreach`, and low-trust override streaks remain available as audit telemetry.

### R3. Require decision-relevant learning for exploratory actions

Every new autonomous commitment states:

- `decision_goal`: `incumbent_improvement | decision_information`;
- `result_use`: the next action or candidate-ranking change caused by the result.

A `decision_information` commitment additionally states:

- `follow_up_if_supported`;
- `follow_up_if_refuted`.

These fields remain domain-neutral. Existing completed trajectories without them remain readable and replayable.

### R4. Challenge only score-relevant self-closing behavior

A correction retry requires a score-relevant condition, not one detector signal alone. Applicable conditions include:

1. repeated action/factor behavior without incumbent improvement where the selected candidate is neither preferred nor the current best acquisition option;
2. middle/late global exploration whose information cannot repay its remaining budget cost;
3. terminal information work with no remaining follow-up action;
4. late targeted/global exploration outside the acquisition shortlist without a viable next-step use;
5. medium/high-trust surrogate dissent without a concrete experiment that resolves the disagreement.

### R5. A challenge must identify the required correction

The retry prompt identifies whether the agent must:

- update its decision state using verified observations;
- choose an incumbent-oriented action;
- provide executable supported/refuted follow-up branches;
- test a named trusted-surrogate disagreement; or
- provide evidence that the current action has greater competition value.

Changing only prose or switching to an unrelated candidate with the same failing condition does not resolve the challenge.

### R6. Competition-score and budget-stage awareness

- Runtime remains label-free: it must not read `test.csv`, the global optimum, or the T95 threshold.
- Early phase permits exploit, targeted exploration, and global exploration.
- Middle phase requires decision-changing use for information experiments and discourages global exploration that cannot repay its budget cost.
- Late phase prioritizes incumbent improvement and shortlist-adjacent exploitation; information-only actions require at least one remaining follow-up action.
- Offline acceptance evaluates Best, best-so-far AUC, T95, and simple regret using labels unavailable to the agent.
- Runtime code remains direction-aware and does not encode Buchwald-specific factor names or yield thresholds.

### R7. Backward compatibility and failure behavior

- Default/non-autonomous policy behavior remains unchanged.
- Existing trajectory and receipt formats remain readable.
- New fields are required only for new autonomous commitments on this branch.
- Existing hard policy challenges remain hard.
- Advisory exhaustion must not crash a campaign.

## Acceptance Criteria

- [ ] Four or more consecutive low-trust surrogate overrides that improve the incumbent or resolve declared comparisons do not cause a correction retry.
- [ ] Repeated actions with no incumbent improvement, no decision update, and a stronger available acquisition option cause one bounded correction retry.
- [ ] A frozen factor under productive local refinement does not cause a correction retry solely because it is frozen.
- [ ] Cross-context, scope-overreach, and GP-dissent signals remain recorded as telemetry.
- [ ] Decision-information actions without both supported/refuted follow-up branches are rejected before budget spend.
- [ ] An unrelated candidate substitution that retains the named failing condition does not resolve the challenge.
- [ ] In the terminal phase, an information commitment is allowed only when its result can change at least one remaining action.
- [ ] Existing hard validation and default-policy tests remain unchanged and pass.
- [ ] Offline replay substantially reduces false-positive corrections on historical healthy trajectories while retaining bounded corrections in known stagnant intervals.
- [ ] A same-seed A/B pilot compares detector-off and competition-policy runs using Best, AUC best-so-far, T95, simple regret, intervention count, and action-transition audit.
- [ ] Before any merge recommendation, at least five paired seeds show no median AUC or median T95 regression unless an explicit final-best trade-off is approved.
- [ ] Node unit tests and syntax checks pass.

## Out of Scope

- Hardcoding Buchwald reaction factors, yield thresholds, or the seed-1600 optimum.
- Reading private labels during policy execution.
- Replacing the GP/surrogate implementation.
- Adding a general-purpose persistent belief database.
- Guaranteeing monotonic yield improvement on every trial.
- Defining the default general Agentic BO policy.
- Claiming superiority from one seed.

## Key Decisions

- This task intentionally prioritizes the current competition score.
- Runtime stays label-free; competition labels are offline evaluation data only.
- Implementation stays isolated on `experiment/competition-score-policy` until paired evidence supports merging.

## Open Questions

None blocking planning.

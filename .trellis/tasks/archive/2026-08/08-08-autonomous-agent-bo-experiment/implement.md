# Implementation Plan

1. Load backend specs, the leakage audit, completed diagnostic task, and current modified source before editing.
2. Preserve reusable exact-score identity/posterior fields and report integrity checks from the diagnostic implementation.
3. Add focused RED tests for:
   - sanitized model-visible manifest/context;
   - standalone autonomous prompt composition;
   - no initial ranked suggestions in autonomous context;
   - profile-gated automatic UCB behavior;
   - label-free Candidate Inspection filtering/pagination/limits;
   - Decision Evidence Record validation against actual tool use;
   - forbidden autonomous mutation tools and early stop;
   - leakage preflight failure conditions;
   - default compatibility.
4. Implement the minimal label-free `lenz candidates` command by reusing `test_features.csv`, candidate identity helpers, and existing restriction semantics where exact-list filtering already fits.
5. Add the typed `lenz_candidates` Supervisor tool with a per-step returned-row counter capped at 500.
6. Replace the diagnostic runtime policy selectors with `default` and `autonomous_agent`; do not change default behavior.
7. Add the standalone autonomous prompt/profile and explicit model-visible context allowlist. Remove dataset/public paths from prompts and run evidence exposed to the model.
8. Profile-gate Supervisor behavior:
   - no automatic low-trust UCB switch for autonomous runs;
   - only acquisition/beta mutation tools exposed;
   - no initial `suggest` call/context;
   - no pre-budget stop;
   - both steps use autonomous instructions.
9. Extend commitment validation with the required Decision Evidence Record and verify `surrogate_relationship` against actual per-step tool evidence.
10. Add prior hash/scan/provenance and provider-generation-seed limitation to run configuration evidence.
11. Add a deterministic leakage preflight command/function and make autonomous provider startup and experiment planning fail closed when it does not pass.
12. Adapt the experiment planner/report for fresh matched `default` and `autonomous_agent` seeds 300–304, budget 2. Preserve failures and separate behavior/outcome/integrity sections.
13. Run focused Python and Node tests, then smoke one fresh budget-2 autonomous campaign only after leakage preflight passes. Export and validate its trajectory.
14. Run fresh matched Arm A and Arm D campaigns. Retry only provider-transient failures from the same state; retain explicit failures.
15. Generate the descriptive report and verify every successful run has two exact trajectory entries, two matching signed Receipts, complete session/events traces, Decision Evidence Records, and hashes.
16. Dispatch Trellis check, fix blocking findings, update executable backend specs, and prepare a clean commit plan. Do not commit generated ignored run artifacts.

## Validation Commands

- Focused Python unittest modules covering CLI/tool/report/leakage contracts.
- `cd supervisor && node --test campaign.test.mjs && node --check supervisor.mjs`.
- Leakage preflight against the exact autonomous rendered prompt and tool surface.
- One autonomous budget-2 smoke through `boagent init` + `boagent run --policy autonomous_agent` + export + `validate_trajectory(..., budget=2)`.
- Final report regeneration over all preserved matched runs.
- Trellis task context validation and `trellis-check` agent review.

## Risk / Rollback Points

- After context sanitization: stop if any required non-path manifest field is lost; use an explicit allowlist rather than restoring object spreading.
- After Candidate Inspection: stop if any implementation path reads `test.csv` or result-derived ordering.
- After profile cutover: prove omitted/default policy behavior before any autonomous live run.
- Before provider calls: leakage preflight is mandatory; no override flag.
- Do not delete completed diagnostic experiment artifacts or failed new campaign directories.
- Do not change model, provider, seed set, prompt, or policy in response to outcomes.

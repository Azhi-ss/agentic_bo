# Autonomous Agent BO design research

## Leakage audit

- No confirmed pre-commit hidden-label or global-optimum leak exists through the current model prompt or typed tools.
- Builtin filesystem/shell tools are disabled; extensions, skills, context files, templates, and other resource-loading surfaces are also disabled.
- `suggest`, `score`, `predict`, diagnostics, and trials derive from `test_features.csv`, imported historical Observations, and post-commit verified Observations.
- Oracle is the only Campaign component that reads `test.csv`; it requires an authorized Trial identity and returns a signed Experiment Receipt.
- Confirmed conditional risk: `manifest.dataset_root` is spread into model-visible `effective_manifest`, exposing an absolute dataset path. This is not currently exploitable without builtin tools, but autonomous runs must remove it and fail a regression gate if paths or forbidden fields reappear.

## Diagnostic experiment conclusion

- The completed `lm_compare` intervention generated a distinct scored chemistry-prior Candidate in every seed but still selected GP rank 1 in every seed.
- The base Paper Prompt's `preferred_suggestion` and mandatory low-trust UCB rules remained a GP-first anchor.
- The forced-LM contingency measured a constrained diagnostic intervention, not Autonomous Deliberation.
- The next experiment must make Surrogate Advice non-binding, allow Sara to choose which tools to consult, and avoid requiring either GP acceptance or LM distinctness.

## Approved design decisions

- New profile: `autonomous_agent`; existing `default` stays unchanged.
- Standalone concise autonomous prompt, not an override layered onto the Paper Prompt.
- Initial context provides summary/status but no precomputed ranked Proposals or full historical rows.
- Sara may inspect history and decide whether/when to consult GP tools.
- Add label-free, exact-filter Candidate Inspection with deterministic pagination, max 100 rows/call and 500 rows/Campaign Step.
- No automatic UCB switch in autonomous runs; Frame starts at valid default `noisy_logei` and Sara may modify acquisition/beta only.
- Both budget-2 steps are autonomous; early stop is forbidden for the experiment profile.
- Every Commitment requires a Decision Evidence Record whose self-declared Surrogate relationship matches actual tool use.
- Hard leakage preflight before provider execution; sanitize all model-visible context with allowlists.
- Keep public mechanism-level `PRIOR.md`, record hash, automatic label scan, and human provenance declaration.
- Fresh matched comparison: default Arm A versus autonomous Arm D, Suzuki seeds 300–304, budget 2, `gpt-5.6-sol`, requested `xhigh`, fresh sessions.
- Report behavior, outcomes, integrity, and failures separately; no statistical or cross-dataset superiority claims.

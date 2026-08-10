# Autonomous Agent BO experiment

## Goal

Evaluate a genuinely autonomous Sara policy against the current GP-first default on Suzuki: Sara chooses which public evidence and typed lenz tools to consult, owns both Commitments, and is not instructed to accept GP rank 1 or manufacture a distinct LM candidate.

## Background

The completed first-step LM-vs-UCB diagnostic showed that requiring a distinct scored chemistry candidate did not remove the base prompt's GP-first anchor: `lm_compare` proposed a distinct candidate in 5/5 runs but selected GP rank 1 in 5/5. The forced-LM contingency demonstrated outcome variance but did not evaluate autonomous decision-making because it constrained the answer.

A leakage audit found no confirmed pre-commit hidden-label leak through current prompts or typed tools. However, `manifest.dataset_root` currently enters `effective_manifest` and exposes an absolute dataset path in the prompt. Builtin filesystem/shell tools are disabled, so this is not a current label leak, but autonomous runs must remove the path and add a hard regression gate before provider execution.

## Requirements

### Policy and Prompt

- Add a selectable `autonomous_agent` Campaign Profile while keeping the current `default` behavior unchanged.
- Use an independent concise autonomous system prompt rather than layering override text onto the GP-first Paper Prompt.
- The prompt must state that Sara owns the final decision and that Surrogate Advice is non-binding.
- Do not require Sara to select GP rank 1, propose a distinct Candidate, consult GP, or follow a fixed tool sequence.
- Both Campaign Steps remain autonomous. After Receipt 1, Sara must state how the Observation changes its belief before choosing Step 2.
- Autonomous experiment runs must spend both budget units; early stop is not allowed for this profile.

### Visible Evidence and Leakage Boundary

- Initial prompt includes a label-free dataset summary and public domain prior, not all historical rows or precomputed ranked Proposals.
- Sara may call `lenz_trials` to inspect verified historical Observations.
- Sara decides whether and when to call diagnostics, suggestions, score, or predict.
- Remove `dataset_root`, `public_root`, `test.csv`, absolute dataset paths, global-best information, hidden ranks, and uncommitted Outcomes from rendered prompts and typed tool results.
- Keep builtin tools, extensions, skills, context files, and prompt templates disabled.
- Oracle remains the only campaign component allowed to read `test.csv`; it may reveal an Outcome only after a valid Commitment and through a signed Experiment Receipt.
- Before any live provider run, a hard automated leakage gate must verify the rendered first-turn prompt and tool contracts/results against the forbidden fields above.
- Record `prior_hash`, prior source identity, an automatic label-content scan result, and a human provenance declaration that `PRIOR.md` derives from mechanism knowledge or pre-experiment sources rather than hidden benchmark labels.

### Candidate Inspection

- Add a read-only typed `lenz_candidates` tool over `test_features.csv`.
- Support exact legal option filters, multiple allowed values per feature, deterministic `pool_index` order, cursor pagination, and a per-call limit no greater than 100.
- Return only `pool_index`, `candidate_id`, and exact public `config`, plus pagination metadata.
- Never return Outcomes, label-derived statistics, hidden ranks, global-best distance, or result-based ordering.
- Allow at most 500 returned Candidate rows per Campaign Step; repeated queries count again. Reset the allowance for Step 2.
- `score` and `predict` calls do not consume Candidate Inspection rows.
- An invalid or non-pool Commitment is rejected without spending experiment budget. Sara may correct it within the existing capped action attempts; persistent failure is explicit and is never replaced silently with a GP Candidate.

### Optimization Authority

- Under `autonomous_agent`, do not perform the Supervisor's automatic low-trust `UCB(beta=16)` switch.
- The Frame begins with its valid default `noisy_logei` configuration.
- Sara may inspect or change acquisition function and `beta` through typed tools.
- For this experiment, Sara may not change objectives, constraints, or permanent parameter bounds. Candidate filters are temporary inspection queries, not domain revisions.
- A Commitment is compliant whether Sara accepts a consulted Proposal, overrides it, uses Surrogate evidence without viewing ranked Proposals, or does not consult the Surrogate.

### Decision Evidence Record

Every Commitment must contain:

- `hypothesis`: why the Candidate may improve the Campaign;
- `evidence_sources`: explicit consulted sources;
- `expected_outcome`: qualitative or quantitative outcome/risk judgment;
- `expected_learning`: how possible results affect later decisions, or why the final step maximizes final best;
- `surrogate_relationship`: `accept`, `override`, `informed_without_proposal`, or `not_consulted`;
- `rationale`: why this Candidate should be executed now.

The evidence record is an audit contract, not proof of optimality and not a constraint on which Candidate Sara selects.

### Experiment

- Compare two freshly run arms using the same code revision:
  - Arm A: current `default` GP-first behavior.
  - Arm D: `autonomous_agent` behavior.
- Use Suzuki, campaign seeds `300–304`, budget `2`, provider `ai-modeling`, model `gpt-5.6-sol`, requested thinking `xhigh`, and a fresh Pi session per arm/seed.
- Record that campaign seed controls campaign/model initialization where supported but is not a provider generation seed; provider generation seed is unavailable.
- Preserve failed directories and retry only transient provider failures from the same Campaign state. Do not replace failed seeds or analyze only successes.
- The experiment succeeds by executing and auditing the agreed policies; autonomous performance is an outcome, not an acceptance condition.

### Reporting

Report per seed and descriptive aggregates without statistical-significance claims.

Behavior fields:

- calls to trials, candidates, diagnostics, suggest, score, and predict;
- Candidate rows inspected;
- acquisition/beta revisions;
- whether ranked Proposals were consulted;
- `surrogate_relationship`;
- final acquisition rank when available;
- Candidate diversity across seeds;
- Decision Evidence Record completeness.

Outcome fields:

- first-step Yield;
- second-step Yield;
- two-step best;
- improvement over historical incumbent;
- mean, median, minimum, and per-seed values.

Integrity fields:

- prompt, prior, config, and code-revision hashes;
- leakage-gate result;
- exact Candidate identity;
- exactly two signed Receipts and a complete trajectory/session trace per successful run;
- explicit failure count and reasons.

## Acceptance Criteria

- [ ] `default` remains behaviorally compatible and selectable without an explicit policy argument.
- [ ] `autonomous_agent` uses a standalone non-GP-first prompt and does not receive precomputed ranked Proposals in its initial prompt.
- [ ] Autonomous Sara controls if and when it consults or reconfigures Surrogate Advice and owns both final Commitments.
- [ ] `lenz_candidates` exposes only deterministic, label-free public Candidate identity/configuration with exact filters and enforced 100-per-call/500-per-step limits.
- [ ] Every autonomous Commitment has a valid complete Decision Evidence Record and an exact unobserved public Candidate identity.
- [ ] Invalid Candidates fail explicitly without consuming budget or silently falling back to a GP Candidate.
- [ ] Autonomous runs cannot change objectives, constraints, or permanent bounds and cannot stop before two verified evaluations.
- [ ] The automated leakage gate passes before live runs and proves prompts/tool outputs omit hidden labels and dataset paths while builtin tools remain disabled.
- [ ] `PRIOR.md` has a recorded hash, automated label scan, and provenance declaration.
- [ ] Fresh matched Arm A and Arm D campaigns complete or retain explicit failures for seeds 300–304, with exactly two signed Receipts for every successful run.
- [ ] The final report separates behavior, optimization outcomes, and integrity evidence; it includes failures and makes no significance or cross-dataset superiority claim.
- [ ] Focused Python and Node contract tests pass, exported successful trajectories validate, and a Trellis check finds no blocking issue.

## Out of Scope

- Full 40-step benchmarking.
- General superiority claims across datasets or models.
- Free-form Candidates outside the finite public pool.
- Replacing the default production policy.
- Treating natural-language rationale as measured evidence.
- Making provider output fully replayable when provider generation seeding is unavailable.

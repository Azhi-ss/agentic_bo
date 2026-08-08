# Technical Design

## Architecture

Add an explicit experiment policy selector at the campaign-run boundary rather than editing the default paper prompt in place.

- `default`: current production behavior and prompt remain unchanged.
- `lm_compare`: append a narrow opening-policy instruction only while the surrogate is low-trust and no campaign observation exists.
- `lm_forced_first` (contingency only): same comparison evidence, but the first commitment must be the distinct chemistry-prior candidate.

The selected policy must be written into `campaign-run-config.json` and included in the prompt/config hash evidence.

## Opening Data Flow

1. Supervisor computes the existing context: status, top-20 suggestions, diagnostics, and verified trials.
2. For `lm_compare` under low trust at step 1, the prompt requires:
   - identify GP rank 1;
   - construct one exact, distinct chemistry-prior config from the public finite domain;
   - resolve and inspect that config through a typed lenz tool;
   - compare posterior mean/variance and active acquisition against GP rank 1;
   - freely choose one and commit it.
3. The second step receives the verified first result and repeats normal evidence-based selection; the trace must show how the result changed the decision.
4. For `lm_forced_first`, step 1 follows the same comparison but commits the independent LM candidate; step 2 is free.

## Tool Contract

Reuse `lenz_score` rather than adding a broad new tool. Extend its result to include the resolved finite-pool identity and posterior fields needed for comparison:

```json
{
  "candidate_id": "...",
  "pool_index": 123,
  "config": {},
  "posterior_mean": 80.0,
  "posterior_variance": 12.0,
  "acquisition_value": 0.4,
  "acqf": "ucb"
}
```

`pool_index` is required so an LLM-proposed public config can be committed. Keep existing acquisition-name output only if compatibility tests require it; otherwise use the same normalized shape as `suggest` to avoid a second convention.

## Enforcement

Prompt text alone is insufficient. During the first low-trust `lm_compare` turn, Supervisor tracks tool evidence and rejects an action unless:

- a scored candidate distinct from `preferred_suggestion` was observed in the turn; and
- the commitment is either that candidate or GP rank 1.

For `lm_forced_first`, reject any first commitment other than the scored distinct candidate.

This enforcement is experiment-policy scoped. The default policy retains current behavior.

## Experiment Runner

Use a small benchmark/operator script to run fixed seeds for both arms with budget 2, unique output directories, and identical model/thinking settings. It should resume or report failed runs without deleting artifacts.

Suggested fixed seeds: `300, 301, 302, 303, 304`. They are declared before outcomes and avoid existing seed-200 comparisons.

Aggregate only observable fields:

- selected GP rank;
- distinct LM candidate and whether selected;
- score/predict calls;
- first and second Yield;
- two-step best and improvement over historical incumbent;
- prompt/config hashes and policy compliance.

## Compatibility

- Default `boagent run` behavior is unchanged when no experiment policy is supplied.
- Existing campaign state and trajectory schemas remain readable.
- New trace fields, if any, are additive.
- No hidden test labels enter prompts or tool outputs.

## Risks

- The LLM may satisfy “distinct” with a chemically weak arbitrary point. Mitigation: require explicit chemistry rationale and exact score comparison; report compliance separately from Yield.
- Five seeds are descriptive, not inferential. The report must not claim significance.
- Provider failures can dominate a small experiment. Preserve state and retry the same arm/seed.
- The same historical dataset means initial diagnostics may be identical across seeds; the experiment primarily measures LLM/prompt behavior and subsequent decision response.

## Rollback

Remove/disable the non-default policy selector and experiment runner. Default prompt, state, and run behavior remain untouched throughout.

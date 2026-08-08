# First-step LM vs UCB experiment research

## Confirmed repository behavior

- Initial Suzuki state contains 29 historical observations. In the seed-300 trace, opening diagnostics were `train_r2=0.9999278046254365`, `cv_r2=-0.32469671839768655`, train/CV gap `1.324624523023123`, with a boundary lengthscale.
- `supervisor/supervisor.mjs:138-143` changes a zero-observation low-trust campaign to `UCB(beta=16)` before prompting the LLM.
- `profiles/paper-reproduction/PAPER_SYSTEM.md:54-56` says to commit `preferred_suggestion` by default and defines UCB beta 16 as mandatory low-trust behavior.
- `supervisor/campaign.mjs:258` leaves `enforcePreferredSuggestion` as a no-op, and tests confirm low-trust prior overrides are allowed. The system permits overrides but does not require an independent proposal or comparison.
- The seed-300 LLM stated a chemistry-prior candidate before tool calls, but it matched GP/UCB rank 1. Across the completed run, every commitment had acquisition rank 1.
- `lenz_score` resolves exact configs internally through `find_candidate`, but its output omits `pool_index`, preventing a scored LLM config from being directly committed without another identity lookup.
- A campaign budget of 2 naturally runs exactly two real Supervisor/Oracle evaluations, making it suitable for the proposed experiment.

## Planning decision

Run two mandatory arms across fixed seeds 300–304, budget 2:

1. Current UCB-first default.
2. Low-trust LM-vs-GP comparison: require a distinct chemistry candidate and exact score/predict comparison, then let the LLM choose.

If arm 2 still selects GP rank 1 in all five first steps, run a predeclared forced-LM first-step diagnostic arm for the same seeds.

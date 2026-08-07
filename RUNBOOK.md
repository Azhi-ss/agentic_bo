# Reproduce Sara with pi and uv

1. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`.
2. Install the Python environment: `uv sync`.
3. Verify the paper's pi harness model: `PI_CODING_AGENT_DIR=$PWD/.pi pi --list-models Claude-4.8-opus`.
4. Run one Suzuki campaign:

```bash
uv run boagent \
  --dataset-root datasets/chemical_reactions/suzuki \
  --output runs/suzuki/seed-100 \
  --seed 100 \
  --budget 40 \
  --model Claude-4.8-opus
```

The agent sees `train.csv`, `test_features.csv`, and — when the dataset root contains a `PRIOR.md` — that file's domain prior, injected into the `## Domain context` section of the generated `TASK.md`. The trusted Oracle alone reads `test.csv`, returning only the committed row's metric. Each campaign writes `state.json` plus `seed_<seed>.pt`.

To give a dataset its own domain prior, add a `PRIOR.md` to its dataset root (see `datasets/chemical_reactions/suzuki/PRIOR.md` for the format). Keep it qualitative — reaction name, catalyst system, and favorable regime — with no label statistics, optimal values, or specific winning candidates; `boagent init` picks it up automatically and falls back to the generic Domain-context line when the file is absent.

Direct lenz use:

```bash
uv run lenz create --state state.json --dataset-root datasets/chemical_reactions/suzuki --target Yield --direction maximize --seed 100
uv run lenz suggest --state state.json --q 8
uv run lenz submit --state state.json --query-index 123
uv run boagent-oracle --dataset-root datasets/chemical_reactions/suzuki --query-index 123
uv run lenz observe --state state.json --query-index 123 --metrics '{"Yield": 53.6}'
uv run lenz incumbent --state state.json
```

This is an architecture-level reproduction of Sara + lenz for finite candidate pools. The paper does not disclose enough backend defaults for bit-for-bit reproduction; the project fixes explicit BoTorch defaults instead.

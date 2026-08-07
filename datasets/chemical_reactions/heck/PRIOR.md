### Task Specific Domain Priors: Mizoroki-Heck Reaction

**Reaction Context:**
This task optimizes a palladium-catalyzed Mizoroki-Heck cross-coupling. The searchable knobs are the `Base`, phosphine `Ligand`, `Solvent`, substrate `Concentration_M`, and reaction `Temp_C`; the aryl/alkene substrates and Pd catalyst are fixed.

**Favorable Operating Regime (qualitative priors):**
- The Heck reaction generally favors **hot and dry** conditions: higher `Temp_C` within the searchable range typically accelerates the catalytic cycle, and non-aqueous media are preferred.
- The `Base` acts as a scavenger that regenerates the active Pd(0) species; carboxylate bases (acetate/pivalate) are standard for this cycle.
- The `Ligand` stabilizes and activates the Pd center; electron-rich phosphines are commonly used to promote the reaction.
- `Concentration_M` and `Solvent` jointly set the effective reaction medium and can shift both rate and selectivity.

**Usage Instruction:**
Use these priors only to (1) guide cold-start proposals before `lenz` has a trustworthy surrogate, and (2) break near-ties in acquisition score by preferring the candidate whose temperature/base/ligand best matches the hot, dry regime above. Never let these priors override strong observed evidence from Experiment Receipts, and never treat them as measured results.

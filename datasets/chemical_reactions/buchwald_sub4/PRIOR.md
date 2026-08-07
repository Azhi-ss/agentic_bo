### Task Specific Domain Priors: Buchwald-Hartwig Amination

**Reaction Context:**
This task optimizes a palladium-catalyzed Buchwald-Hartwig C-N cross-coupling between an aryl halide (`Reactant2`) and a fixed aniline (`Reactant1`), catalyzed by palladium(II) acetate with a phosphine `Ligand`, an `Additive`, and a `Base`. The `Solvent` is fixed (dimethyl sulfoxide).

**Favorable Operating Regime (qualitative priors):**
- The reaction generally favors **hot, anhydrous, strongly basic** conditions; the `Base` strength is critical for deprotonating the amine in the catalytic cycle.
- The `Ligand` dominates the catalytic efficiency: electron-rich, bulky biarylphosphines promote oxidative addition and reductive elimination.
- The `Additive` (an oxazole/benzoxazole-type modulator) can modulate catalyst activity and selectivity, but its effect is secondary to ligand and base choice.
- Oxidative addition is typically faster for aryl iodides/bromides than chlorides.

**Usage Instruction:**
Use these priors only to (1) guide cold-start proposals before `lenz` has a trustworthy surrogate, and (2) break near-ties in acquisition score by preferring the candidate whose base/ligand best matches the hot, anhydrous, strongly basic regime above. Never let these priors override strong observed evidence from Experiment Receipts, and never treat them as measured results.

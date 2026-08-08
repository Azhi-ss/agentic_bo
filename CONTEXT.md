# Agentic Bayesian Optimization

This context covers a surrogate-assisted research campaign over mixed parameter spaces or finite experimental candidate pools.

## Language

**Campaign**:
A budgeted sequence of experimental decisions that shares one evolving trial history and optimization configuration.
_Avoid_: Run, job

**Candidate**:
A unique normalized parameter configuration eligible for evaluation; a finite-pool row index is only an external reference.
_Avoid_: Trial, proposal, row

**Observation**:
An immutable raw Outcome set produced by a real Experiment, subject only to append-only correction events.
_Avoid_: Prediction, score, objective

**Oracle**:
The isolated boundary that reveals real Outcomes only for Trials authorized in the current Campaign Step.
_Avoid_: Test set, label lookup

**Sara**:
The reasoning Agent that owns Deliberation and final optimization decisions while treating lenz as a reconfigurable source of Surrogate Advice.
_Avoid_: Campaign Supervisor, surrogate

**Surrogate**:
The probabilistic model derived from observations that estimates candidate outcomes and uncertainty.
_Avoid_: Oracle, evaluator

**Proposal**:
A candidate recommended by the Bayesian backend without spending evaluation budget or changing trial history.
_Avoid_: Observation, experiment

**Commitment**:
The exact candidate selected for a real evaluation and marked in flight before its observation arrives.
_Avoid_: Proposal, prediction

**Incumbent**:
The best feasible observed candidate under the campaign's current objective and constraints.
_Avoid_: Best prediction

**Trajectory**:
The ordered record of commitments and observations for one campaign seed.
_Avoid_: Candidate ranking

**Deliberation**:
The sequence of computational actions Sara takes between two real evaluations, including probes, proposals, and reconfiguration.
_Avoid_: Trial, evaluation

**Campaign Step**:
One Deliberation followed by an explicitly authorized Commitment or Batch and its resulting Observations, or an explicit stop decision.
_Avoid_: Agent turn, loop iteration

**Optimization Configuration**:
The current surrogate family, acquisition function, active bounds, objectives, and constraints used by the campaign.
_Avoid_: Model state

**Campaign Supervisor**:
The non-decision-making authority that enforces budget, step boundaries, persistence, and campaign continuation while Sara controls optimization decisions.
_Avoid_: Optimizer, agent

**Experiment**:
The real-world execution of exactly one Commitment that may produce an Observation or an Experiment Failure.
_Avoid_: Prediction, proposal

**Experiment Failure**:
A real attempted Experiment that consumes budget but produces no trainable metric.
_Avoid_: Infrastructure failure

**Infrastructure Failure**:
A failure of the execution machinery before a real Experiment outcome is established; it does not consume experimental budget and may be retried.
_Avoid_: Experiment failure

**Exogenous Instruction**:
New append-only campaign context supplied after setup that may change requirements without erasing prior deliberation or trial history.
_Avoid_: Configuration overwrite

**Parameter Space**:
The typed domain of continuous, integer, and categorical parameters from which Candidates may be formed.
_Avoid_: Candidate pool

**Candidate Pool**:
An optional finite restriction on which combinations from the Parameter Space may be evaluated.
_Avoid_: Parameter space

**Trial**:
One Candidate's committed Experiment lifecycle, progressing through pending and running to observed or failed.
_Avoid_: Candidate, observation

**Replicate**:
A separately authorized Trial of a Candidate that has already been evaluated.
_Avoid_: Duplicate candidate

**Outcome**:
An immutable raw quantity measured by an Experiment, independently of how the campaign currently values it.
_Avoid_: Objective, constraint

**Objective**:
An Optimization Configuration's current direction for valuing an Outcome.
_Avoid_: Outcome

**Outcome Constraint**:
A current threshold on one Outcome used to classify observations as feasible, infeasible, or unknown.
_Avoid_: Parameter bound

**Configuration Revision**:
An append-only change to how existing evidence is interpreted, including objectives, constraints, bounds, categories, or acquisition policy.
_Avoid_: Trial mutation

**Batch**:
An explicitly authorized atomic set of Trials selected in one Campaign Step; each Trial consumes its own budget unit.
_Avoid_: Single trial

**Surrogate Advice**:
Non-binding posterior, uncertainty, diagnostic, acquisition, or Proposal evidence that Sara may accept, compare, or override.
_Avoid_: Decision, commitment

**Override**:
A Commitment that intentionally departs from the consulted Surrogate Advice while preserving the advice and Sara's rationale in the campaign record.
_Avoid_: Invalid candidate

**Benchmark LCB**:
A campaign-level lower-confidence score computed across repeated seeds as an evaluation protocol; it is never an acquisition function or campaign input.
_Avoid_: GP-LCB

**GP-LCB**:
A candidate-level lower confidence bound derived from a surrogate posterior for use during Deliberation.
_Avoid_: Benchmark LCB

**Stop Recommendation**:
Sara's non-binding judgment that another Experiment has insufficient expected value; the Campaign Supervisor remains the stopping authority.
_Avoid_: Campaign termination

**Surrogate Registry**:
The versioned set of reproducible surrogate families Sara may select without modifying backend source code during a Campaign.
_Avoid_: Arbitrary model code

**Model Comparison**:
A read-only comparison of registered surrogates on identical Trial evidence and validation splits; it does not change the active Optimization Configuration.
_Avoid_: Configuration revision

**Surrogate Diagnostics**:
Non-binding evidence about predictive accuracy, uncertainty calibration, sensitivity, local support, fitted assumptions, and numerical stability.
_Avoid_: Trust score, decision

**Natural-Language Prior**:
Informal domain knowledge from instructions, documents, or code that Sara interprets during Deliberation and may translate into explicit decisions or Configuration Revisions.
_Avoid_: Observation, hidden posterior mutation

**Domain Prior**:
The per-dataset, mechanism-level Natural-Language Prior loaded from an optional `PRIOR.md` in the dataset root. At `boagent init` time it is composed into the `## Domain context` section of `TASK.md`; when no `PRIOR.md` exists, the generic Domain-context line is used unchanged. It names the reaction/domain and its favorable operating regime at a qualitative level only — it must never encode label statistics, optimal values, or specific winning candidates derived from the labeled search space (that is data leakage).
_Avoid_: Observation, Oracle Outcome, hidden label

**Acquisition Policy**:
The current method and parameters used by lenz to value or generate Proposals; its outputs remain Surrogate Advice.
_Avoid_: Commitment policy

**Model Revision**:
The identified fitted Surrogate derived from a particular Trial evidence set, surrogate family, and fitting specification.
_Avoid_: Configuration revision

**Faithful Campaign**:
A Campaign whose Sara policy is induced by one Pi CLI Agent Loop, the transcribed paper prompts, only read and bash tools, retained context, and a fixed inference profile.
_Avoid_: SDK-controlled campaign

**Campaign Profile**:
A versioned declaration of the model, inference settings, prompts, tools, and operational constraints that induce Sara's policy.
_Avoid_: Optimization configuration

**Experiment Receipt**:
An immutable record proving that one authorized Trial was executed and what Outcomes or failure it produced, even before lenz records an Observation.
_Avoid_: Observation

**Agent Harness**:
The Pi command-line host that runs Sara's Agent Loop, retains conversational context, communicates with the LLM, and exposes read and bash.
_Avoid_: Sara, Campaign Supervisor

**Frame**:
The single persistent lenz state containing the Trial Log, Event Log, and Shelf from which all surrogate objects are derived.
_Avoid_: Fitted model, session

**Trial Log**:
The append-only experimental history of Trial lifecycle events and raw Outcomes.
_Avoid_: Proposal history

**Event Log**:
The append-only history of Campaign setup, Configuration Revisions, probe audit references, and data corrections.
_Avoid_: Trial log

**Shelf**:
The current Optimization Configuration snapshot derived from the Event Log and stored for efficient access.
_Avoid_: Source of historical truth

**State Revision**:
The monotonic identity of a complete Frame snapshot used for concurrency control and reproducible tool outputs.
_Avoid_: Configuration revision

**Benchmark Profile**:
A versioned evaluation contract fixing datasets, seeds, initial evidence, candidate visibility, evaluation budget, trajectory validation, metrics, and aggregation.
_Avoid_: Campaign profile

**Public Candidate Pool**:
The unlabeled finite Candidate set visible to Sara and lenz during a benchmark Campaign.
_Avoid_: Oracle data

**Initial Trial**:
An observed Trial imported before Sara starts and available as prior evidence without consuming the Campaign's evaluation budget.
_Avoid_: Campaign experiment

**Oracle Outcome**:
A hidden benchmark Outcome revealed only for one valid committed Candidate through the Oracle boundary.
_Avoid_: Public dataset label

**Benchmark Trajectory**:
The evaluator-facing ordered projection of validated Campaign Trials and Oracle Outcomes, derived from authoritative logs rather than Agent-authored output.
_Avoid_: Pi conversation

**Paper Prompt**:
The normalized but semantically unmodified transcription of the paper's published SYSTEM.md or LENZ_REF.md, identified by source and content hash.
_Avoid_: Campaign prompt

**Campaign Prompt**:
The versioned operational instructions that specialize a Paper Prompt for one Campaign without weakening its rules.
_Avoid_: Task description

**Rendered System Prompt**:
The exact ordered prompt text delivered to the model after all declared prompt layers are composed.
_Avoid_: Prompt source files

**Commitment**:
Sara's explicit selection of one valid Candidate for real evaluation, including its source and any override of Surrogate Advice.
_Avoid_: Proposal

**Exogenous Instruction**:
New user-supplied requirements arriving during a Campaign that may trigger an audited Optimization Configuration revision.
_Avoid_: Observation

**Verified Campaign Summary**:
The Supervisor-generated factual report derived from the Frame, Experiment Receipts, revisions, and archived artifacts.
_Avoid_: Sara report

**Autonomous Deliberation**:
A Deliberation in which Sara chooses which public evidence and Surrogate Advice to consult, then owns the final Commitment without a default obligation to accept the top-ranked Proposal.
_Avoid_: Surrogate-free decision, random override

**Candidate Inspection**:
A read-only examination of legal Candidates and their public parameter configurations without access to Oracle Outcomes, hidden benchmark ranks, or label-derived statistics.
_Avoid_: Oracle lookup, candidate evaluation

**Decision Evidence Record**:
The structured account of Sara's hypothesis, consulted evidence, expected learning or improvement value, relationship to Surrogate Advice, and final rationale for a Commitment.
_Avoid_: Observation, proof of optimality

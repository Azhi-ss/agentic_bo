import { isDeepStrictEqual } from "node:util";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const result = (value) => ({ content: [{ type: "text", text: JSON.stringify(value) }], details: value });
export const STOP_CONDITIONS = [
  "target_reached",
  "observed_candidates_exhausted",
];

export const validateCampaignStatus = (status, manifest, frame) => {
  if (!status || status.status !== "stopped") return undefined;
  if (status.campaign_id !== manifest.campaign_id) throw new Error("campaign status campaign_id mismatch");
  if (status.state_revision !== frame.state_revision) throw new Error("campaign status state_revision mismatch");
  const observed = frame.trials.filter((trial) => trial.status === "observed" && trial.source !== "historical").length;
  const pending = frame.trials.filter((trial) => trial.status === "pending" && trial.source !== "historical").length;
  if (status.observed !== observed) throw new Error("campaign status observed count mismatch");
  if (pending !== 0) throw new Error("stopped campaign cannot have pending trials");
  if (status.budget !== manifest.budget || status.budget_remaining !== manifest.budget - observed) throw new Error("campaign status budget mismatch");
  if (!STOP_CONDITIONS.includes(status.condition) || !status.rationale?.trim() || status.verified !== true) throw new Error("campaign status is not a verified stop");
  return status;
};

export const verifyStop = (action, manifest, context) => {
  const status = context.status;
  if (action.condition === "target_reached") {
    const threshold = manifest.target_value ?? manifest.target_threshold;
    if (!Number.isFinite(threshold)) throw new Error("target_reached requires a quantitative target threshold");
    const values = context.verified_trials.filter((trial) => trial.source !== "historical").map((trial) => trial.metrics?.[manifest.target]).filter(Number.isFinite);
    const reached = manifest.direction === "minimize"
      ? values.some((value) => value <= threshold)
      : values.some((value) => value >= threshold);
    if (!reached) throw new Error("target_reached is not supported by verified observations");
  }
  if (action.condition === "observed_candidates_exhausted" && (status.remaining !== 0 || status.pending.length !== 0)) {
    throw new Error("observed_candidates_exhausted requires zero remaining and pending candidates");
  }
  return action;
};

export const reconcileTrajectory = (frame, trajectory, receiptForTrial = () => undefined) => {
  const entries = trajectory.map((entry) => ({ ...entry }));
  for (const trial of frame.trials) {
    if (trial.source === "historical") continue;
    let entry = entries.find((item) => item.trial_id === trial.trial_id || item.request_id === trial.request_id);
    if (!entry) {
      entry = { rationale: null, provenance: "recovered" };
      entries.push(entry);
    }
    const rationale = entry.decision?.rationale ?? entry.rationale ?? null;
    entry.request_id = trial.request_id;
    entry.trial_id = trial.trial_id;
    entry.decision = {
      ...(entry.decision ?? {}),
      pool_index: trial.query_index,
      config: trial.config,
      candidate_id: trial.candidate_id,
      rationale,
    };
    entry.receipt = entry.receipt ?? receiptForTrial(trial);
    entry.provenance ??= rationale === null ? "recovered" : "journaled";
    if (trial.status === "observed") entry.metrics = trial.metrics;
  }
  return entries;
};

export const lastAssistantFailure = (messages) => {
  const message = messages.findLast((item) => item.role === "assistant");
  return message?.stopReason === "error" ? (message.errorMessage || "provider returned an unspecified error") : undefined;
};

export const isTransientProviderError = (message) => /(?:\b(?:429|502|503|504)\b|concurrency limit|too many concurrent requests|cooldown|temporar(?:y|ily) unavailable|timed?\s*out|timeout|connection (?:reset|closed)|socket hang up|(?:http\/2|response )?stream (?:was )?(?:failed|interrupted|ended without finish_reason))/i.test(message);
export const promptWithTransientRetries = async ({ prompt, messages, onPause, onError, sleep, canRetry = () => true, maxAttempts = 3 }) => {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    await prompt();
    const error = lastAssistantFailure(messages());
    if (!error) return;
    if (!isTransientProviderError(error)) {
      await onError(error);
      throw new Error(error);
    }
    await onPause(error, attempt);
    if (!canRetry() || attempt === maxAttempts) throw new Error(error);
    await sleep(250 * (2 ** (attempt - 1)));
  }
};

export const createCampaignActionTools = (setAction, { autonomous = false } = {}) => {
  const evidence = {
    hypothesis: Type.String({ minLength: 1 }),
    evidence_sources: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
    expected_outcome: Type.String({ minLength: 1 }),
    expected_learning: Type.String({ minLength: 1 }),
    surrogate_relationship: Type.Union(["accept", "override", "informed_without_proposal", "not_consulted"].map((value) => Type.Literal(value))),
    surrogate_trust: Type.Union([Type.Literal("low"), Type.Literal("medium"), Type.Literal("high")]),
    surrogate_trust_rationale: Type.String({ minLength: 1 }),
    search_mode: Type.Union([Type.Literal("exploit"), Type.Literal("targeted_exploration"), Type.Literal("global_exploration")]),
    decision_goal: Type.Union([Type.Literal("incumbent_improvement"), Type.Literal("decision_information")]),
    expected_objective_value: Type.Optional(Type.Number()),
    result_use: Type.String({ minLength: 1 }),
    follow_up_if_supported: Type.Optional(Type.String({ minLength: 1 })),
    follow_up_if_refuted: Type.Optional(Type.String({ minLength: 1 })),
    rationale: Type.String({ minLength: 1 }),
  };
  const tools = [defineTool({
    name: "commit_candidate",
    label: "Commit Candidate",
    description: "Commit exactly one candidate from the current verified public candidate set.",
    parameters: Type.Object({
      pool_index: Type.Integer({ minimum: 0 }),
      config: Type.Record(Type.String(), Type.Unknown()),
      ...(autonomous ? evidence : {
        rationale: Type.String({ minLength: 1 }),
        intent: Type.Optional(Type.Union([Type.Literal("optimize"), Type.Literal("discriminate"), Type.Literal("explore"), Type.Literal("reconfigure")])),
        evidence_sources: Type.Optional(Type.Array(Type.Union([Type.Literal("acquisition"), Type.Literal("prior"), Type.Literal("information"), Type.Literal("reconfiguration")]), { minItems: 1 })),
        expected_learning: Type.Optional(Type.String({ minLength: 1 })),
        result_use: Type.Optional(Type.String({ minLength: 1 })),
      }),
    }),
    async execute(_id, params) {
      const action = { type: "commit_candidate", ...params };
      setAction(action);
      return { ...result(action), terminate: true };
    },
  })];
  if (!autonomous) tools.push(defineTool({
    name: "stop_campaign",
    label: "Stop Campaign",
    description: "Stop only when one of the paper-defined stopping conditions is verified.",
    parameters: Type.Object({
      condition: Type.Union(STOP_CONDITIONS.map((condition) => Type.Literal(condition))),
      rationale: Type.String({ minLength: 1 }),
    }),
    async execute(_id, params) {
      const action = { type: "stop_campaign", ...params };
      setAction(action);
      return { ...result(action), terminate: true };
    },
  }));
  return tools;
};

export const requireCampaignAction = (action) => {
  if (!action) throw new Error("assistant returned no explicit campaign action");
  return action;
};

export const campaignResult = (campaign, evaluations, stop) => ({
  ok: true,
  campaign,
  status: stop ? "stopped" : "budget_exhausted",
  evaluations,
  ...(stop ? { stop } : {}),
});

export const createLenzTools = (lenz, state, onMutation = () => {}, onEvidence = () => {}, { autonomous = false } = {}) => {
  let inspectedRows = 0;
  const tracked = (name, response) => {
    if (response?.ok) onEvidence(name, response);
    return result(response);
  };
  const tools = [
    defineTool({
      name: "lenz_suggest", label: "Lenz Suggest", description: "Read the current posterior and propose candidates without committing or updating state. Repeating without a new observation or acquisition/search change adds no evidence.",
      parameters: Type.Object({ q: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })), acqf: Type.Optional(Type.String()), beta: Type.Optional(Type.Number({ minimum: 0 })), bounds: Type.Optional(Type.Record(Type.String(), Type.Unknown())), around: Type.Optional(Type.Boolean()), radius: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 1 })), pure_rank: Type.Optional(Type.Boolean()) }),
      async execute(_id, params) {
        const args = ["suggest", "--state", state, "--q", String(params.q ?? 5)];
        if (params.acqf) args.push("--acqf", params.acqf);
        if (params.beta !== undefined) args.push("--beta", String(params.beta));
        if (params.bounds) args.push("--bounds", JSON.stringify(params.bounds));
        if (params.around) args.push("--around", "--radius", String(params.radius ?? 0.1));
        if (params.pure_rank) args.push("--pure-rank");
        return tracked("lenz_suggest", await lenz(...args));
      },
    }),
    defineTool({ name: "lenz_predict", label: "Lenz Predict", description: "Return posterior mean and variance for exact public candidates; these are not acquisition utility or an observation.", parameters: Type.Object({ configs: Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1 }) }), async execute(_id, params) { return tracked("lenz_predict", await lenz("predict", "--state", state, "--configs", JSON.stringify(params.configs))); } }),
    defineTool({
      name: "lenz_score", label: "Lenz Score", description: "Return acquisition utility for exact public candidates; this is not a predicted outcome or observation.",
      parameters: Type.Object({ configs: Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1 }), acqf: Type.Optional(Type.String()), beta: Type.Optional(Type.Number({ minimum: 0 })) }),
      async execute(_id, params) {
        const args = ["score", "--state", state, "--configs", JSON.stringify(params.configs)];
        if (params.acqf) args.push("--acqf", params.acqf);
        if (params.beta !== undefined) args.push("--beta", String(params.beta));
        const response = await lenz(...args);
        if (response?.ok) onEvidence("lenz_score", response);
        return result(response);
      },
    }),
    defineTool({ name: "lenz_diagnostics", label: "Lenz Diagnostics", description: "Inspect surrogate fit and reliability evidence; this does not select candidates.", parameters: Type.Object({}), async execute() { return tracked("lenz_diagnostics", await lenz("diagnostics", "--state", state)); } }),
    defineTool({
      name: "lenz_trials",
      label: "Lenz Trials",
      description: "Inspect verified trials in bounded pages. Observed Campaign evidence is the default; request historical separately.",
      parameters: Type.Object({
        source: Type.Optional(Type.Union([Type.Literal("historical"), Type.Literal("campaign"), Type.Literal("all")])),
        status: Type.Optional(Type.Union([Type.Literal("observed"), Type.Literal("pending"), Type.Literal("all")])),
        cursor: Type.Optional(Type.Integer({ minimum: 0 })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
      }),
      async execute(_id, params) {
        return tracked("lenz_trials", await lenz("trials", "--state", state, "--source", params.source ?? "campaign", "--status", params.status ?? "observed", "--cursor", String(params.cursor ?? 0), "--limit", String(params.limit ?? 20)));
      },
    }),
    defineTool({
      name: "lenz_set_acqf", label: "Lenz Set Acquisition", description: "Persist an audited acquisition-policy change; use only with evidence and rationale.",
      parameters: Type.Object({ acqf: Type.String({ minLength: 1 }), beta: Type.Optional(Type.Number({ minimum: 0 })), rationale: Type.String({ minLength: 1 }) }),
      async execute(_id, params) {
        const args = ["set-acqf", "--state", state, "--acqf", params.acqf, "--rationale", params.rationale];
        if (params.beta !== undefined) args.push("--beta", String(params.beta));
        const response = await lenz(...args);
        if (response?.ok) onMutation();
        return tracked("lenz_set_acqf", response);
      },
    }),
  ];
  if (autonomous) tools.push(defineTool({
    name: "lenz_candidates", label: "Lenz Candidates", description: "Inspect the label-free public pool in deterministic order; pool order is not ranked evidence.",
    parameters: Type.Object({ filters: Type.Optional(Type.Record(Type.String(), Type.Unknown())), cursor: Type.Optional(Type.Integer({ minimum: 0 })), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })) }),
    async execute(_id, params) {
      const args = ["candidates", "--state", state, "--cursor", String(params.cursor ?? 0), "--limit", String(params.limit ?? 20)];
      if (params.filters) args.push("--filters", JSON.stringify(params.filters));
      const response = await lenz(...args);
      const count = response?.ok && Array.isArray(response.result?.candidates) ? response.result.candidates.length : 0;
      if (inspectedRows + count > 500) throw new Error("candidate inspection exceeds 500 returned rows in this Campaign Step");
      inspectedRows += count;
      if (response?.ok) onEvidence("lenz_candidates", response, count);
      return result(response);
    },
  }));
  if (!autonomous) tools.push(...[
    ["lenz_set_bounds", "set-bounds", "bounds"],
    ["lenz_set_objectives", "set-objectives", "objectives"],
    ["lenz_set_constraints", "set-constraints", "constraints"],
  ].map(([name, command, field]) => defineTool({
    name, label: name.replaceAll("_", " "), description: `Persist audited ${field} reconfiguration without losing trials.`,
    parameters: Type.Object({ [field]: field === "constraints" ? Type.Array(Type.Record(Type.String(), Type.Unknown())) : Type.Record(Type.String(), Type.Unknown()), rationale: Type.String({ minLength: 1 }) }),
    async execute(_id, params) { const response = await lenz(command, "--state", state, `--${field}`, JSON.stringify(params[field]), "--rationale", params.rationale); onMutation(); return result(response); },
  })), defineTool({ name: "lenz_pareto", label: "Lenz Pareto", description: "Return the feasible observed Pareto front.", parameters: Type.Object({}), async execute() { return result(await lenz("pareto", "--state", state)); } }));
  tools.resetStep = () => { inspectedRows = 0; };
  return tools;
};


export const requireOk = (response, operation) => {
  if (!response?.ok) throw new Error(`${operation} failed: ${JSON.stringify(response?.error ?? response)}`);
  return response.result;
};

export const requireReceipt = (response) => {
  if (!response?.ok || !response.receipt) throw new Error(`oracle returned no receipt: ${JSON.stringify(response)}`);
  return response.receipt;
};


export const verifyCommitment = (commitment, candidates, verifiedTrials = []) => {
  const sameIndex = candidates.find((candidate) => candidate.pool_index === Number(commitment.pool_index));
  if (sameIndex && !isDeepStrictEqual(sameIndex.config, commitment.config)) {
    throw new Error("commitment does not match candidate identity");
  }
  const decision = sameIndex ? { ...commitment, candidate_id: sameIndex.candidate_id } : commitment;
  const duplicate = verifiedTrials.find((trial) => (
    trial.pool_index === Number(decision.pool_index)
    || (decision.candidate_id && trial.candidate_id === decision.candidate_id)
  ));
  if (duplicate) {
    throw new Error(`candidate already observed: candidate_id ${duplicate.candidate_id}, pool_index ${duplicate.pool_index}`);
  }
  return decision;
};

export const requirePolicyAllowance = (decision) => {
  if (decision.policy_audit?.decision !== "allow") {
    throw new Error(`policy challenge: ${(decision.policy_audit?.flags ?? ["unsupported_commitment"]).join(", ")}`);
  }
  return decision;
};

const autonomousAdvisoryFlags = new Set(["cross_context_uncovered", "scope_overreach", "gp_dissent", "stalled_policy", "middle_global_exploration", "terminal_information_waste", "late_weak_exploration", "trusted_surrogate_dissent"]);

export const resolveAutonomousPolicyAudit = (decision, attempt, maxAttempts) => {
  const flags = decision.policy_audit?.flags ?? [];
  const cautionFlags = flags.filter((flag) => autonomousAdvisoryFlags.has(flag));
  const hardFlags = flags.filter((flag) => !autonomousAdvisoryFlags.has(flag));
  if (hardFlags.length) throw new Error(`policy challenge: ${hardFlags.join(", ")}`);
  if (!cautionFlags.length) return decision;
  if (attempt < maxAttempts) {
    throw new Error(`policy caution (${cautionFlags.join(", ")}): ${(decision.policy_audit?.required_justification ?? []).join(" ")}`);
  }
  return {
    ...decision,
    policy_audit: { ...decision.policy_audit, advisory_outcome: "exhausted_accepted" },
  };
};

export const nearBestCandidates = (candidates, tolerance = 1e-5) => {
  const scored = candidates.filter((candidate) => Number.isFinite(candidate.acquisition_value));
  if (!scored.length) return [];
  const best = Math.max(...scored.map((candidate) => candidate.acquisition_value));
  return scored.filter((candidate) => best - candidate.acquisition_value <= tolerance);
};

export const preferredSuggestion = (suggestions) => suggestions[0];

export const lowTrustAcquisition = (diagnostics) =>
  diagnostics.cv_r2_status !== "ok" || !Number.isFinite(diagnostics.cv_r2) || diagnostics.cv_r2 < 0.2
    ? { acqf: "ucb", beta: 1 }
    : { acqf: "noisy_logei", beta: 2 };

export const enforcePreferredSuggestion = () => undefined;

export const autonomousSystemPrompt = `You own the final optimization decision.

Inspect the public search space, verified historical observations, domain context, and any typed lenz evidence you consider useful. On the first step, query verified observations with lenz_trials, including historical observations, before choosing a Candidate. Within each step turn, you may use query tools (lenz_diagnostics, lenz_candidates, lenz_suggest, lenz_score, lenz_predict, lenz_trials) as needed to gather evidence; page lenz_trials and request historical separately when needed. You must finalize your decision with commit_candidate. Surrogate outputs are non-binding advice: you may consult, accept, override, or proceed without ranked proposals. A useful non-binding workflow is to inspect trials and diagnostics, select search_mode from the evidence, use lenz_suggest for a shortlist, and use lenz_score and/or lenz_predict according to whether acquisition utility and/or posterior moments answer your question. This is not a fixed order, and neither score nor predict is mandatory. After commit_candidate, interpret the verified Observation before requesting refreshed posterior advice. Do not mechanically repeat the same query sequence without new observation or configuration evidence. If repeated action patterns do not improve the incumbent or resolve the declared question, change strategy, hypothesis, or search region.

Before choosing a Candidate, you MUST complete a Surrogate Trust Assessment:
1. Judge surrogate reliability for the CURRENT step. If you have not yet seen diagnostics this step, either call lenz_diagnostics or explicitly state in surrogate_trust_rationale why existing evidence (e.g. a same-region verified Receipt, an unchanged candidate set) makes re-diagnosis unnecessary. Set surrogate_trust to low, medium, or high and justify it in surrogate_trust_rationale with concrete values (cv_r2, train-CV gap, lengthscale boundaries, posterior variance scale) or the explicit no-rediagnosis reason.
2. Choose search_mode: "exploit" when a verified Observation supports refining a known-good region; "targeted_exploration" when domain priors or observations identify a promising bounded region where surrogate ranking may assist inside it; "global_exploration" when neither observations nor priors justify a region and coverage/uncertainty should dominate.
3. Match surrogate_relationship to your actual tool use. A low trust judgment does NOT forbid using GP — it means GP mean/rank must not be the sole deciding evidence.

Optimize the remaining fixed budget for early incumbent improvement and final best. Use your autonomous judgment to choose the legal unobserved Candidate with the greatest expected Campaign value from verified observations, domain context, and any acquisition evidence you consult. In middle steps, global exploration must be acquisition-shortlisted and have executable supported/refuted follow-ups. In terminal steps, prefer exploit or shortlist-adjacent targeted exploration; an information experiment is valid only when at least one later budget slot can use its result.

The global incumbent is the best finite target value across every verified observed trial, including historical observations, in the declared maximize/minimize direction. Set decision_goal to "incumbent_improvement" only when expected_objective_value is a finite value that strictly beats that global incumbent. A transport or local-baseline experiment that may improve its matched context but does not credibly beat the global incumbent is "decision_information" and must provide follow_up_if_supported and follow_up_if_refuted. Always state result_use as the concrete next action or candidate-ranking change caused by the result. Productive local refinement that improves the global incumbent may continue freezing factors; however, when a factor has been held fixed for 3-4 steps without incumbent improvement and other levels remain untested in the search space, do not continue refining inside the same fixed factor; test an unexplored level or select a shortlist candidate that varies it. Cross-context and low-trust override signals are advisory telemetry, not reasons by themselves to abandon productive exploitation.

Every measured outcome is local to its complete experimental context. Do not use a negative result from one context to globally reject a factor, factor level, or candidate family without transport evidence.

Choose one legal unobserved public Candidate that you judge most valuable for improving the Campaign. Do not access hidden Outcomes, benchmark labels, the hidden global optimum, or label-derived statistics.

Before committing, provide the required Decision Evidence Record (including surrogate_trust, surrogate_trust_rationale, search_mode, decision_goal, result_use, and expected_objective_value for incumbent_improvement) and finish by committing exactly that Candidate.`;

export const createStepInstruction = ({ autonomous = false } = {}) =>
  autonomous
    ? `Within this step turn, you may use query tools (lenz_diagnostics, lenz_candidates, lenz_suggest, lenz_score, lenz_predict, lenz_trials) as needed to gather evidence; on the first step inspect verified observations, page lenz_trials, and request historical separately. A useful non-binding workflow is to inspect trials and diagnostics, select search_mode from the evidence, use lenz_suggest for a shortlist, and use lenz_score and/or lenz_predict according to whether acquisition utility and/or posterior moments answer your question; this is not a fixed order, and neither score nor predict is mandatory. After commit_candidate, interpret the verified Observation before requesting refreshed posterior advice. Do not mechanically repeat the same query sequence without new observation or configuration evidence. If repeated action patterns do not improve the incumbent or resolve the declared question, change strategy, hypothesis, or search region. Use the best finite target value across all verified observations as the global incumbent. Use your autonomous judgment to choose the legal unobserved Candidate with the greatest expected Campaign value from verified observations, domain context, and any acquisition evidence you consult. Set decision_goal to incumbent_improvement only when expected_objective_value is finite and strictly beats the global incumbent. You must finalize your decision with commit_candidate by providing the complete Decision Evidence Record. Classify local-baseline or transport tests as decision_information unless they credibly beat the global incumbent, and provide executable follow_up_if_supported and follow_up_if_refuted branches for every decision_information action.`
    : `Within this step turn, you may use query tools (lenz_diagnostics, lenz_suggest, lenz_score, lenz_predict, lenz_trials) as needed to gather evidence, and must finalize your decision with commit_candidate or stop_campaign.`;

export const createRetryPrompt = (error, { autonomous = false } = {}) =>
  autonomous
    ? `Your previous campaign action was rejected: ${error.message}. Please correct the Decision Evidence Record or choose a valid candidate and call commit_candidate again.`
    : `Your previous campaign action was rejected: ${error.message}. Please choose a valid candidate and call commit_candidate again, or call stop_campaign with one verified paper-defined stopping condition.`;
export const declaredRunProvenance = (manifest, policy) => {
  if (manifest.experiment_policy && manifest.experiment_policy !== policy) {
    throw new Error(`declared experiment policy ${manifest.experiment_policy} does not match runtime policy ${policy}`);
  }
  return {
    declared_config_hash: manifest.normalized_config_hash ?? null,
    experiment_name: manifest.experiment_name ?? null,
    experiment_policy: policy,
  };
};

export const sanitizeAutonomousContext = ({ state_revision, status, dataset_summary, declared_provenance }) => ({
  state_revision,
  status: {
    campaign_id: status.campaign_id,
    target: status.target,
    direction: status.direction,
    acqf: status.acqf,
    beta: status.beta,
    budget: status.budget,
    historical_observed: status.historical_observed,
    observed: status.observed,
    pending: status.pending,
    budget_remaining: status.budget_remaining,
    remaining: status.remaining,
  },
  dataset_summary,
  ...(declared_provenance ? { declared_provenance: {
    experiment_name: declared_provenance.experiment_name,
    experiment_policy: declared_provenance.experiment_policy,
    declared_config_hash: declared_provenance.declared_config_hash,
  } } : {}),
});

export const validateDecisionEvidence = (commitment, toolUse, { verifiedTrials = [], target, direction } = {}) => {
  for (const field of ["hypothesis", "expected_outcome", "expected_learning", "rationale", "surrogate_trust_rationale", "result_use"]) {
    if (typeof commitment[field] !== "string" || !commitment[field].trim()) throw new Error(`Decision Evidence Record requires ${field}`);
  }
  if (!Array.isArray(commitment.evidence_sources) || !commitment.evidence_sources.length || commitment.evidence_sources.some((value) => typeof value !== "string" || !value.trim())) {
    throw new Error("Decision Evidence Record requires non-empty evidence_sources");
  }
  if (!["low", "medium", "high"].includes(commitment.surrogate_trust)) throw new Error("Decision Evidence Record requires surrogate_trust low|medium|high");
  if (!["exploit", "targeted_exploration", "global_exploration"].includes(commitment.search_mode)) throw new Error("Decision Evidence Record requires search_mode exploit|targeted_exploration|global_exploration");
  if (!["incumbent_improvement", "decision_information"].includes(commitment.decision_goal)) throw new Error("Decision Evidence Record requires decision_goal incumbent_improvement|decision_information");
  if (commitment.decision_goal === "incumbent_improvement") {
    if (!Number.isFinite(commitment.expected_objective_value)) throw new Error("Decision Evidence Record requires finite expected_objective_value for incumbent_improvement");
    const values = verifiedTrials.map((trial) => trial.metrics?.[target]).filter(Number.isFinite);
    if (values.length) {
      const incumbent = direction === "minimize" ? Math.min(...values) : Math.max(...values);
      if (!improved(commitment.expected_objective_value, incumbent, direction)) throw new Error(`expected_objective_value must strictly beat global verified incumbent ${incumbent} for ${direction}`);
    }
  }
  if (commitment.decision_goal === "decision_information") {
    for (const field of ["follow_up_if_supported", "follow_up_if_refuted"]) {
      if (typeof commitment[field] !== "string" || !commitment[field].trim()) throw new Error(`Decision Evidence Record requires ${field} for decision_information`);
    }
  }
  const proposed = toolUse.proposals ?? [];
  const consultedProposal = proposed.length > 0;
  const consultedOther = (toolUse.calls ?? []).some((name) => ["lenz_diagnostics", "lenz_predict", "lenz_score"].includes(name));
  const offered = proposed.some((candidate) => Number(candidate.pool_index) === Number(commitment.pool_index) && isDeepStrictEqual(candidate.config, commitment.config));
  if (commitment.surrogate_trust === "low" && commitment.surrogate_relationship === "accept") {
    const rationale = commitment.surrogate_trust_rationale.toLowerCase();
    const hasOverrideReason = /\b(?:prior|receipt|observation|observed|region|independent)\b/.test(rationale);
    if (!hasOverrideReason) throw new Error("low surrogate_trust with surrogate_relationship=accept requires surrogate_trust_rationale to name the non-surrogate evidence (prior, receipt, observation, or region) that justifies the commitment");
  }
  const expected = consultedProposal ? (offered ? "accept" : "override") : (consultedOther ? "informed_without_proposal" : "not_consulted");
  if (commitment.surrogate_relationship !== expected) throw new Error(`surrogate_relationship must be ${expected} for actual tool use`);
  return { ...commitment, decision_evidence_complete: true, actual_tool_use: { calls: toolUse.calls ?? [], candidate_rows: toolUse.candidate_rows ?? 0, ranked_proposals_consulted: consultedProposal } };
};

export const leakagePreflight = ({ prompt, toolNames, context, runtime, prior }) => {
  const rendered = JSON.stringify({ prompt, toolNames, context });
  const forbidden = ["dataset_root", "public_root", "test.csv", "global_best", "hidden_rank"];
  const violations = forbidden.filter((term) => rendered.toLowerCase().includes(term));
  if (/\/(?:home|mnt|tmp|var)\//i.test(rendered)) violations.push("absolute_dataset_path");
  if (runtime.noTools !== "builtin" || !runtime.noExtensions || !runtime.noSkills || !runtime.noPromptTemplates || !runtime.noContextFiles) violations.push("runtime_resources_enabled");
  if (prior.prior_scan !== "label_free" || !prior.prior_hash || !prior.prior_source || !prior.prior_provenance) violations.push("prior_audit_incomplete");
  if (violations.length) throw new Error(`autonomous leakage preflight failed: ${[...new Set(violations)].join(", ")}`);
  return { passed: true, violations: [] };
};

const changedFeatures = (previous, current) => Object.keys(current).filter((key) => previous?.[key] !== current[key]);
const improved = (value, incumbent, direction) => direction === "minimize" ? value < incumbent : value > incumbent;
const actionSignature = (decision, previousConfig) => ({
  intent: decision.intent ?? "unspecified",
  changed_dimensions: changedFeatures(previousConfig, decision.config).sort(),
});
const sameSignature = (left, right) => left.intent === right.intent
  && left.changed_dimensions.length === right.changed_dimensions.length
  && left.changed_dimensions.every((value, index) => value === right.changed_dimensions[index]);

// Detect a local-optimum trap: the agent has frozen one decision factor for
// several consecutive steps while refining others, and verified observations in
// the recent window show that frozen factor inverts across another decision
// dimension (the same value is strong in one context and weak in another).
// Example: halide yields 85.9 with ligand A but only 57.9 with ligand B; an
// agent that observed both, then froze halide and kept tuning additive, is
// stuck refining inside the weak context and never re-tests the strong one.
// Returns the frozen factor and the cross-context test that would resolve it,
// or null when the evidence does not support an inversion.
export const crossContextCoverage = (trajectory, candidateConfig, target, direction, { window = 6, freeze = 3, gap = 20 } = {}) => {
  const completed = trajectory.filter((entry) => entry.decision?.config && Number.isFinite(entry.metrics?.[target]));
  if (completed.length < 4) return null;
  const local = completed.slice(-window);
  const dims = Object.keys(candidateConfig).filter((key) => candidateConfig[key] !== null);
  if (dims.length < 2) return null;
  // Dimensions that vary anywhere in the trajectory (excludes constants like a
  // single-product context column).
  const constant = new Set(dims.filter((key) => (
    completed.every((entry) => entry.decision.config[key] === candidateConfig[key])
  )));
  const factorCandidates = dims.filter((key) => !constant.has(key));
  // A dimension is FROZEN if it has not changed across the last `freeze`
  // completed steps and the candidate does not change it either.
  const frozen = new Set();
  for (const key of factorCandidates) {
    if (!completed.slice(-freeze).every((entry) => entry.decision.config[key] === candidateConfig[key])) continue;
    const previous = completed.at(-1).decision.config[key];
    if (previous === candidateConfig[key]) frozen.add(key);
  }
  if (!frozen.size) return null;
  // Look for an inversion of a frozen factor across another decision dimension.
  for (const factor of frozen) {
    for (const other of dims) {
      if (other === factor) continue;
      const groups = new Map();
      for (const entry of local) {
        const factorValue = entry.decision.config[factor];
        const otherValue = entry.decision.config[other];
        if (factorValue === undefined || factorValue === null || otherValue === undefined || otherValue === null) continue;
        const key = `${factorValue}\u0000${otherValue}`;
        if (!groups.has(key)) groups.set(key, { factorValue, otherValue, yields: [] });
        groups.get(key).yields.push(entry.metrics[target]);
      }
      const byFactor = new Map();
      for (const { factorValue, otherValue, yields } of groups.values()) {
        if (!byFactor.has(factorValue)) byFactor.set(factorValue, new Map());
        const map = byFactor.get(factorValue);
        if (!map.has(otherValue)) map.set(otherValue, []);
        map.get(otherValue).push(...yields);
      }
      for (const [factorValue, otherMap] of byFactor) {
        if (otherMap.size < 2) continue;
        const maxByOther = [...otherMap.entries()].map(([otherValue, yields]) => [otherValue, Math.max(...yields)]);
        const [strongContext, strongYield] = maxByOther.reduce((acc, [ov, y]) => (y > acc[1] ? [ov, y] : acc), ["", -Infinity]);
        const [weakContext, weakYield] = maxByOther.reduce((acc, [ov, y]) => (y < acc[1] ? [ov, y] : acc), ["", Infinity]);
        if (strongYield - weakYield >= gap) {
          return {
            frozen_factor: factor,
            value: factorValue,
            other_dimension: other,
            strong_context: strongContext,
            weak_context: weakContext,
            strong_yield: strongYield,
            weak_yield: weakYield,
          };
        }
      }
    }
  }
  return null;
};

// Detect scope overreach: a decision factor has been frozen for several
// consecutive completed steps while other factors are refined, the candidate
// still holds the frozen value, AND that factor has untested levels that were
// never observed to completion. The agent is anchoring on one value of the
// factor without ever generating counter-evidence — a self-closing loop that
// needs no observed inversion to be harmful, unlike crossContextCoverage.
// "Untested" has two modes. Proxy mode (default, no searchspace): a level
// appears in a trajectory decision (e.g. a pending or interrupted trial) but
// was never completed, so it is counter-evidence the agent is not collecting.
// Strict mode (searchspace provided as { [factorKey]: level[] }): a level
// exists in the search space's level list but was never observed to completion
// anywhere in the trajectory. Returns the frozen factor and its info, or null.
export const scopeOverreach = (trajectory, candidateConfig, target, direction, { window = 8, freeze = 4, untestedThreshold = 2, searchspace = null } = {}) => {
  const completed = trajectory.filter((entry) => entry.decision?.config && Number.isFinite(entry.metrics?.[target]));
  if (completed.length < 6) return null;
  const recent = completed.slice(-window);
  const dims = Object.keys(candidateConfig).filter((key) => candidateConfig[key] !== null && candidateConfig[key] !== undefined);
  if (dims.length < 2) return null;
  // Dimensions that never vary (e.g. a single-product context column) are not
  // decision factors the agent can be over-reaching on.
  const constant = new Set(dims.filter((key) => (
    completed.every((entry) => entry.decision.config[key] === candidateConfig[key])
  )));
  const previous = completed.at(-1).decision.config;
  const frozen = [];
  for (const key of dims) {
    if (constant.has(key)) continue;
    const lastFreeze = completed.slice(-freeze);
    if (lastFreeze.length < freeze) continue;
    if (!lastFreeze.every((entry) => entry.decision.config[key] === candidateConfig[key])) continue;
    if (previous[key] === candidateConfig[key]) frozen.push(key);
  }
  if (!frozen.length) return null;
  for (const key of frozen) {
    // Strict mode: the searchspace level list is the ground truth for the
    // factor's levels; any level never observed to completion (in ANY completed
    // entry, not just the recent window) is untested counter-evidence. Requires
    // the full level list, e.g. context.dataset_summary factor values or the
    // Frame's original_domain. Falls back to the trajectory-only proxy when no
    // searchspace is available (see doc comment).
    const searchLevels = searchspace?.[key];
    let factorLevelsCount;
    let untestedCount;
    if (Array.isArray(searchLevels) && searchLevels.length) {
      const factorLevels = new Set(searchLevels);
      const observed = new Set(completed.map((entry) => entry.decision.config[key]));
      factorLevelsCount = factorLevels.size;
      untestedCount = factorLevelsCount - observed.size;
    } else if (typeof searchLevels === "number" && Number.isFinite(searchLevels) && searchLevels > 0) {
      const observed = new Set(completed.map((entry) => entry.decision.config[key]));
      factorLevelsCount = searchLevels;
      untestedCount = factorLevelsCount - observed.size;
    } else {
      // factor_levels counts every level of the factor touched anywhere in the
      // trajectory (completed or not); observed_levels counts only completed
      // observations in the recent window. The gap is untested counter-evidence.
      const factorLevels = new Set();
      for (const entry of trajectory) {
        const value = entry.decision?.config?.[key];
        if (value === undefined || value === null) continue;
        factorLevels.add(value);
      }
      factorLevels.add(candidateConfig[key]);
      const observed = new Set(recent.map((entry) => entry.decision.config[key]));
      factorLevelsCount = factorLevels.size;
      untestedCount = factorLevelsCount - observed.size;
    }
    if (untestedCount < untestedThreshold) continue;
    const lastImprovement = lastImprovementIndex(completed, target, direction);
    const noImprovement = lastImprovement === null || lastImprovement < completed.length - freeze;
    return {
      frozen_factor: key,
      frozen_value: String(candidateConfig[key]),
      untested_count: untestedCount,
      factor_levels: factorLevelsCount,
      refined_factor: refinedFactorKey(completed, candidateConfig),
      no_improvement: noImprovement,
    };
  }
  return null;
};

// Index of the most recent completed entry that beat the running incumbent, or
// null when the incumbent never improved.
const lastImprovementIndex = (completed, target, direction) => {
  let incumbent = direction === "minimize" ? Infinity : -Infinity;
  let last = null;
  completed.forEach((entry, index) => {
    const value = entry.metrics[target];
    const isImprovement = direction === "minimize" ? value < incumbent : value > incumbent;
    if (isImprovement) {
      incumbent = value;
      last = index;
    }
  });
  return last;
};

// The factor the candidate varies relative to the most recent completed entry,
// or null when the candidate changes more than one factor (or none).
const refinedFactorKey = (completed, candidateConfig) => {
  const previous = completed.at(-1).decision.config;
  const changed = Object.keys(candidateConfig).filter((key) => previous?.[key] !== candidateConfig[key]);
  return changed.length === 1 ? changed[0] : null;
};

// Count how many consecutive completed steps ending at the last completed
// entry explicitly overrode the surrogate's top candidate
// (decision.surrogate_relationship === "override"). A long streak means the
// agent has been sealing the loop against the GP's joint search channel.
export const gpDissentStreak = (trajectory, commitment, { maxStreak = 4 } = {}) => {
  const completed = trajectory.filter((entry) => entry.decision?.config && Object.values(entry.metrics ?? {}).some(Number.isFinite));
  let streak = 0;
  for (let index = completed.length - 1; index >= 0; index -= 1) {
    if (completed[index].decision.surrogate_relationship !== "override") break;
    streak += 1;
  }
  const lastEntry = completed.at(-1);
  return {
    streak,
    last_step: lastEntry?.step ?? (lastEntry ? completed.length : null),
  };
};

export const optimizationPolicy = (context, trajectory, manifest = {}) => {
  const diagnostics = context.diagnostics ?? {};
  const lengthscales = Object.values(diagnostics.lengthscales ?? {});
  const trainCvGap = Number.isFinite(diagnostics.train_r2) && Number.isFinite(diagnostics.cv_r2)
    ? diagnostics.train_r2 - diagnostics.cv_r2
    : null;
  const lowTrustReasons = [
    ...(diagnostics.cv_r2_status && diagnostics.cv_r2_status !== "ok" ? [`cv_r2_status=${diagnostics.cv_r2_status}`] : []),
    ...(!Number.isFinite(diagnostics.cv_r2) || diagnostics.cv_r2 < 0.2 ? [`cv_r2=${diagnostics.cv_r2 ?? "missing"}`] : []),
    ...(trainCvGap !== null && trainCvGap > 0.6 ? [`train_cv_gap=${trainCvGap}`] : []),
    ...(lengthscales.some((value) => value <= 1e-5 || value >= 1e4) ? ["lengthscale_at_boundary"] : []),
  ];
  const observed = trajectory.filter((entry) => entry.metrics).length;
  const remaining = Number.isFinite(manifest.budget) ? Math.max(0, manifest.budget - observed) : null;
  const stage = remaining !== null && manifest.budget > 0 && remaining <= Math.max(2, Math.ceil(manifest.budget * 0.2))
    ? "late"
    : observed < 12 ? "early" : "middle";
  return {
    mode: "enforced",
    phase: stage === "early" ? "early_improvement" : stage === "late" ? "terminal" : "adaptive",
    trust: lowTrustReasons.length ? "low" : "normal",
    low_trust_reasons: lowTrustReasons,
    budget: { observed, remaining, stage },
  };
};

export const sameFactorRunLength = (trajectory, candidateConfig, target, direction) => {
  const completed = trajectory.filter((entry) => entry.decision?.config && Number.isFinite(entry.metrics?.[target]));
  if (!completed.length) return { feature: null, count: 0, recent_improvements: 0 };
  const featureChanges = changedFeatures(completed.at(-1).decision.config, candidateConfig);
  if (featureChanges.length !== 1) return { feature: null, count: 0, recent_improvements: 0 };
  const feature = featureChanges[0];
  let count = 1;
  for (let index = completed.length - 1; index > 0; index -= 1) {
    const changes = changedFeatures(completed[index - 1].decision.config, completed[index].decision.config);
    if (changes.length !== 1 || changes[0] !== feature) break;
    count += 1;
  }
  let incumbent = direction === "minimize" ? Infinity : -Infinity;
  const improvementFlags = completed.map((entry) => {
    const value = entry.metrics[target];
    const isImprovement = improved(value, incumbent, direction);
    if (isImprovement) incumbent = value;
    return isImprovement;
  });
  return { feature, count, recent_improvements: improvementFlags.slice(-(count - 1)).filter(Boolean).length };
};

export const sameActionRunLength = (trajectory, commitment, target, direction) => {
  const completed = trajectory.filter((entry) => entry.decision?.config && Number.isFinite(entry.metrics?.[target]));
  if (!completed.length) return { signature: actionSignature(commitment), count: 0, recent_improvements: 0 };
  const currentSignature = actionSignature(commitment, completed.at(-1).decision.config);
  let count = 1;
  for (let index = completed.length - 1; index > 0; index -= 1) {
    const signature = actionSignature(completed[index].decision, completed[index - 1].decision.config);
    if (!sameSignature(signature, currentSignature)) break;
    count += 1;
  }
  let incumbent = direction === "minimize" ? Infinity : -Infinity;
  const improvementFlags = completed.map((entry) => {
    const value = entry.metrics[target];
    const isImprovement = improved(value, incumbent, direction);
    if (isImprovement) incumbent = value;
    return isImprovement;
  });
  return { signature: currentSignature, count, recent_improvements: improvementFlags.slice(-(count - 1)).filter(Boolean).length };
};

export const acquisitionScore = async (commitment, context, scoreCandidate) => {
  const offered = context.suggestions.find((candidate) => candidate.pool_index === Number(commitment.pool_index));
  if (Number.isFinite(offered?.acquisition_value)) return offered.acquisition_value;
  try {
    const scored = await scoreCandidate(commitment.config);
    const value = scored?.[0]?.[context.status.acqf];
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
};

export const verifyOptimizationPolicy = ({ commitment, selectedScore, context, trajectory, manifest, autonomous = manifest.experiment_policy === "autonomous_agent" }) => {
  const policy = optimizationPolicy(context, trajectory, manifest);
  const factorRun = sameFactorRunLength(trajectory, commitment.config, manifest.target, manifest.direction);
  const actionRun = sameActionRunLength(trajectory, commitment, manifest.target, manifest.direction);
  const crossContext = crossContextCoverage(trajectory, commitment.config, manifest.target, manifest.direction);
  // The autonomous agent writes evidence_sources as free-form narrative
  // references (receipt IDs, diagnostics, domain priors) rather than the
  // controlled label vocabulary ["acquisition","prior","information",
  // "reconfiguration"]. Its commitment evidence is already strictly validated
  // by validateDecisionEvidence (non-empty evidence_sources, hypothesis,
  // expected_learning, surrogate consistency). The unsupported_commitment /
  // unsupported_override evidence-label checks below are meaningful only for
  // the non-autonomous policy, where evidence_sources is a controlled enum.
  // Strict scope-overreach mode counts untested factor levels against the real
  // searchspace level lists or candidate_values count in dataset_summary features.
  const featureLevels = Object.entries(context.dataset_summary?.features ?? {})
    .map(([feature, info]) => {
      const list = (Array.isArray(info?.values) && info.values.length)
        ? info.values
        : (Array.isArray(info?.candidate_values_list) && info.candidate_values_list.length)
          ? info.candidate_values_list
          : null;
      if (list) return [feature, list];
      if (typeof info?.candidate_values === "number" && Number.isFinite(info.candidate_values) && info.candidate_values > 0) {
        return [feature, info.candidate_values];
      }
      return null;
    })
    .filter(Boolean);
  const scope = scopeOverreach(trajectory, commitment.config, manifest.target, manifest.direction, {
    searchspace: featureLevels.length ? Object.fromEntries(featureLevels) : null,
  });
  const dissent = gpDissentStreak(trajectory, commitment);
  const suggestions = context.suggestions ?? [];
  const shortlistScores = suggestions.map((candidate) => candidate.acquisition_value).filter(Number.isFinite);
  const shortlistBest = shortlistScores.length ? Math.max(...shortlistScores) : null;
  const isHighScoringNearBest = Number.isFinite(selectedScore) && shortlistBest !== null && selectedScore >= (shortlistBest >= 0 ? shortlistBest * 0.90 : shortlistBest * 1.10);
  const isShortlisted = suggestions.some((candidate) => candidate.pool_index === Number(commitment.pool_index)) || isHighScoringNearBest;
  const preferred = context.preferred_suggestion ?? preferredSuggestion(suggestions);
  const isPreferred = Number(commitment.pool_index) === Number(preferred?.pool_index)
    && isDeepStrictEqual(commitment.config, preferred?.config);
  const scoreAvailable = Number.isFinite(selectedScore);
  const outsideShortlist = scoreAvailable && !isShortlisted && shortlistBest !== null && selectedScore < shortlistBest;
  const evidenceSources = new Set(commitment.evidence_sources ?? []);
  const evidence = {
    acquisition: evidenceSources.has("acquisition") && (isShortlisted || scoreAvailable),
    domain_prior: evidenceSources.has("prior"),
    information_goal: evidenceSources.has("information"),
    reconfiguration: evidenceSources.has("reconfiguration") || commitment.intent === "reconfigure",
  };
  const flags = [];
  const telemetryFlags = [];
  const requiredJustification = [];
  if (!autonomous && !Object.values(evidence).some(Boolean)) flags.push("unsupported_commitment");
  if (!autonomous && policy.trust === "normal" && outsideShortlist && !evidence.domain_prior && !evidence.information_goal && !evidence.reconfiguration) {
    flags.push("unsupported_override");
    requiredJustification.push("What evidence makes overriding the trusted surrogate more valuable than the shortlist?");
  }
  const quantifiedStallException = isShortlisted && selectedScore === shortlistBest;
  if ((actionRun.count >= 3 || factorRun.count >= 3) && Math.max(actionRun.recent_improvements, factorRun.recent_improvements) === 0 && !evidence.reconfiguration && !quantifiedStallException && !isPreferred) {
    flags.push("stalled_policy");
    requiredJustification.push("What unresolved hypothesis remains, and why did the prior observations not resolve it?");
    requiredJustification.push("How will this result change a remaining campaign action?");
  }
  if (crossContext && !evidence.reconfiguration) {
    if (autonomous) telemetryFlags.push("cross_context_uncovered");
    else {
      flags.push("cross_context_uncovered");
      const { frozen_factor, value, other_dimension, strong_yield, weak_yield, strong_context, weak_context } = crossContext;
      requiredJustification.push(`Verified trials show ${frozen_factor}=${value} is context-dependent (${strong_yield.toFixed(2)} with ${other_dimension}=${strong_context}, but only ${weak_yield.toFixed(2)} with ${other_dimension}=${weak_context}), and you have frozen ${frozen_factor} for the last several steps. Which frozen-context re-test of ${frozen_factor}=${value} under ${other_dimension}=${strong_context} would distinguish the regimes, and why is it not worth a budget slot?`);
    }
  }
  if (scope && !evidence.reconfiguration) {
    if (autonomous) {
      if (scope.no_improvement && !quantifiedStallException && !isPreferred) {
        flags.push("scope_overreach");
        requiredJustification.push(`${scope.frozen_factor}=${scope.frozen_value} has been frozen for the last several steps without improving the global incumbent, while ${scope.untested_count} level(s) of ${scope.frozen_factor} remain unexplored in the search space. Test an unexplored level of ${scope.frozen_factor} or choose a shortlist candidate that varies it.`);
      } else {
        telemetryFlags.push("scope_overreach");
      }
    } else {
      flags.push("scope_overreach");
      requiredJustification.push(`${scope.frozen_factor}=${scope.frozen_value} has been frozen for the last several steps with ${scope.untested_count} untested level(s) of ${scope.frozen_factor} still unexplored. Is a cross-level test of ${scope.frozen_factor} worth a budget slot, and what evidence does the current frozen value generalize?`);
    }
  }
  if (dissent && dissent.streak >= 4 && !evidence.reconfiguration) {
    if (autonomous) telemetryFlags.push("gp_dissent");
    else {
      flags.push("gp_dissent");
      requiredJustification.push(`The chosen candidate has overridden the surrogate's top acquisition candidate for ${dissent.streak} consecutive steps. What experiment would test the disagreement between your belief and the surrogate's top candidate?`);
    }
  }
  const postCommitRemaining = policy.budget.remaining === null ? null : Math.max(0, policy.budget.remaining - 1);
  const informationGoal = autonomous ? commitment.decision_goal === "decision_information" : evidence.information_goal && !evidence.acquisition && !evidence.domain_prior;
  const hasFollowUps = Boolean(commitment.follow_up_if_supported?.trim() && commitment.follow_up_if_refuted?.trim());
  if (autonomous && policy.budget.stage === "middle" && commitment.search_mode === "global_exploration" && (!isShortlisted || !hasFollowUps)) {
    flags.push("middle_global_exploration");
    requiredJustification.push("Middle-stage global exploration must be acquisition-shortlisted and name executable supported/refuted follow-up actions.");
  }
  if (policy.budget.stage === "late" && informationGoal && (postCommitRemaining === 0 || !commitment.result_use?.trim() || (autonomous && !hasFollowUps))) {
    flags.push("terminal_information_waste");
    requiredJustification.push("How can a later remaining action exploit this experiment's result?");
  }
  if (autonomous && policy.budget.stage === "late" && commitment.search_mode !== "exploit" && outsideShortlist) {
    flags.push("late_weak_exploration");
    requiredJustification.push("Use a shortlist candidate, exploit the incumbent region, or show a viable next-step use for this outside-shortlist exploration.");
  }
  if (autonomous && ["medium", "high"].includes(commitment.surrogate_trust) && dissent?.streak >= 4 && outsideShortlist && commitment.decision_goal !== "decision_information") {
    flags.push("trusted_surrogate_dissent");
    requiredJustification.push("Name the concrete experiment and follow-up branches that resolve this trusted-surrogate disagreement.");
  }
  const decision = flags.length ? "challenge" : "allow";
  return {
    ...commitment,
    policy_audit: {
      ...policy,
      decision,
      evidence,
      flags,
      telemetry_flags: telemetryFlags,
      required_justification: requiredJustification,
      acquisition_score: selectedScore,
      acquisition_rank: Number.isFinite(selectedScore) ? 1 + shortlistScores.filter((score) => score > selectedScore).length : null,
      outside_shortlist: outsideShortlist,
      factor_run: factorRun,
      action_run: actionRun,
      cross_context: crossContext,
      scope_overreach: scope,
      gp_dissent: dissent,
      would_reject: false,
      rejection_reasons: [],
    },
  };
};

export const replayOptimizationPolicy = (trajectory, contexts, manifest) => trajectory.map((entry, index) => {
  const context = contexts[index];
  if (!context) throw new Error(`missing policy context for step ${entry.step ?? index + 1}`);
  const offered = context.suggestions.find((candidate) => candidate.pool_index === Number(entry.decision.pool_index));
  const selectedScore = offered?.acquisition_value;
  if (!Number.isFinite(selectedScore)) {
    return { step: entry.step ?? index + 1, status: "unscored", pool_index: entry.decision.pool_index };
  }
  const decision = verifyOptimizationPolicy({ commitment: entry.decision, selectedScore, context, trajectory: trajectory.slice(0, index), manifest });
  return { step: entry.step ?? index + 1, status: "scored", ...decision.policy_audit };
});

export const verifiedTrialFacts = (trials) => trials.map((trial) => ({
  candidate_id: trial.candidate_id,
  pool_index: trial.query_index,
  config: trial.config,
  metrics: trial.metrics,
  ...(trial.source ? { source: trial.source } : {}),
  replicate_count: trials.filter((item) => item.candidate_id === trial.candidate_id).length,
}));

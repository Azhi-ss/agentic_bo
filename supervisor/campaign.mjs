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

export const createCampaignActionTools = (setAction) => [
  defineTool({
    name: "commit_candidate",
    label: "Commit Candidate",
    description: "Commit exactly one candidate from the current verified public candidate set.",
    parameters: Type.Object({
      pool_index: Type.Integer({ minimum: 0 }),
      config: Type.Record(Type.String(), Type.Unknown()),
      rationale: Type.String({ minLength: 1 }),
      intent: Type.Optional(Type.Union([Type.Literal("optimize"), Type.Literal("discriminate"), Type.Literal("explore"), Type.Literal("reconfigure")])),
      evidence_sources: Type.Optional(Type.Array(Type.Union([Type.Literal("acquisition"), Type.Literal("prior"), Type.Literal("information"), Type.Literal("reconfiguration")]), { minItems: 1 })),
      expected_learning: Type.Optional(Type.String({ minLength: 1 })),
      result_use: Type.Optional(Type.String({ minLength: 1 })),
    }),
    async execute(_id, params) {
      const action = { type: "commit_candidate", ...params };
      setAction(action);
      return { ...result(action), terminate: true };
    },
  }),
  defineTool({
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
  }),
];

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

export const createLenzTools = (lenz, state, onMutation = () => {}) => [
  defineTool({
    name: "lenz_suggest", label: "Lenz Suggest", description: "Generate current surrogate proposals without committing.",
    parameters: Type.Object({ q: Type.Optional(Type.Integer({ minimum: 1, maximum: 20 })), acqf: Type.Optional(Type.String()), beta: Type.Optional(Type.Number({ minimum: 0 })) }),
    async execute(_id, params) {
      const args = ["suggest", "--state", state, "--q", String(params.q ?? 5)];
      if (params.acqf) args.push("--acqf", params.acqf);
      if (params.beta !== undefined) args.push("--beta", String(params.beta));
      return result(await lenz(...args));
    },
  }),
  defineTool({
    name: "lenz_predict", label: "Lenz Predict", description: "Inspect posterior mean and variance for exact public candidates.",
    parameters: Type.Object({ configs: Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1 }) }),
    async execute(_id, params) { return result(await lenz("predict", "--state", state, "--configs", JSON.stringify(params.configs))); },
  }),
  defineTool({
    name: "lenz_score", label: "Lenz Score", description: "Score exact public candidates with an acquisition policy.",
    parameters: Type.Object({ configs: Type.Array(Type.Record(Type.String(), Type.Unknown()), { minItems: 1 }), acqf: Type.Optional(Type.String()), beta: Type.Optional(Type.Number({ minimum: 0 })) }),
    async execute(_id, params) {
      const args = ["score", "--state", state, "--configs", JSON.stringify(params.configs)];
      if (params.acqf) args.push("--acqf", params.acqf);
      if (params.beta !== undefined) args.push("--beta", String(params.beta));
      return result(await lenz(...args));
    },
  }),
  defineTool({
    name: "lenz_diagnostics", label: "Lenz Diagnostics", description: "Inspect current surrogate diagnostics.", parameters: Type.Object({}),
    async execute() { return result(await lenz("diagnostics", "--state", state)); },
  }),
  defineTool({
    name: "lenz_trials", label: "Lenz Trials", description: "Inspect the complete observed trial log, including historical and campaign observations.", parameters: Type.Object({}),
    async execute() { return result(await lenz("trials", "--state", state)); },
  }),
  defineTool({
    name: "lenz_set_acqf", label: "Lenz Set Acquisition", description: "Persist an audited acquisition policy revision.",
    parameters: Type.Object({
      acqf: Type.String({ minLength: 1 }),
      beta: Type.Optional(Type.Number({ minimum: 0 })),
      rationale: Type.String({ minLength: 1 }),
    }),
    async execute(_id, params) {
      const args = ["set-acqf", "--state", state, "--acqf", params.acqf, "--rationale", params.rationale];
      if (params.beta !== undefined) args.push("--beta", String(params.beta));
      const response = await lenz(...args);
      onMutation();
      return result(response);
    },
  }),
];


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

export const nearBestCandidates = (candidates, tolerance = 1e-5) => {
  const scored = candidates.filter((candidate) => Number.isFinite(candidate.acquisition_value));
  if (!scored.length) return [];
  const best = Math.max(...scored.map((candidate) => candidate.acquisition_value));
  return scored.filter((candidate) => best - candidate.acquisition_value <= tolerance);
};

export const preferredSuggestion = (suggestions) => suggestions[0];

export const lowTrustAcquisition = (diagnostics) =>
  diagnostics.cv_r2_status !== "ok" || !Number.isFinite(diagnostics.cv_r2) || diagnostics.cv_r2 < 0.2
    ? { acqf: "ucb", beta: 16 }
    : { acqf: "noisy_logei", beta: 2 };

export const enforcePreferredSuggestion = (commitment, preferred, remaining) => {
  if (remaining <= 1 || !preferred) return;
  if (Number(commitment.pool_index) !== Number(preferred.pool_index) || !isDeepStrictEqual(commitment.config, preferred.config)) {
    throw new Error("commitment must match preferred_suggestion before the terminal evaluation");
  }
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

export const verifyOptimizationPolicy = ({ commitment, selectedScore, context, trajectory, manifest }) => {
  const policy = optimizationPolicy(context, trajectory, manifest);
  const factorRun = sameFactorRunLength(trajectory, commitment.config, manifest.target, manifest.direction);
  const actionRun = sameActionRunLength(trajectory, commitment, manifest.target, manifest.direction);
  const shortlistScores = context.suggestions.map((candidate) => candidate.acquisition_value).filter(Number.isFinite);
  const shortlistBest = shortlistScores.length ? Math.max(...shortlistScores) : null;
  const isShortlisted = context.suggestions.some((candidate) => candidate.pool_index === Number(commitment.pool_index));
  const isPreferred = Number(commitment.pool_index) === Number(context.preferred_suggestion?.pool_index)
    && isDeepStrictEqual(commitment.config, context.preferred_suggestion?.config);
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
  const requiredJustification = [];
  if (!Object.values(evidence).some(Boolean)) flags.push("unsupported_commitment");
  if (policy.trust === "normal" && outsideShortlist && !evidence.domain_prior && !evidence.information_goal && !evidence.reconfiguration) {
    flags.push("unsupported_override");
    requiredJustification.push("What evidence makes overriding the trusted surrogate more valuable than the shortlist?");
  }
  const quantifiedStallException = policy.trust === "normal" && isShortlisted && selectedScore === shortlistBest;
  if ((actionRun.count >= 3 || factorRun.count >= 3) && Math.max(actionRun.recent_improvements, factorRun.recent_improvements) === 0 && !evidence.reconfiguration && !quantifiedStallException && !isPreferred) {
    flags.push("stalled_policy");
    requiredJustification.push("What unresolved hypothesis remains, and why did the prior observations not resolve it?");
    requiredJustification.push("How will this result change a remaining campaign action?");
  }
  const postCommitRemaining = policy.budget.remaining === null ? null : Math.max(0, policy.budget.remaining - 1);
  const informationOnly = evidence.information_goal && !evidence.acquisition && !evidence.domain_prior;
  if (policy.budget.stage === "late" && informationOnly && (postCommitRemaining === 0 || !commitment.result_use?.trim())) {
    flags.push("terminal_information_waste");
    requiredJustification.push("How can the remaining budget exploit the information from this experiment?");
  }
  const decision = flags.length ? "challenge" : "allow";
  return {
    ...commitment,
    policy_audit: {
      ...policy,
      decision,
      evidence,
      flags,
      required_justification: requiredJustification,
      acquisition_score: selectedScore,
      acquisition_rank: Number.isFinite(selectedScore) ? 1 + shortlistScores.filter((score) => score > selectedScore).length : null,
      outside_shortlist: outsideShortlist,
      factor_run: factorRun,
      action_run: actionRun,
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

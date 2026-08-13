import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { fileURLToPath } from "node:url";

import { createAgentSession, DefaultResourceLoader, getAgentDir, ModelRuntime, SessionManager } from "@earendil-works/pi-coding-agent";
import { acquisitionScore, autonomousSystemPrompt, campaignResult, createCampaignActionTools, createLenzTools, createRetryPrompt, createStepInstruction, declaredRunProvenance, enforcePreferredSuggestion, leakagePreflight, lowTrustAcquisition, nearBestCandidates, preferredSuggestion, promptWithTransientRetries, reconcileTrajectory, requireCampaignAction, requireOk, requirePolicyAllowance, requireReceipt, resolveAutonomousPolicyAudit, sanitizeAutonomousContext, validateCampaignStatus, validateDecisionEvidence, verifiedTrialFacts, verifyCommitment, verifyOptimizationPolicy, verifyStop } from "./campaign.mjs";
const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const argv = process.argv.slice(2);
const args = Object.fromEntries(argv.flatMap((item, index) => item.startsWith("--") ? [[item.slice(2), argv[index + 1]]] : []));
const campaign = resolve(args.campaign ?? "runs/campaign");
const manifest = JSON.parse(await readFile(resolve(campaign, "manifest.json"), "utf8"));
const state = resolve(campaign, "frame", "state.json");
const frameAtStartup = JSON.parse(await readFile(state, "utf8"));
const statusPath = resolve(campaign, "campaign-status.json");
const priorStatus = await readFile(statusPath).then((text) => JSON.parse(text), () => undefined);
const terminalStatus = validateCampaignStatus(priorStatus, manifest, frameAtStartup);
if (terminalStatus) {
  console.log(JSON.stringify({ ok: true, campaign, ...terminalStatus }));
  process.exit(0);
}
const receipts = resolve(campaign, "receipts");
await mkdir(receipts, { recursive: true });

const run = (command, commandArgs) => new Promise((accept, reject) => {
  const child = spawn(command, commandArgs, { cwd: campaign, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  child.on("close", (code) => code === 0 ? accept(stdout.trim()) : reject(new Error(`${command} failed (${code}): ${stderr || stdout}`)));
});
const lenz = async (...commandArgs) => JSON.parse(await run("lenz", commandArgs));
const writeJsonAtomic = async (path, value) => {
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(value, null, 2));
  await rename(temporary, path);
};

const sessionFile = resolve(campaign, "pi-session.jsonl");
const priorSession = await readFile(sessionFile, "utf8").catch(() => "");
const priorModel = priorSession.match(/"type":"model_change"[^\n]*"provider":"([^"]+)"[^\n]*"modelId":"([^"]+)"/)?.slice(1);
const provider = "ai-modeling";
const modelId = args.model ?? process.env.BOAGENT_MODEL ?? "gpt-5.6-sol";
const thinking = args.thinking ?? "xhigh";
const policy = args.policy ?? "default";
if (!["default", "autonomous_agent"].includes(policy)) throw new Error(`unknown experiment policy: ${policy}`);
const autonomous = policy === "autonomous_agent";
const defaultSystem = await readFile(resolve(root, "profiles/paper-reproduction/PAPER_SYSTEM.md"), "utf8");
const reference = await readFile(resolve(root, "profiles/paper-reproduction/PAPER_LENZ_REF.md"), "utf8");
const system = autonomous ? autonomousSystemPrompt : defaultSystem;
const hash = (value) => createHash("sha256").update(value).digest("hex");
const codeRevisionHash = async () => {
  const head = (await readFile(resolve(root, ".git/HEAD"), "utf8")).trim();
  if (!head.startsWith("ref: ")) return head;
  return (await readFile(resolve(root, ".git", head.slice(5)), "utf8")).trim();
};
const auditPath = resolve(campaign, "campaign-run-config.json");
const audit = await readFile(auditPath).then((text) => JSON.parse(text), () => ({ revisions: [] }));
const renderedSystem = autonomous ? system : [system, reference].join("\n\n---\n\n");
const runConfig = { campaign_id: manifest.campaign_id, provider, model: modelId, thinking, policy, ...declaredRunProvenance(manifest, policy), system_prompt_hash: hash(system), reference_hash: autonomous ? null : hash(reference), prompt_hash: hash(renderedSystem), prior_hash: manifest.prior_hash, prior_source: manifest.prior_source, prior_scan: manifest.prior_scan, prior_provenance: manifest.prior_provenance, provider_generation_seed: "unavailable", code_revision_hash: await codeRevisionHash() };
runConfig.config_hash = hash(JSON.stringify(runConfig));
let campaignAction;
let turnMutated = false;
let turnEvidence = { calls: [], proposals: [], candidate_rows: 0 };
const actionTools = createCampaignActionTools((action) => { campaignAction = action; turnMutated = true; }, { autonomous });
const lenzTools = createLenzTools(lenz, state, () => { turnMutated = true; }, (name, response, rows = 0) => {
  turnEvidence.calls.push(name);
  turnEvidence.candidate_rows += rows;
  if (name === "lenz_suggest" && response?.ok && Array.isArray(response.result)) turnEvidence.proposals.push(...response.result);
}, { autonomous });
const loader = new DefaultResourceLoader({
  cwd: campaign,
  agentDir: getAgentDir(),
  systemPromptOverride: () => renderedSystem,
  noExtensions: true,
  noSkills: true,
  noPromptTemplates: true,
  noThemes: true,
  noContextFiles: true,
});
await loader.reload();

const defaultToolContext = async () => {
  const status = await lenz("status", "--state", state);
  const suggestions = await lenz("suggest", "--state", state, "--q", "20");
  const diagnostics = await lenz("diagnostics", "--state", state);
  const trials = await lenz("trials", "--state", state);
  const offered = requireOk(suggestions, "suggest");
  return {
    state_revision: status.state_revision,
    status: requireOk(status, "status"),
    suggestions: offered,
    near_best_suggestions: nearBestCandidates(offered),
    preferred_suggestion: preferredSuggestion(offered),
    diagnostics: requireOk(diagnostics, "diagnostics"),
    verified_trials: verifiedTrialFacts(requireOk(trials, "trials")),
    effective_manifest: { campaign_id: manifest.campaign_id, seed: manifest.seed, budget: manifest.budget, target: status.result.target, direction: status.result.direction, ...(manifest.experiment_name ? { experiment_name: manifest.experiment_name } : {}), ...(manifest.experiment_policy ? { experiment_policy: manifest.experiment_policy } : {}), ...(manifest.normalized_config_hash ? { declared_config_hash: manifest.normalized_config_hash } : {}) },
  };
};
const toolContext = async () => {
  if (!autonomous) return defaultToolContext();
  const status = await lenz("status", "--state", state);
  const datasetSummary = JSON.parse(await readFile(resolve(campaign, "dataset-summary.json"), "utf8"));
  return sanitizeAutonomousContext({ state_revision: status.state_revision, status: requireOk(status, "status"), dataset_summary: datasetSummary, declared_provenance: manifest.normalized_config_hash ? { experiment_name: manifest.experiment_name, experiment_policy: manifest.experiment_policy, declared_config_hash: manifest.normalized_config_hash } : undefined });
};

const trajectoryPath = resolve(campaign, "trajectory.json");
let trajectory = await readFile(trajectoryPath).then((text) => JSON.parse(text), () => []);
trajectory = reconcileTrajectory(frameAtStartup, trajectory, (trial) => trial.receipt_id ? resolve(receipts, `${trial.trial_id}.json`) : undefined);
await writeJsonAtomic(trajectoryPath, trajectory);
const persistStep = async (entry) => {
  const index = trajectory.findIndex((item) => (entry.trial_id && item.trial_id === entry.trial_id) || (entry.request_id && item.request_id === entry.request_id));
  if (index >= 0) trajectory[index] = { ...trajectory[index], ...entry };
  else trajectory.push(entry);
  await writeJsonAtomic(trajectoryPath, trajectory);
};
const submitDecision = async (entry) => {
  const submit = await lenz("submit", "--state", state, "--pool-index", String(entry.decision.pool_index), "--config", JSON.stringify(entry.decision.config), "--request-id", entry.request_id);
  const submitted = requireOk(submit, "submit");
  if (submitted.query_index !== Number(entry.decision.pool_index)) throw new Error("commitment pool_index/config mismatch");
  await persistStep({ ...entry, trial_id: submitted.trial_id });
  return submitted.trial_id;
};
for (const intent of trajectory.filter((entry) => entry.decision && entry.request_id && !entry.trial_id)) {
  await submitDecision(intent);
}
let context = await toolContext();
if (context.status.observed === 0) {
  // All policies: cold-start surrogate is untrustworthy (few labels, categorical
  // kernel degenerates). Steer the first-step acquisition toward a conservative
  // exploration-acquisition instead of the raw noisy_logei tail. Fetch diagnostics
  // directly because autonomous context deliberately omits them.
  const diagnosticsNow = requireOk(await lenz("diagnostics", "--state", state), "diagnostics");
  const desired = lowTrustAcquisition(diagnosticsNow);
  if (context.status.acqf !== desired.acqf || Number(context.status.beta) !== desired.beta) {
    requireOk(await lenz("set-acqf", "--state", state, "--acqf", desired.acqf, "--beta", String(desired.beta), "--rationale", "Supervisor diagnostic policy"), "set-acqf");
    context = await toolContext();
  }
}
const recovered = [];
if (context.status.pending.length) {
  for (const trialId of context.status.pending) {
    const current = JSON.parse(await readFile(state, "utf8"));
    const trial = current.trials.find((item) => item.trial_id === trialId);
    if (!trial) throw new Error(`pending trial missing from Frame: ${trialId}`);
    const oracle = JSON.parse(await run("boagent-oracle", ["--dataset-root", current.public_root, "--state", state, "--trial-id", trialId, "--request-id", trial.request_id, "--receipts", receipts]));
    const receipt = requireReceipt(oracle);
    const observation = requireOk(await lenz("observe", "--state", state, "--trial-id", trialId, "--receipt", receipt), "observe");
    await persistStep({ trial_id: trialId, request_id: trial.request_id, receipt, metrics: observation.metrics });
    recovered.push({ trial_id: trialId, metrics: observation.metrics });
  }
  context = await toolContext();
}
const taskText = await readFile(resolve(campaign, "TASK.md"), "utf8");
const runtimeIsolation = { noTools: "builtin", noExtensions: true, noSkills: true, noPromptTemplates: true, noContextFiles: true };
const leakageGate = autonomous ? leakagePreflight({
  prompt: [renderedSystem, taskText, JSON.stringify(context)].join("\n"),
  toolNames: [...lenzTools, ...actionTools].map((tool) => ({ name: tool.name, parameters: tool.parameters })),
  context,
  runtime: runtimeIsolation,
  prior: manifest,
}) : { passed: true, profile: "default" };
runConfig.leakage_gate = leakageGate;
runConfig.config_hash = hash(JSON.stringify(runConfig));
const previous = audit.revisions.at(-1);
if (!previous || Object.entries(runConfig).some(([key, value]) => previous[key] !== value)) {
  audit.revisions.push({ revision: audit.revisions.length + 1, at: new Date().toISOString(), ...runConfig, event: priorModel && (priorModel[0] !== provider || priorModel[1] !== modelId) ? "model_switched" : "run_configured", ...(priorModel ? { previous_provider: priorModel[0], previous_model: priorModel[1] } : {}) });
  await writeJsonAtomic(auditPath, audit);
}
const modelRuntime = await ModelRuntime.create({ modelsPath: resolve(root, ".pi/models.json") });
const model = modelRuntime.getModel(provider, modelId);
if (!model) throw new Error(`model not found: ${provider}/${modelId}`);
const sessionManager = priorSession ? SessionManager.open(sessionFile) : (() => {
  const manager = SessionManager.create(campaign, campaign);
  manager.setSessionFile(sessionFile);
  return manager;
})();
const { session } = await createAgentSession({
  cwd: campaign,
  model,
  modelRuntime,
  resourceLoader: loader,
  noTools: "builtin",
  customTools: [...lenzTools, ...actionTools],
  sessionManager,
  thinkingLevel: thinking,
});
const events = [];
session.subscribe((event) => {
  if (["tool_execution_start", "tool_execution_end", "turn_start", "turn_end", "agent_end"].includes(event.type)) {
    events.push({ at: new Date().toISOString(), ...event });
  }
});
let prompt = [
  `Campaign ID: ${manifest.campaign_id}`,
  `The Frame already exists. Verified lenz evidence is supplied by the Supervisor.`,
  `The complete public task description is included below; do not try to read hidden outcomes.\n${taskText}`,
  `Current verified campaign evidence: ${JSON.stringify(context)}`,
  recovered.length ? `Recovered verified observations: ${JSON.stringify(recovered)}.` : "",
  autonomous
    ? `${createStepInstruction({ autonomous: true })} Early stop is unavailable.`
    : `${createStepInstruction({ autonomous: false })} Candidate identity is the complete config plus pool_index. Only identical candidate_id values are replicates.`,
].filter(Boolean).join("\n");
const completedThisRun = [];
const maxActionAttempts = 3;
const maxProviderAttempts = 3;
const sleep = (milliseconds) => new Promise((accept) => setTimeout(accept, milliseconds));
let stopped;
for (let step = context.status.observed; step < manifest.budget; step += 1) {
  let decision;
  lenzTools.resetStep?.();
  turnEvidence = { calls: [], proposals: [], candidate_rows: 0 };
  turnMutated = false;
  for (let attempt = 1; attempt <= maxActionAttempts; attempt += 1) {
    campaignAction = undefined;
    await promptWithTransientRetries({
      prompt: () => session.prompt(prompt),
      messages: () => session.messages,
      maxAttempts: maxProviderAttempts,
      sleep,
      canRetry: () => !turnMutated,
      onPause: (error, providerAttempt) => writeJsonAtomic(statusPath, { status: "paused", campaign_id: manifest.campaign_id, state_revision: context.state_revision, observed: context.status.observed, error, provider_attempt: providerAttempt }),
      onError: (error) => writeJsonAtomic(statusPath, { status: "error", campaign_id: manifest.campaign_id, state_revision: context.state_revision, observed: context.status.observed, error }),
    });
    try {
      const action = requireCampaignAction(campaignAction);
      if (action.type === "stop_campaign") {
        context = await toolContext();
        verifyStop(action, context.effective_manifest, context);
        stopped = {
          status: "stopped",
          campaign_id: manifest.campaign_id,
          state_revision: context.state_revision,
          condition: action.condition,
          verified: true,
          rationale: action.rationale,
          observed: context.status.observed,
          budget: manifest.budget,
          budget_remaining: manifest.budget - context.status.observed,
        };
        break;
      }
      const verifiedTrials = autonomous
        ? verifiedTrialFacts(requireOk(await lenz("trials", "--state", state), "trials"))
        : context.verified_trials ?? [];
      const commitment = verifyCommitment(action, context.suggestions ?? [], verifiedTrials);
      if (autonomous) {
        const page = requireOk(await lenz("candidates", "--state", state, "--cursor", String(commitment.pool_index), "--limit", "1"), "candidates");
        const exact = page.candidates?.[0];
        if (!exact || Number(exact.pool_index) !== Number(commitment.pool_index) || !isDeepStrictEqual(exact.config, commitment.config)) throw new Error("commitment does not match exact public Candidate identity");
        decision = validateDecisionEvidence({ ...commitment, candidate_id: exact.candidate_id }, turnEvidence, { verifiedTrials, target: context.status.target, direction: context.status.direction });
        const policyContext = { ...context, suggestions: turnEvidence.proposals };
        const selectedScore = await acquisitionScore(decision, policyContext, async (config) => requireOk(await lenz("score", "--state", state, "--configs", JSON.stringify([config])), "score"));
        // Autonomous policy cautions request correction while attempts remain,
        // then preserve the final validated commitment as an advisory outcome.
        decision = resolveAutonomousPolicyAudit(
          verifyOptimizationPolicy({ commitment: decision, selectedScore, context: policyContext, trajectory, manifest, autonomous }),
          attempt,
          maxActionAttempts,
        );
      } else {
        enforcePreferredSuggestion(commitment, context.preferred_suggestion, manifest.budget - context.status.observed);
        const selectedScore = await acquisitionScore(commitment, context, async (config) => requireOk(await lenz("score", "--state", state, "--configs", JSON.stringify([config])), "score"));
        decision = requirePolicyAllowance(verifyOptimizationPolicy({ commitment, selectedScore, context, trajectory, manifest: context.effective_manifest, autonomous }));
      }
      break;
    } catch (error) {
      if (attempt === maxActionAttempts) throw error;
      prompt = createRetryPrompt(error, { autonomous });
    }
  }
  if (stopped) break;
  const requestId = `${manifest.campaign_id}:${step}:${randomUUID()}`;
  const intent = { step: step + 1, request_id: requestId, decision, provenance: "journaled" };
  await persistStep(intent);
  const trialId = await submitDecision(intent);
  const current = JSON.parse(await readFile(state, "utf8"));
  const oracle = JSON.parse(await run("boagent-oracle", ["--dataset-root", current.public_root, "--state", state, "--trial-id", trialId, "--request-id", requestId, "--receipts", receipts]));
  const receipt = requireReceipt(oracle);
  const observation = requireOk(await lenz("observe", "--state", state, "--trial-id", trialId, "--receipt", receipt), "observe");
  await persistStep({ step: step + 1, request_id: requestId, decision, trial_id: trialId, receipt, metrics: observation.metrics });
  completedThisRun.push(trialId);
  if (step + 1 === manifest.budget) break;
  context = await toolContext();
  prompt = autonomous ? [
    `Verified observation for Trial ${trialId}: ${JSON.stringify(observation.metrics)}.`,
    `State how this Observation changes your belief before choosing Step ${step + 2}.`,
    `Budget remaining: ${manifest.budget - step - 1}.`,
    `Current verified campaign evidence: ${JSON.stringify(context)}.`,
    createStepInstruction({ autonomous: true }),
  ].join("\n") : [
    `Verified observation for Trial ${trialId}: ${JSON.stringify(observation.metrics)}.`,
    `Budget remaining: ${manifest.budget - step - 1}.`,
    `Current verified campaign evidence: ${JSON.stringify(context)}.`,
    manifest.budget - step - 1 === 1 ? `Terminal decision: compare every near_best_suggestions candidate before committing. With no later action, maximize the expected final best observed value; do not spend the last evaluation mainly on information or a matched comparison.` : `Interpret the result using exact candidate identities.`,
    createStepInstruction({ autonomous: false }),
  ].join("\n");
}
await writeJsonAtomic(trajectoryPath, trajectory);
const eventsPath = resolve(campaign, "supervisor-events.json");
const priorEvents = await readFile(eventsPath).then((text) => JSON.parse(text), () => []);
await writeJsonAtomic(eventsPath, [...priorEvents, ...events]);
console.log(JSON.stringify(campaignResult(campaign, completedThisRun.length, stopped)));

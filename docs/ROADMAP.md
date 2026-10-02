# Roadmap

Product milestones for Popper. Each milestone describes a user-visible outcome, the capabilities in scope, a demo gate, dependencies, and explicit exclusions. The demo gate accepts useful negative, null, inconclusive, and partial outcomes when their standing is clear; statistical significance is not a completion criterion. Architecture contracts live in [ARCHITECTURE.md](ARCHITECTURE.md). Implementation breakdowns belong in temporary specs and plans.

The development priority is to find useful, evidence-grounded hypotheses and findings worth further testing. Execution, state, recovery and traceability support that discovery loop. Established research systems provide mechanisms to adapt; local benchmarking is not a prerequisite for adoption. LLM capacity is expandable: budgets and concurrency settings allocate work and bound runs, without imposing a fixed capability ceiling. Demo gates verify concrete behavior and contracts; later evaluation measures scientific effectiveness.

For M3–M6, collect a small set of scientific capability signals while exercising each mechanism on real runs. Signals describe observed usefulness and failure modes; they are not benchmark gates, minimum thresholds, or prerequisites for completing a milestone. Build the mechanism, run it, inspect the signals and representative traces, then adjust the design.

M0–M2-optimize describe the baseline path. M3 starts a thin sequential adaptive loop as soon as execution identity and useful state exist; M4 strengthens recovery and captures lessons; M5 scales search to parallel branches and adds minimal literature retrieval; M6 expands literature grounding and acquisition. Deep publication audit and locked validation follow. Each increment retains a runnable path; exclusions describe that increment, not permanent product boundaries.

## M0 — Mini scientist

**Outcome.** A researcher can provide a brief and tabular dataset and receive a paper reporting a framed question, data exploration, one hypothesis, and its analysis.

**Scope / capabilities.** End-to-end coordination across understanding, data preparation, exploration, analysis, and communication; generated analysis code; recorded executions; named-result reporting.

**Demo gate.** A researcher runs the example study and receives a readable paper containing the research framing, data changes, exploration, hypothesis, and result.

**Dependencies.** None.

**Out.** Researcher-guided framing, robustness summaries, locked validation, multi-hypothesis discovery, literature retrieval.

## M1 — Trustworthy results

**Outcome.** A researcher can inspect the analysis attempts and robustness evidence, with computed labels and held-back data protected for possible future validation.

**Scope / capabilities.** Baseline, main, and robustness analyses; an attempt summary and computed legacy stability label; sealed candidate holdout; resumable runs.

**Demo gate.** A study report shows baseline, main, and robustness results, the full attempt summary, and a code-computed label; held-back data remain unavailable to discovery.

**Dependencies.** M0.

**Out.** A claim-level evidence audit and executable validation protocol.

## M2 — Grounded frame

**Outcome.** A researcher can steer the system's understanding of the problem, and see how the data represent that framing and where they fall short.

**Scope / capabilities.** Research context and Research Frame; researcher review; data-grounded operationalization, readiness, concerns, and limitations; a bounded return to framing when the data do not support the intended question.

**Demo gate.** A researcher reviews and resumes a study, then receives a paper with operationalizations and limitations grounded in the reviewed frame and data.

**Dependencies.** M1.

**Out.** Literature grounding, multiple hypotheses, broad method admission rules, and locked validation.

## M2-optimize — Cost and context

**Outcome.** Grounded-frame studies expose cost and context behavior, and researchers can control the resources available to a resumed run.

**Scope / capabilities.** Run-cost and tool-use reporting; model conversation reuse; clearer tool interaction; explicit researcher control over a resumed run's budget.

**Demo gate.** Positive and null grounded-frame studies expose cost and reuse behavior. An explicit budget change on resume is recorded and respected without resetting prior spend.

**Dependencies.** M2.

**Out.** New research capabilities, broad model-routing changes, and publication redesign.

## Pre-M3 — Baseline reconciliation

**Outcome.** The implemented M0–M2-optimize execution path is understood and reconciled with the contracts needed for M3, without replacing the existing scientist or creating parallel legacy and new paths.

**Scope / capabilities.** Trace the real path from CLI through coordinator, phases, tree search, harness execution and run store to reported output. Inventory active mechanisms and their owning contracts; for each, record whether to keep, adapt in place, retire or remove it based on an observed conflict with the M3 contracts. Preserve the meaning and readable history of existing runs. Keep stage-level code search inside analysis; place scientific candidate selection at the Discover boundary. Adapt single-hypothesis, closed-method and unscoped evidence identities only as required to support M3.

**Demo gate.** The architecture records the observed end-to-end path and a keep/adapt/retire/remove decision per existing mechanism. Each adaptation has one owner and a clear artifact identity; no new run can enter duplicate baseline and M3 paths. Format-4 runs retain their existing interpretation and resume behavior. Before changing a persisted reader or writer, tests exercise representative old records and the new contract; removal requires confirming no callers or serialized-state dependency remains.

**Dependencies.** M0–M2-optimize implementation.

**Out.** Building the M3 adaptive loop, broad cleanup unrelated to a demonstrated contract conflict, and wholesale replacement of working phases.

## M3 — Research execution core

**Outcome.** A small adaptive scientist can compare a few hypotheses, choose and run a justified next move, and update sourced state while preserving the identity of each test.

**Scope / capabilities.** Artifact-backed active research state exposing attempted work, usable observations, attributed assessments and open questions; scientific and execution identity; open `MethodSpec` for known and custom/generated methods with declared assumptions and outputs; specification-to-executor-to-artifact contracts using the existing backend; input source/provenance contracts; deterministic integrity checks; typed diagnosis and transitions; a thin loop that generates two or three hypotheses, proposes moves, selects one, executes it and updates state; bounded same-hypothesis revisit; committed resume and child lineage; separate coverage, fidelity, sensitivity, and support semantics.

**Demo gate.** The study path completes and resumes while preserving identities and history. From two or three hypotheses, Discover proposes ResearchMoves with an objective, evidence trigger, candidate action, expected discriminating value, estimated cost and stopping condition; it selects and executes a move, then updates state from the committed result. A bounded revisit cites its trigger, preserves prior attempts, and distinguishes same-test repair from a changed specification. Negative evidence, measurement defects, integrity failures, and resource constraints lead to visibly different outcomes.

**Scientific capability signals.** On real runs, inspect whether the state view gives the agent enough relevant context to propose a useful next action, whether cited records support that proposal, and which missing or stale state led to an unhelpful action. Review whether the small hypothesis set contains plausible alternatives and whether the selected move is informative. Use examples and researcher review; no numeric pass threshold.

**Dependencies.** Pre-M3 baseline reconciliation.

**Out.** Broad recovery and late data routing, parallel branches, deep claim lineage audit, independent validation, large hypothesis tournaments, deep literature grounding and dataset acquisition, and graph infrastructure.

## M4 — Feedback, recovery and evidence resolution

**Outcome.** When execution, measurement, or scientific obstacles arise, the researcher receives a justified next step or useful partial report without retries being driven by a desired result.

**Scope / capabilities.** Shared recovery routing over phase-owned diagnoses; broader bounded repair, refinement, pivot, and reframe routes; recovery from late data and scope issues; targeted escalation for decisions that materially affect researcher intent; independent challenge from a fresh context; minimal claim/measurement/specification/execution resolution over existing committed artifacts; sourced lesson capture from diagnoses and recovery outcomes; invalidation and supersession visibility; readable partial and no-budget outcomes.

**Demo gate.** Representative execution failures, measurement defects, and late data issues recover or stop with clear reasons and retained history. A corrected measurement retains its prior version and flags dependent claims. A proposed follow-up uses resolvable evidence and exposes missing links. Positive, null, and partial studies produce useful reports without retrying for significance.

**Scientific capability signals.** Record which recovery cases reach a usable continuation or honest stop, and review recovery success alongside wrong-recovery cases: transitions that misclassify a scientific change as repair, alter intended meaning, or act on a result as though it were an execution defect. Review whether captured lessons accurately describe their source case and limits. Report counts with case descriptions and denominators when available; do not use a target rate as the milestone gate.

**Dependencies.** M3.

**Out.** Parallel multi-hypothesis search, locked validation execution, and advanced challenge or orchestration topologies.

## M5 — Adaptive research search

**Outcome.** A run scales the sequential adaptive loop to parallel hypothesis and specification branches, accumulates findings, and returns evidence-grounded candidates with justified next tests.

**Scope / capabilities.** Parallel candidate generation, selection, follow-ups and resumable branch scheduling; replaceable `BudgetAllocator` strategy that recommends which candidates receive, retain, lose or regain compute and records the reason; sourced origins, predictions, alternatives and interpretation; active state queries for findings, contradictions and open questions; exclusive execution ownership and consistent shared history/resource accounting; minimal literature retrieval for hypotheses and follow-ups; generate/critique/revise and independent review as replaceable strategies; visible selection, exposure, failed and abandoned work; reuse of existing experiment tree search, open `MethodSpec` and evidence resolution.

**Demo gate.** Independent branches execute concurrently and resume without losing lineage, duplicating accepted execution, or resetting exposure. A follow-up cites the observations, challenge or resolved literature that motivated it. Allocation decisions show why a branch received more compute, was paused or stopped, and when resources were reassigned. The report distinguishes candidates from established findings, includes negative and abandoned work, and explains uncertainty and a discriminating next test for each recommended candidate. A null result can close a branch without ending other justified work.

**Scientific capability signals.** Review a sample of generated hypotheses and branches for relevance to the research question, testability, evidence-backed rationale, and a discriminating next test. Inspect whether literature sources retrieved in-loop are relevant and inform a useful move. Inspect whether the search explores substantively different explanations or methods, and whether allocation and selection preserve promising alternatives. Record useful-candidate examples, weak candidates and repeated or redundant branches; these observations guide iteration without becoming a quality threshold.

**Dependencies.** M4. Minimal literature retrieval uses M3 source/provenance contracts and can be integrated in parallel with search implementation.

**Out.** Mandatory tournament, debate, PI hierarchy or graph database; locked validation as a prerequisite; comprehensive causal-identification machinery.

## M6 — Acquisition and literature grounding

**Outcome.** A researcher can use deeper literature grounding and assess sourced dataset or benchmark candidates before selecting a run input.

**Scope / capabilities.** Expand M5's minimal literature retrieval with richer search, source triangulation, supporting passages, verified citations and suitability/limitations; provenance connecting sources to framing, hypothesis motivation and related work; candidate dataset and benchmark discovery with researcher selection and Ground assessment.

**Demo gate.** Broader literature grounding informs framing or follow-up through resolved sources, and related work cites only resolved records. Candidate datasets or benchmarks expose source, retrieval provenance, suitability and limitations before researcher selection. Retrieved literature is distinguished from current-run measurements; unresolved citations are flagged.

**Scientific capability signals.** Review whether retrieved sources are relevant to the query and research context, and whether they materially help framing, candidate generation or a justified follow-up. For dataset/benchmark candidates, record which were judged suitable and useful after researcher review and Ground assessment, including why others were rejected. Use representative cases and counts as observations, not acceptance thresholds.

**Dependencies.** M5 minimal literature retrieval and M3 artifact/source contracts. Dataset and benchmark acquisition can proceed alongside M5; deep publication audit is not a prerequisite.

**Out.** Automatic procurement or collection, multiple datasets within one run, automatic acquisition of validation entitlement, and unsupported novelty claims.

## M7 — Traceable evidence and publication

**Outcome.** A researcher can trace reported claims to measurements and intended tests, understand candidate findings and their limitations, and obtain a paper that builds reliably.

**Scope / capabilities.** Extend the existing resolver into claim/number/figure lineage audit; evidence completeness and measurement-fidelity reporting; invalidation and supersession propagation; figures, claims view and bounded publication repair; faithful reporting of multi-hypothesis, null, partial and recovered studies, including selection history and next tests.

**Demo gate.** Positive, null and partial reports build or preserve complete source with diagnostics. A claim audit traces reported empirical values and figures to committed evidence, flags unresolved or invalidated links, and retains failed or abandoned branch history. Completion, scientific assessments and validation standing remain separate.

**Dependencies.** M4 evidence resolution and M5 discovery. Integrates M6 sources when available; acquisition is optional for a study using researcher-provided inputs.

**Out.** Locked validation, comprehensive causal-identification machinery, and mandatory debate or critic topology.

## M8 — Locked validation

**Outcome.** A researcher can evaluate a selected claim once under a prespecified protocol using suitable evidence that did not shape adaptive discovery.

**Scope / capabilities.** Protocol lock before access; suitability and exposure accounting across branches, resumes and shared sources; separated access and verdict authority; explicit supported, not-supported, inconclusive and unavailable outcomes; append-only validation records and publication updates.

**Demo gate.** A validation study records a computed outcome under a locked protocol, preserves its exposure, and prevents post-access adaptation from changing the protocol or standing. Unsupported and inconclusive outcomes are valid demo results. Adaptive discovery runs remain useful when independent validation is unavailable.

**Dependencies.** M7 and suitable independent evidence. This milestone does not gate adaptive discovery or acquisition.

**Out.** Reusable holdouts, complex exposure allocation, and automatic acquisition of new validation data.

## M9 — Cross-run learning

**Outcome.** A later run can use attributed lessons from prior execution and research workflows while retaining its own evidence and exposure history.

**Scope / capabilities.** Lesson extraction from failures, repairs and recurring patterns; source attribution, applicability conditions and retrieval/use records; reusable skills as advisory context; correction or retirement of stale lessons; data identity and exposure carried with dataset-specific information.

**Demo gate.** A later run retrieves an applicable sourced lesson and uses it in a recorded proposal or repair. An inapplicable lesson is excluded or qualified. No lesson is presented as new-run empirical evidence, and shared-source information remains visible in exposure accounting.

**Dependencies.** M4 captures sourced diagnoses and recovery lessons. Full retrieval and reuse remain this milestone's outcome. Scientific-strategy lessons integrate M5 selection history when available; M8 is not a prerequisite, but any validation must honor lesson-derived exposure.

**Out.** Automatic promotion of lessons to scientific facts, unqualified transfer across datasets, and model-weight training.

## M10 — Strategy extensions and evaluation

**Outcome.** A justified advanced capability improves a demonstrated user outcome without weakening evidence, identity, or integrity contracts.

**Scope / capabilities.** Derived research graph/index, alternative search policies, tournament/debate and PI or Discover agents, richer diagnostics, additional execution backends, expanded data types, web interface or deployment isolation. Popper evaluation cases and later benchmark comparisons cover completion, recovery, hypothesis quality, measurement fidelity, traceability, scientific usefulness and cost; rollout counts are activity metrics, not scientific success.

**Demo gate.** Each proposed capability has its own end-to-end demonstration showing the motivating need, user-visible benefit, cost, and preservation of architectural contracts.

**Dependencies.** The relevant shipped capability and a documented rationale from established systems, a concrete user need or an observed failure. These strategies are independent options; benchmark availability does not gate their initial adoption. Evaluation cases and operational records can accumulate throughout earlier milestones.

**Out.** Capabilities without a demonstrated need and value; no advanced strategy is a prerequisite hidden in earlier milestones.

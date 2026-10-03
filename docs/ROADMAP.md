# Roadmap

Product milestones for Popper. Each milestone describes a user-visible outcome, the capabilities in scope, a demo gate, dependencies, and explicit exclusions. The demo gate accepts useful negative, null, inconclusive, and partial outcomes when their standing is clear; statistical significance is not a completion criterion. Architecture contracts live in [ARCHITECTURE.md](ARCHITECTURE.md). Implementation breakdowns belong in temporary specs and plans.

The development priority is to find useful, evidence-grounded hypotheses and findings worth further testing. Execution, state, recovery and traceability support that discovery loop. Established research systems provide mechanisms to adapt; local benchmarking is not a prerequisite for adoption. LLM capacity is expandable: budgets and concurrency settings allocate work and bound runs, without imposing a fixed capability ceiling. Demo gates verify concrete behavior and contracts; later evaluation measures scientific effectiveness.

For M3–M6, collect a small set of scientific capability signals while exercising each mechanism on real runs. Signals describe observed usefulness and failure modes; they are not benchmark gates, minimum thresholds, or prerequisites for completing a milestone. Build the mechanism, run it, inspect the signals and representative traces, then adjust the design.

M0–M2-optimize describe the baseline playbook. M3 establishes bounded adaptive execution; M4 adds scientific interpretation/challenge and strengthens recovery; M5 develops candidate evolution, research direction and minimal literature; M6 expands literature and data assessment. M7 makes manuscript/review feedback callable, M8 adds a strong optional validation regime, and M9 delivers cross-run scientific continuity alongside separate procedural reuse. Milestone numbers describe delivery, not a terminal scientific phase sequence. Parallelism and role topology remain optional strategies; each increment retains a runnable path.

## Current code reality

The traced path is [CLI](../src/popper/cli.py) → [run/resume](../src/popper/coordinator/run.py) → [sequential scheduling](../src/popper/coordinator/discovery.py). It creates a format-5 Run, or decodes a saved format-4/5 policy, locks the Run, computes raw descriptives, obtains a reviewed frame, prepares data with bounded reframing, and explores discovery rows. [Discover](../src/popper/discover/explore.py) generates exactly two or three sourced testable candidates (default three). [Its model policy](../src/popper/discover/policy.py) proposes and selects sourced ResearchMoves; Coordinator schedules an immutable attempt, and [scoped experiments](../src/popper/discover/experiment.py) reuse baseline/main/predeclared sensitivity code search. [State](../src/popper/discover/state.py) is rebuilt from committed results, diagnoses and direct invalidation. [Communication](../src/popper/communicate/paper.py) renders measurements and retained history, including deterministic partial output when model budget is exhausted.

| Capability | Current contract | Target distinction |
| --- | --- | --- |
| Researcher intent and empirical grounding | Reviewed Research Frame; fresh preparation, proposed operationalization, concerns/readiness | These remain useful scientific inputs; phase order is replaceable. |
| Candidates and methods | Two or three once-generated candidates; precise primary estimand/direction; open MethodSpec | Immature ideas, explanation/rival evolution and broader candidate identity are not yet supported. |
| Moves and transitions | Sourced proposal/selection; test, same-test repair and operational refinement; pivot/reframe/acquisition deferred | Reasoning-only moves, independent scientific challenge and interpretation updates are targets. |
| Experiment and evidence | Immutable TestSpec, scoped Attempt/MeasurementRef; fresh execution; exact code/input/test identity; separate fidelity, support, coverage and sensitivity | TestSpec is the current ExperimentSpec contract. Successful execution or prospective support does not confer validation or scientific truth. |
| Persistence and recovery | Journal, write-once artifacts, frontier/snapshots, direct invalidation, run lock and spend; incomplete attempts resume first | Cross-run scientific continuity and transitive interpretation/claim invalidation are targets. |
| Reporting | StudyOutput transports one Run's records; exact-content publication caches; named results and partial/diagnostic reports | This does not yet provide a persistent multi-run Study or manuscript-to-research feedback. |

Defaults allow four scheduled moves and one later move per hypothesis. Interrupted attempts count; proposal, stop and deferred calls do not. Stage roles select analysis budgets; opaque instance identities scope paths and replay, avoiding reuse of another candidate's results. Node scores select code within an instance, never hypotheses. Scratch output has no accepted node backing. Prospective directional/equivalence support rules apply only to matching usable measurements; missing or unresolved fidelity means unavailable support.

Format-4 Runs retain their single-hypothesis declarations, global artifact names and original stability rule through the saved-policy decoder, existing engine and renderer. Historical records are not rewritten or granted a richer scientific specification retroactively. Current format-5 contracts replace those global identities for new work; compatibility decoding is not a second target architecture.

**Remaining gaps:** the set is generated once and demands precise estimands/direction immediately. Move proposal/selection can reason over observations, but there is no committed explanatory synthesis or general independent scientific challenge. Question records can be projected but no current production path creates them. Literature retrieval, persistent cross-run direction, transitive claim resolution, held-back verification and manuscript-to-research routing are not implemented. These are scientific capability gaps; execution recovery and node assessment do not fill them.

**Logical ownership versus current placement.** Scientific responsibilities already exist across these files; the runtime is not a proposed service. `harness/research.py` currently contains research-context semantics, and `harness/records.py` contains hypothesis/test measurement identities and StudyOutput transport. Those are scientific contracts housed in the harness, not generic harness policy. Preserve their working semantics and readers. Move shared scientific contracts only when a concrete caller or ownership conflict requires it; do not create a new package hierarchy merely to make the diagram literal. Pure descriptive computation can stay a reusable utility; interpretation belongs to the Scientist.

Current `choose_action` drafts until its configured draft allowance, then chooses a debuggable node or improves the best accepted node under step/debug limits; `select_best` uses the highest local Judge score, earliest on ties. Predeclared sensitivity attempts use their recorded schedule. Replay preserves instance identity and consumed attempts. These are local implementation strategies, not scientific judgments. Discover's separate model proposal/selection loop chooses ResearchMoves (§4.6); it must not treat a node score as hypothesis quality or favorable estimates as its objective.

## Delivery toward a persistent Scientist

The target is `Research Program → Scientific State ↔ AI Scientist → ResearchMove → Run → Evidence → Scientific State`. Persistence means scientific understanding, direction and exposure survive bounded episodes; it does not require a continuously running process. Architecture owns these semantics. The following delivery slices strengthen the existing loop without changing historical evidence or building a second pipeline:

1. Preserve the execution core: exact references, TestSpec, scoped attempts, typed recovery, evidence dimensions and resume. Treat current StudyOutput as an episode report, not a persistent Study.
2. Add independent challenge and attributed interpretation to the sequential loop. After a result, commit what changed in the explanation, which rivals survive and which questions remain unresolved; derive the Scientist-facing view from those records. Exercise the thin behavior below before wider scheduling.
3. Let candidates mature and evolve, and give move selection a sourced research direction above the immediate action. Integrate minimal resolved literature into that reasoning; parallel branches remain an optional response to an observed limitation.
4. Continue a real question across bounded Runs through explicit source-run references, scientific state and shared exposure. Use that continuation to demonstrate persistent Research Program semantics; add Study grouping only when it clarifies a coherent investigation. Keep reusable procedural lessons separate.
5. Make manuscript review, validation and new-data requests return observations or unresolved questions to the same scientific loop as their capabilities ship. These are callable capabilities, not a required sequence or completion ladder.

These slices describe the path to the target, not a claim that the current branch already delivers persistent research. Milestone acceptance below determines delivery scope. Evaluation cases accumulate with each slice, including stopped, null and contradictory outcomes.

### Thin end-to-end behavior

The target behavior is `scientific candidates → challenge → ResearchMove → ExperimentSpec → execute → observe → update scientific understanding → next move`. Exercise it on the existing sequential path before adding topology. The following is an illustrative target trace, not a claim about a completed run:

1. Exploration finds a study-time/score association. The Scientist retains an observation, asks what explains it, and proposes learning benefit and prior-attainment selection as rivals; it does not require both to become precise directional hypotheses immediately.
2. A separate challenge checks timing, proxies and prior work. It identifies missing prior-attainment measurement and asks which available observation could distinguish the rivals. Sources and access limits are recorded; agreement between models grants no empirical standing.
3. The Scientist chooses a ResearchMove to test a stated implication with an available pre-outcome proxy, explains its value to the larger question and its limits, and retains the alternative of collecting longitudinal data. The move yields a TestSpec with fixed inputs, operational comparison, uncertainty procedure, outputs and any prospective support rule.
4. Coordinator schedules the authorized move; the current Analyst/tree strategy implements it through the harness. A fresh execution records named measurements and coverage; fidelity concerns remain separate from scientific outcome.
5. Suppose the association attenuates under the declared adjustment. The Scientist records that this weakens the simple learning-benefit account, may favor selection, and cannot identify causality from an imperfect proxy. The sourced view retains both explanations, the measurement and the unresolved temporal question.
6. The next move follows that updated understanding: a justified discriminating check, literature clarification, or a recommendation for new data/another Run. A paper can report the uncertainty; writing is neither required for this episode to be useful nor permission to upgrade the evidence.

**Current coverage:** candidate proposals, sourced moves, immutable TestSpecs, scoped execution, accepted observations, state rebuilding and next-move selection exist. **Target additions:** independent candidate/interpretation challenge, less premature formalization, explicit scientific synthesis/evolution and longer-horizon continuity. The architectural test is whether these additions change what Popper understands and chooses to investigate, with traceable evidence and cost, rather than merely making the schedule more elaborate.

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

**Demo gate.** The current-code baseline in this roadmap records the observed end-to-end path and the preserve/adapt decision for each affected mechanism; architecture retains its design contracts. Each adaptation has one owner and a clear artifact identity; no new run can enter duplicate baseline and M3 paths. Format-4 runs retain their existing interpretation and resume behavior. Before changing a persisted reader or writer, tests exercise representative old records and the new contract; removal requires confirming no callers or serialized-state dependency remains.

**Dependencies.** M0–M2-optimize implementation.

**Out.** Building the M3 adaptive loop, broad cleanup unrelated to a demonstrated contract conflict, and wholesale replacement of working phases.

## M3 — Research execution core

**Outcome.** A small adaptive scientist can compare a few hypotheses, choose and run a justified next move, and update sourced state while preserving the identity of each test.

**Scope / capabilities.** Artifact-backed active research state exposing attempted work, usable observations, attributed assessments and open questions; scientific and execution identity; open `MethodSpec` for known and custom/generated methods with declared assumptions and outputs; specification-to-executor-to-artifact contracts using the existing backend; input source/provenance contracts; deterministic integrity checks; typed diagnosis and transitions; a thin loop that generates two or three hypotheses, proposes moves, selects one, executes it and updates state; bounded same-hypothesis revisit; committed resume and child lineage; separate coverage, fidelity, sensitivity, and support semantics.

**Demo gate.** The study path completes and resumes while preserving identities and history. From two or three hypotheses, Discover proposes ResearchMoves with an objective, evidence trigger, candidate action, expected discriminating value, estimated cost and stopping condition; it selects and executes a move, then updates state from the committed result. A bounded revisit cites its trigger, preserves prior attempts, and distinguishes same-test repair from a changed specification. Negative evidence, measurement defects, integrity failures, and resource constraints lead to visibly different outcomes.

**Scientific capability signals.** On real runs, inspect whether the state view gives the agent enough relevant context to propose a useful next action, whether cited records support that proposal, and which missing or stale state led to an unhelpful action. Review whether the small hypothesis set contains plausible alternatives and whether the selected move is informative. Use examples and researcher review; no numeric pass threshold.

**Dependencies.** Pre-M3 baseline reconciliation.

**Out.** Broad recovery and late data routing, parallel branches, deep claim lineage audit, independent validation, large hypothesis tournaments, deep literature grounding and dataset acquisition, and graph infrastructure.

## M4 — Scientific feedback, challenge and recovery

**Outcome.** After execution, challenge or an obstacle, the Scientist records what changes in the current explanation, which rivals survive and what remains unresolved, then proposes a justified next step or an honest episode stop.

**Scope / capabilities.** Independent challenge from a fresh context; attributed interpretation/synthesis and sourced questions in the existing state path; shared recovery routing over domain-owned diagnoses; broader bounded repair/refine/pivot/reframe and late-data routes; targeted escalation for confirmed intent; minimal evidence resolution and invalidation/supersession visibility; sourced procedural lesson capture; readable partial/no-budget outcomes. Preserve the execution core and separate empirical observations from assessments.

**Demo gate.** A challenged candidate or interpretation changes a subsequent move with cited reasons. A positive, null or contradictory result updates the Scientist-facing understanding and unresolved questions. Technical failure and negative scientific evidence lead to visibly different responses. A corrected measurement retains history and flags affected uses. An unavailable route is deferred rather than presented as executed; the Run may stop without a paper.

**Scientific capability signals.** Inspect whether challenge identifies a material weakness, whether interpretation is faithful and whether it changes research choices. Review wrong-recovery cases, including scientific changes disguised as repairs and negative results treated as bugs. Inspect lesson applicability and limits; use cases and denominators without a target success rate.

**Dependencies.** M3 execution identity, state and bounded moves.

**Out.** Full cross-run Program persistence, parallel scheduling, locked validation execution and mandatory critic/debate topology.

## M5 — Candidate evolution and research direction

**Outcome.** The Scientist evolves explanations and rivals from observations/questions toward testable hypotheses, and selects work that advances a sourced research direction rather than only a greedy next test.

**Scope / capabilities.** Adapt the once-generated precise-candidate contract for maturity and linked revisions; retain alternative explanations, abandoned work and reasons for selection. Add sourced direction above ResearchMoves, Scientist-facing queries for explanations/contradictions/open questions, and reasoning moves where needed. Integrate minimal literature reading/retrieval using existing source contracts. Reuse TestSpec, scoped code search and evidence semantics. Parallel branches or a separate allocator are optional extensions when a real run exposes a capacity/search gap; they preserve branch ownership, accounting and exposure.

**Demo gate.** An observation/question remains useful before an estimand is declared. Challenge or evidence narrows, splits, retires or evolves a candidate with visible lineage. A move cites how it advances direction, including a prerequisite or replication need. Resolved prior work informs an explanation or discriminating test; unavailable literature remains explicit. New observations update understanding and the next move. If parallel scheduling is introduced, demonstrate ownership, resume and shared accounting without duplicate accepted executions or exposure resets.

**Scientific capability signals.** Inspect substantive hypothesis evolution, diversity of surviving explanations, discrimination and longer-horizon rationale. Review whether sources materially affect reasoning rather than merely appear in related work. Compare useful progress, redundant work and cost with the sequential loop.

**Dependencies.** M4 challenge, interpretation and evidence resolution; M3 source contracts. Minimal literature does not depend on dataset acquisition.

**Out.** Mandatory parallelism, BudgetAllocator, tournament, PI hierarchy or graph infrastructure; locked validation as a prerequisite; comprehensive causal-identification machinery.

## M6 — Acquisition and literature grounding

**Outcome.** A researcher can use deeper literature grounding and assess sourced dataset or benchmark candidates before selecting a run input.

**Scope / capabilities.** Expand M5's minimal literature retrieval with richer search, source triangulation, supporting passages, verified citations and suitability/limitations; provenance connecting sources to framing, hypothesis motivation and related work; candidate dataset and benchmark discovery with researcher selection and Ground assessment.

**Demo gate.** Broader literature grounding informs framing or follow-up through resolved sources, and related work cites only resolved records. Candidate datasets or benchmarks expose source, retrieval provenance, suitability and limitations before researcher selection. Retrieved literature is distinguished from current-run measurements; unresolved citations are flagged.

**Scientific capability signals.** Review whether retrieved sources are relevant to the query and research context, and whether they materially help framing, candidate generation or a justified follow-up. For dataset/benchmark candidates, record which were judged suitable and useful after researcher review and Ground assessment, including why others were rejected. Use representative cases and counts as observations, not acceptance thresholds.

**Dependencies.** M5 minimal literature retrieval and M3 artifact/source contracts. Dataset and benchmark acquisition can proceed alongside M5; deep publication audit is not a prerequisite.

**Out.** Automatic procurement or collection, multiple datasets within one run, automatic acquisition of validation entitlement, and unsupported novelty claims.

## M7 — Persistent manuscripts and research feedback

**Outcome.** A researcher can trace a manuscript's claims to evidence, preserve its versions, and see missing science revealed by writing/review become a justified research question or move.

**Scope / capabilities.** Extend the resolver into claim/number/figure lineage audit, transitive stale-claim visibility, evidence-frontier manuscript versions and bounded writing/review. Return sourced issues through the existing scientific state/selection path. Preserve faithful negative, null, partial and superseded reporting and the deterministic fallback. Manuscript work is callable within or across episodes; rendering does not define Run completion.

**Demo gate.** A manuscript version resolves empirical values and figures to committed evidence and builds or preserves source/logs. Review exposes a missing discriminating test or unsupported claim, commits the issue and motivates a move rather than only editing prose. A later result changes the manuscript with preserved prior versions and visible stale dependencies. An episode can end with evidence or a next question without producing a paper.

**Scientific capability signals.** Inspect whether review-to-research feedback improves evidence or appropriately narrows claims, whether revisions remain faithful, and how much cost is spent on writing versus useful missing science.

**Dependencies.** M4 evidence resolution and M5 state/selection. Cross-run manuscript continuation integrates M9 references when available; it does not require a manuscript service or full Program hierarchy to demonstrate within-run feedback.

**Out.** Mandatory paper per Run, locked validation as a publication gate, comprehensive causal-identification machinery and fixed writer/critic topology.

## M8 — Locked validation

**Outcome.** A researcher can evaluate a selected claim once under a prespecified protocol using suitable evidence that did not shape adaptive discovery.

**Scope / capabilities.** Protocol lock before access; suitability and exposure accounting across branches, resumes and shared sources; separated access and verdict authority; explicit supported, not-supported, inconclusive and unavailable outcomes; append-only validation records and publication updates.

**Demo gate.** A validation study records a computed outcome under a locked protocol, preserves its exposure, and prevents post-access adaptation from changing the protocol or standing. Unsupported and inconclusive outcomes are valid demo results. Adaptive discovery runs remain useful when independent validation is unavailable.

**Dependencies.** Evidence-lineage and stale-claim checks from M7, plus suitable independent evidence. A completed manuscript is not a prerequisite. This milestone does not gate adaptive discovery or acquisition.

**Out.** Reusable holdouts, complex exposure allocation, and automatic acquisition of new validation data.

## M9 — Persistent scientific continuity and procedural learning

**Outcome.** The Scientist continues a real Research Program across bounded Runs, retaining current understanding, unresolved questions, research direction and evidence/exposure, while separately reusing attributed procedural advice.

**Scope / capabilities.** Explicit source-run references/read contracts and Program identity over existing immutable records; continued Scientific State with explanation/candidate lineage, contradictions, direction and pending work; cross-run resolution, stale-state visibility and shared-source exposure. Use a real continuation or replication to justify Study grouping where useful, without a mandatory storage/service hierarchy. Separately retrieve reusable lessons/skills with applicability, source attribution, use records and correction/retirement. Preserve historical Run semantics.

**Demo gate.** One episode ends with a contradiction, missing-data need or next question; another continues from the same Program understanding without relabeling imported measurements as new evidence or resetting exposure. It preserves the reason for the next move and updates understanding from its new outcomes. An applicable procedural lesson informs work with a recorded source and limit; an inapplicable lesson is excluded or qualified. Neither a report transport record nor a lesson store is treated as the scientific authority.

**Scientific capability signals.** Inspect whether continuity avoids repeating resolved work, preserves competing explanations and handles stale/invalidated sources. Evaluate the new episode's contribution to the larger question, shared-source independence and the distinct value of procedural advice.

**Dependencies.** M3 identity/persistence/source contracts, M4 interpretation/evidence resolution and M5 direction/evolution. Manuscripts and validation integrate when available; M8 is not a prerequisite, but any validation must honor inherited exposure.

**Out.** Fresh validation entitlement per Run, automatic promotion of lessons to scientific facts, mandatory Study hierarchy/graph/service, automatic collection and model-weight training.

## M10 — Strategy extensions and evaluation

**Outcome.** A justified advanced capability improves a demonstrated user outcome without weakening evidence, identity, or integrity contracts.

**Scope / capabilities.** Derived research graph/index, alternative search policies, tournament/debate and PI or Scientist agent configurations, richer diagnostics, additional backends, expanded data types, web interface or deployment isolation. Broaden the scientific evaluations accumulated in earlier milestones: hypothesis evolution, experiment selection, challenge/recovery quality, literature use, research continuity, fidelity, traceability, usefulness and cost. Rollout counts are activity metrics, not scientific success.

**Demo gate.** Each proposed capability has its own end-to-end demonstration showing the motivating need, user-visible benefit, cost, and preservation of architectural contracts.

**Dependencies.** The relevant shipped capability and a documented rationale from established systems, a concrete user need or an observed failure. These strategies are independent options; benchmark availability does not gate their initial adoption. Evaluation cases and operational records can accumulate throughout earlier milestones.

**Out.** Capabilities without a demonstrated need and value; no advanced strategy is a prerequisite hidden in earlier milestones.

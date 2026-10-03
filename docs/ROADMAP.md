# Roadmap

[ARCHITECTURE.md](ARCHITECTURE.md) is the architectural baseline: a persistent AI Scientist operating through Scientific Runtime and Agent Harness. This roadmap records implemented behavior and the runnable scientific increments that approach it. Change architectural direction only when implementation exposes a concrete contradiction; component completion alone is not a milestone.

The target loop is `Research Program → Scientific State ↔ Scientist → ResearchMove → Run → Evidence → Scientific State`. A Run bounds execution and resources; it need not complete a Study or manuscript. Each increment uses the authoritative path, preserves existing persisted evidence, and delivers a behavior that can be exercised with useful positive, negative, inconclusive, failed or partial outcomes. Model agreement, favorable estimates and candidate counts alone are not success.

## Current code reality

The traced path is [CLI](../src/popper/cli.py) → [run/resume](../src/popper/coordinator/run.py) → [sequential scheduling](../src/popper/coordinator/discovery.py). It creates a format-5 Run, or decodes a saved format-4/5 policy, locks the Run, computes raw descriptives, obtains a reviewed frame, prepares data with bounded reframing, and explores discovery rows. [Discover](../src/popper/discover/explore.py) generates exactly two or three sourced testable candidates (default three). [Scientific feedback](../src/popper/discover/feedback.py) challenges every candidate in a separate read-only context. [Its model policy](../src/popper/discover/policy.py) proposes and selects sourced ResearchMoves; Coordinator schedules an immutable attempt, and [scoped experiments](../src/popper/discover/experiment.py) reuse baseline/main/predeclared sensitivity code search. [State](../src/popper/discover/state.py) is rebuilt from committed results, diagnoses and invalidation. Each result receives an attributed interpretation with surviving rivals, limits and unresolved questions before another move is selected. Measurement invalidation marks dependent interpretations stale, including results that reused the measurement and later interpretations citing stale ones. [Communication](../src/popper/communicate/paper.py) renders measurements, attributed feedback and retained history, including deterministic partial output when model budget is exhausted.

| Capability | Current contract | Target distinction |
| --- | --- | --- |
| Researcher intent and empirical grounding | Reviewed Research Frame; fresh preparation, proposed operationalization, concerns/readiness | These remain useful scientific inputs; phase order is replaceable. |
| Candidates and methods | Two or three once-generated candidates; precise primary estimand/direction; open MethodSpec | Immature ideas, explanation/rival evolution and broader candidate identity are not yet supported. |
| Moves and transitions | Sourced proposal/selection; test, same-test repair and operational refinement; pivot/reframe/acquisition deferred | Candidate challenge and result interpretation are current. Reasoning-only moves, general candidate evolution and broader routes remain targets. |
| Experiment and evidence | Immutable TestSpec, scoped Attempt/MeasurementRef; fresh execution; exact code/input/test identity; separate fidelity, support, coverage and sensitivity | TestSpec is the current ExperimentSpec contract. Successful execution or prospective support does not confer validation or scientific truth. |
| Persistence and recovery | Journal, write-once artifacts, frontier/snapshots, interpretation staleness, run lock and spend; incomplete attempts resume first; committed feedback, terminal decisions and exhausted correction deferrals are not replayed | Cross-run scientific continuity and general claim resolution remain targets. |
| Reporting | StudyOutput transports one Run's records; exact-content publication caches; named results and partial/diagnostic reports | This does not yet provide a persistent multi-run Study or manuscript-to-research feedback. |

Defaults allow four scheduled moves and one later move per hypothesis. Interrupted attempts count; proposal, stop and deferred calls do not. Stage roles select analysis budgets; opaque instance identities scope paths and replay, avoiding reuse of another candidate's results. Node scores select code within an instance, never hypotheses. Scratch output has no accepted node backing. Prospective directional/equivalence support rules apply only to matching usable measurements; missing or unresolved fidelity means unavailable support.

Format-4 Runs retain their single-hypothesis declarations, global artifact names and original stability rule through the saved-policy decoder, existing engine and renderer. Historical records are not rewritten or granted a richer scientific specification retroactively. Current format-5 contracts replace those global identities for new work; compatibility decoding is not a second target architecture.

**Remaining gaps:** the set is generated once and demands precise estimands/direction immediately. Move proposal/selection consumes committed challenge and interpretation, and unresolved questions are projected from current interpretations. General explanation/rival maturation and independent challenge of interpretations are not implemented. Literature retrieval, persistent cross-run direction, transitive claim resolution, held-back verification and manuscript-to-research routing are not implemented. These are scientific capability gaps; execution recovery and node assessment do not fill them.

**Logical ownership versus current placement.** Scientific responsibilities already exist across these files; the runtime is not a proposed service. `harness/research.py` currently contains research-context semantics, and `harness/records.py` contains hypothesis/test measurement identities and StudyOutput transport. Those are scientific contracts housed in the harness, not generic harness policy. Preserve their working semantics and readers. Move shared scientific contracts only when a concrete caller or ownership conflict requires it; do not create a new package hierarchy merely to make the diagram literal. Pure descriptive computation can stay a reusable utility; interpretation belongs to the Scientist.

Current `choose_action` drafts until its configured draft allowance, then chooses a debuggable node or improves the best accepted node under step/debug limits; `select_best` uses the highest local Judge score, earliest on ties. Predeclared sensitivity attempts use their recorded schedule. Replay preserves instance identity and consumed attempts. These are local implementation strategies, not scientific judgments. Discover's separate model proposal/selection loop chooses ResearchMoves (§4.6); it must not treat a node score as hypothesis quality or favorable estimates as its objective.

### Existing execution and reporting strategies

The current playbook uses Understand, Ground, Discover, Experiment and Communication, with Theorist, Data Steward, Analyst, Judge and Writer model configurations. These are implemented capabilities and strategies, not the target scientific topology. Within code search, the existing stage configuration is:

| Stage | Goal | Inputs | Required outputs |
| --- | --- | --- | --- |
| `explore` | Relevant relations, group differences and surprises | Prepared discovery data, descriptives and empirical foundation | Observations with figures |
| `baseline` | Transparent model/test for the hypothesis | Prepared discovery data and intended test | Key estimate with interval; historical contracts also require a figure |
| `main` | Planned analysis under the specification | Selected baseline and committed test | Named estimates and coverage; figures only where the saved contract requires them |
| `robustness` | Predeclared sensitivity checks | Selected main analysis and recorded schedule | Named measurements and requested-alternative coverage |

Format-5 sensitivity currently compares direction and interval overlap, with coverage, attributed fidelity and prospective support recorded separately. Format-4 retains its ordinary-variant schedule plus one seeded exposure permutation using the same contrast/estimator; the permutation is diagnostic rather than a calibrated permutation test. A repaired specification is represented by its highest-scoring successful node, earliest on ties. The historical rule requires at least `min_variants=3` successful ordinary specifications and labels work `stable` when at least `stability_share` (default 0.8) of scheduled variants have intervals excluding zero with the main sign and the adversary interval contains zero, endpoints included. Failed/missing ordinary variants remain in the denominator; a failed/missing adversary forces `fragile`. Preserve this rule's original meaning without using it as validation or a general scientific verdict.

Candidate holdout preparation currently uses `holdout_fraction` (default 0.2; zero disables), grouped by `data.group_column` when configured, without inferring grouping from research metadata. Executable locked validation remains M9 work; sealing alone does not establish suitability or independence.

Current reporting uses exact StudyOutput content/frontiers for publication caches and provides deterministic partial/diagnostic output. Local context truncation, prompt caching, progress display and CLI modes remain harness configuration. Targeted decision-specific escalation must preserve initial researcher review while it is adapted; automated operation leaves unresolved intent proposed/unknown or deferred.

## Delivered foundations and outstanding verification

Earlier milestone names describe delivery history, not a required scientific lifecycle:

| Delivery history | Implemented foundation retained |
| --- | --- |
| M0: initial end-to-end path | Framing, preparation, exploration, generated analysis and named-result reporting. A paper-producing playbook is a current strategy, not the meaning of a Run. |
| M1: trustworthy execution | Recorded attempts, computed historical sensitivity summary, sealed candidate holdout and resume. Historical labels retain their original rules and do not establish validation. |
| M2: grounded framing | Reviewed researcher intent, proposed operationalization, preparation checks, concerns and bounded reframing. |
| M2-optimize: cost and context | Recorded spend, conversation/tool context and explicit budget raises without resetting spend. |
| M3: adaptive execution | Multiple sourced quantitative candidates, model-selected moves, immutable specifications, scoped fresh execution, state rebuilding and typed repair/refinement. |

**Status (2026-10-03).** Provisionally closed by researcher decision. Implementation and automated verification are complete on the feature branch; live verification of the full demo gate remains outstanding. The live study retained two hypotheses but stopped before experiment execution because proposed source references lacked manifest backing and the budget was exhausted.

**Carry-forward.** Verify live move selection, execution, committed state update and bounded revisit/resume. Address reference guidance and correction behavior while preserving integrity checks, and the budget guard's possible in-flight cost overrun. These remain open follow-ups for M4; provisional closure does not mark the demo gate as passed or merge the feature branch.

## M4 — Challenge, execute, interpret, continue

**Outcome.** The Scientist challenges multiple candidates from a separate context, executes a justified move, records what the result changes in its understanding, and uses that sourced interpretation to choose the next move.

**Smallest vertical slice.** Extend the existing sequential path with independent candidate challenge and attributed result interpretation. Reuse quantitative candidates, ResearchMove selection, TestSpec, scoped experiments, artifact reading, immutable records and the existing report renderer. Make unresolved questions visible in state; feedback is reasoning rather than a code-computed scientific verdict. No separate Scientist agent, Program service, planner or parallel scheduler is needed.

**Runnable acceptance.** An existing end-to-end case retains competing candidates, records sourced challenge, selects and freshly executes a test, records an interpretation with limits/rivals/open questions, then selects a second experiment because of the updated state. A null/contradictory result and a technical/measurement failure receive distinct reasoning. Resume at challenge, execution or interpretation boundaries neither duplicates committed feedback nor repeats accepted execution. Invalidated observations expose dependent interpretations as stale. Budget/correction exhaustion preserves useful records and an explicit deferral/episode stop.

**Delivery status.** Implemented on the existing path. Provider-free focused tests exercise competing candidates, exact-source correction, a second experiment triggered by interpretation, negative outcomes, technical/measurement failure, invalidation, partial reporting and committed-boundary recovery. Automated verification is complete: Ruff and mypy pass; the non-slow suite has 433 passed, 1 skipped and 25 deselected; the full parallel suite has 458 passed and 1 skipped (2026-10-03). The final read-only review/simplify pass found two interrupted-disposition recovery gaps; both are fixed and covered by regressions. Live verification and scientific usefulness remain open; automated completion does not close the earlier demo gate.

**Carry-forward included.** Exercise exact-source guidance and actionable correction for feedback and move reasoning. Keep reference checks hard. Resource checks continue to gate new calls/actions; possible in-flight model cost overrun remains an explicit limitation, not a reset or permission to exceed future allocations.

**Out.** General candidate maturation, cross-run Program continuity, broad late-data/pivot/reframe routing, literature retrieval, independent validation, persistent manuscripts and infrastructure expansion.

## Subsequent runnable increments

The order below follows new scientific behavior. Each increment retains a runnable path and integrates already available capabilities rather than requiring an architectural component to be finished first.

### Next: M5 — Evolve explanations and choose discriminating work

**Outcome.** An observation or question can remain useful before an estimand exists; challenge and evidence narrow, split, retire or evolve explanations/rivals with sourced lineage. The Scientist chooses a prerequisite, replication or discriminating test because it advances a recorded research direction.

**Implementation path.** Relax precise-candidate declarations only at their authoritative owner, retain the stronger executable-test contract, and extend existing move/state reasoning. Add reasoning-only moves and justified scientific transitions where exercised; unavailable routes remain deferred. A selection narrative can carry direction without a planner hierarchy.

**Runnable acceptance.** Evidence changes a candidate's explanatory meaning and the next action while prior identity/evidence remain readable. Scientific change cannot masquerade as repair. Confirmed-intent changes remain researcher decisions.

### M6 — Continue an inquiry across bounded episodes

**Outcome.** One Run ends with a contradiction, unresolved question or replication need; another continues the same Research Program with prior understanding, direction and exposure intact.

**Implementation path.** Extend exact source-Run references/read contracts over existing immutable records. Demonstrate continuation before adding storage/services; optional Study grouping must clarify a coherent investigation. Procedural lessons keep attribution/applicability and remain separate from scientific observations.

**Runnable acceptance.** The second episode uses prior evidence without repeating resolved work, relabeling imported results as fresh execution or resetting exposure. Invalidated sources are visible and scientific understanding is reassessed. No mandatory Program service, Study hierarchy or graph.

### M7 — Resolve prior work when reasoning needs it

**Outcome.** A missing explanation, assumption or discriminating observation motivates a literature query; resolved prior work changes a candidate, interpretation or next move.

**Implementation path.** Add narrow source reading/retrieval through existing artifact/untrusted-context contracts. Preserve passages, retrieval provenance and distinctions between source claims, Scientist interpretation and current measurements. Expand search/triangulation only when the exercised question needs it.

**Runnable acceptance.** Relevant resolved sources materially change scientific reasoning; missing/unresolved sources remain explicit. Literature does not confer empirical or validation standing. Broad acquisition is not a prerequisite.

### M8 — Let writing and review reveal missing science

**Outcome.** A sourced manuscript/review issue motivates another scientific move; later evidence changes a preserved manuscript version while the inquiry continues.

**Implementation path.** Extend the existing evidence resolver and renderer with frontier-bound manuscript versions and stale-claim visibility. Reuse state/selection for returned questions. Build status, manuscript readiness, Run status and scientific outcome stay distinct.

**Runnable acceptance.** Claims/figures resolve to committed evidence, an unsupported claim is narrowed or motivates testing, and correction retains the prior manuscript and evidence. No mandatory paper per Run or manuscript service.

### M9 — Evaluate a selected claim under locked validation

**Outcome.** Suitable evidence that did not shape adaptive discovery evaluates a selected claim under a justified protocol locked before access.

**Implementation path.** Preserve sealing; add lock, source/slice suitability, shared-source exposure and separated verdict authority. Compute supported, not-supported, inconclusive or unavailable standing; keep execution/protocol failure separate from scientific non-support.

**Runnable acceptance.** Resume/branches/new Runs cannot acquire a fresh look at exposed evidence. Post-access adaptation cannot alter the lock or upgrade standing. Negative/inconclusive validation is a valid outcome. A completed manuscript is not a prerequisite; validation does not gate useful discovery.

### M10 — Obtain a missing observation or extend an exercised strategy

**Outcome.** A concrete inquiry identifies needed data, a replication or an execution/search limitation; the justified extension improves the resulting scientific action.

**Implementation path.** Assess candidate datasets/benchmarks with provenance, access and suitability before researcher selection and Ground assessment; Coordinator authorizes use. Alternative backends, parallel search, specialized agents, graphs or deployment infrastructure are independent options only when exercised behavior demonstrates the need.

**Runnable acceptance.** The extension supplies a useful observation/action at stated cost while preserving scientific identity, append-only history, exact provenance, fresh execution and exposure. No automatic procurement, validation entitlement or topology expansion merely to complete the diagram.

## Verification and scientific capability signals

Each increment runs focused contract tests and the repository's relevant full suite, using FakeLLM and real execution without provider calls. Extend the existing full pipeline or test at stage level. Historical records need representative coverage only where a changed reader/writer touches them; do not preserve obsolete new-work restrictions through compatibility workarounds.

On representative live runs, inspect whether challenge finds material weaknesses, interpretations follow usable evidence, candidates evolve substantively, next moves distinguish plausible explanations, and continued inquiry retains uncertainty/exposure. Include failures, null results and unavailable inputs with denominators and stated resources. Operational completion and model agreement do not establish scientific usefulness. Detailed temporary implementation steps belong under ignored `docs/superpowers/`.

# Roadmap

Product milestones for Popper. Each milestone is a shippable increment: a researcher can run it and gets something more useful than the milestone before. [ARCHITECTURE.md](ARCHITECTURE.md) defines the components and contracts; this document decides which of them ship when, and what "done" means.

## How milestones work

- **Outcome first.** A milestone is stated as what a researcher can do after it ships, then the capabilities that deliver it.
- **Demo gate.** One command a person can run, producing output they can read. A milestone is done only when its gate and acceptance criteria pass on a real model.
- **Size estimate.** A rough guess of `src/` lines for planning, not a limit. Code stays as small as the outcome allows.
- **From milestone to code.** Milestone → spec in `docs/specs/` (refines ARCHITECTURE contracts, never contradicts them) → implementation plan → build → close. A spec is removed once its milestone closes.
- **Scope discipline.** Nothing is built ahead of its milestone. After M4, a new mechanism names the failure it fixes and its evaluation result.

## Product overview

| Milestone | Product outcome | Demo gate | Depends on | Size (est.) | Status |
|---|---|---|---|---|---|
| **M0** Mini scientist | From a brief and a CSV, get a complete paper with one tested hypothesis | `popper run examples/student_performance` → paper with framing, data changes, exploration figures, one hypothesis and a tested result | — | ~2k | done |
| **M1** Trustworthy results | Every main result comes with robustness evidence and a computed stability label, and the run can later be verified | The paper shows baseline, main and robustness results, a specification curve over every attempt and a stability label | M0 | ~2.5k | done |
| **M2** Grounded frame | The researcher steers an agent's understanding of the problem; an agent grounds it in the data and says what the data cannot support | `popper run examples/student_performance` stops for review of the Research Frame; after `popper resume` → paper with an operationalization table and generated limitations | M1 | ~1.5k | todo |
| **M3** Discover agent | An agent decides what to explore, when to hypothesize and what to test over a research graph, and every tested hypothesis says how it was generated, what it predicted and whether the result matched | The demo explores at least two questions chosen by the agent; the paper shows the hypothesis origin, a pre-test sample table, the prediction verdict beside the stability label, and a research path from the graph | M2 | ~1.5k | todo |
| **M4** Evidence baseline | The team can tell whether a change makes Popper better | `popper-eval` prints the null false-finding rate, effect recovery, estimand recovery, holdout gap and cost for two configurations | M3 | + `evals/` | todo |
| **M5** Publication quality | A paper that compiles cleanly and can be checked claim by claim | Clean compile on three datasets; review, claims file and search map | M1 | ~3k | todo |
| **M6** Research loop | The researcher steers; results change what the run does next | Several critiqued hypotheses, researcher picks, a second round builds on the first, a late data problem opens a new Ground attempt; eval compares it with the playbook | M4, M5 | ~3.5k | todo |
| **M7** Literature | Framing, hypotheses and related work grounded in real prior work | The demo paper cites resolved prior work | M6 | ~4k | todo |
| **M8** Verify | Confirm a chosen result once on held-back data | `popper verify <run> <result>` → a computed outcome | M4 | ~4.5k | todo |
| **M9** Long-term track | Deferred capabilities, each started when its trigger is met | Per item | M4 | per item | parked |

## Capability growth

| Area | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|---|---|---|---|---|---|---|---|---|---|
| **Understand** | Profile and framing with one reflection | — | Theorist session (explore, critique, synthesize); research context with provenance and concepts; `ask_researcher`; item-level review signals and one revision; computed framing warnings | — | — | Introduction from objectives and audience | Research Frame revision after results | Domain background in the research context; prior work shapes questions | — |
| **Ground** | Agentic `data` stage, change log, row counts | Holdout set aside at ingest | Data Steward session with code-checked submits; operationalization, concerns, readiness; one descriptive-statistics module; bounded return to Understand | — | — | Before/after figures, derived-variable checks | New Ground attempt when a later phase finds a problem | — | — |
| **Exploration & hypothesis** | Agentic `explore` stage, one hypothesis | Hypothesis contract (one primary estimand, refuting result) | Reads frame and foundation; computed hypothesis warnings | Research graph seeded from the frame and foundation; agent chooses questions to explore and when to hypothesize; origins `frame` and `observation`; primary prediction; candidates kept | — | — | 3–5 hypotheses with mechanism and auxiliary predictions; origins `rival` and `followup` through `interpret`; Critic rubric, researcher choice | Relation to prior work | — |
| **Experiment** | One combined stage | `baseline` → `main` → `robustness`, multiverse, adversarial check, stability label | — | `test` move: pre-test description, frozen test specification, computed verdict | — | — | One tree per chosen hypothesis; rival predictions as variants and adversarial checks; label intervals adjusted for several hypotheses | — | Locked re-run on holdout |
| **Search engine** | Draft/debug/improve, typed Judge answers | Judge blind to estimates, reads figures | Discover stages only | Runs inside Discover moves | — | — | — | — | — |
| **Publication** | Template paper, named-result numbers, fixed label | Standard paper structure, results table, robustness section, specification curve | Operationalization table; limitations from proposals, concerns, readiness and warnings; raw-access disclosure | Hypothesis origin, pre-test sample table, verdict beside the stability label, research path from the graph | — | Figure aggregation, checks, claims file, rubric review, search map, disclosure | Per-hypothesis results | Related work, citations | Verified labels |
| **Roles** | PI playbook, Theorist, Analyst, Judge, Writer | — | Theorist as a session; Data Steward | Discover agent | — | Critic reviews the paper | PI agent across phases; Critic assesses hypotheses and challenges results as graph moves | Literature for Theorist and Writer | — |
| **Harness** | Agent loop, tools, context, sandbox, journal, run store, budget, failure classes, progress | Vision input, resume, import contract | Research-context ingest, descriptive module, code-checked terminal tools, researcher callback, `awaiting_review` stop | Discover moves as tools; Discover budget | — | — | Working memory, researcher input, per-phase budgets | Literature tool | Verify package |
| **Evaluation** | — | — | — | — | Planted (leak, few clusters, bounded outcome) and null suites, headline metrics, first comparisons, adoption records | Traced-number share | PI agent vs playbook, Critic on vs off | — | — |

---

## M0 — Mini scientist

**Outcome.** A researcher gives a brief and a CSV and receives a complete, readable paper: what the data needed, what exploration showed, one hypothesis, and its test. Rough, but real end to end.

**Scope.**
- All five phases in order under a fixed PI playbook (ARCHITECTURE §4).
- Roles PI, Theorist, Analyst, Judge, Writer, each in its own session (§6).
- Search engine with draft/debug/improve, code checks, typed Judge answers and best-node selection (§5.1–5.3, §8).
- Stages `data`, `explore` and one combined experiment stage (§5.4).
- Harness: model client with retry, agent loop, the Analyst tools, context assembly with untrusted wrapping, sandbox, journal, write-once run store, money budget priced per model with prompt caching, failure classes, progress (§7).
- Publication: fixed template, named-result numbers with `??` on unknown names, the fixed `exploratory` label, generated appendix, PDF when an engine exists (§10 steps 3, 4, 8).
- CLI: `popper run <example_dir | --research R --data D> [--config C] [--runs-dir R] [--quiet]`, and `popper pdf <run>`.

**Acceptance.**
- On `student_performance` with a real model: the paper reports the planted data issues it fixed (duplicates, `absent`, impossible values, income labels), finds a positive effect of study hours, has no `??`, costs under $5 and finishes under 45 minutes.
- Tests cover config merge, budget stop, model-call retry, turn limit, node selection, results validation, number rendering, the sandbox (timeout, credentials, inputs), a stage recovering from bad replies, and an end-to-end run with a scripted model.
- CI gate passes.

**Out.** Split experiment stages, figure judging, several hypotheses, researcher input, going back, Critic, search map, holdout.

**Risks.** Agentic nodes cost more tokens per node than single-shot code; watch cost per run against the $5 gate.

---

## M1 — Trustworthy results

**Outcome.** A researcher can see whether the main result survives reasonable alternative analyses and how widely the attempts disagreed, the paper says so with a label no model sets, and the run keeps rows back so it can be verified later.

**Scope.**
- Experiment stages `baseline` → `main` → `robustness`, each seeding the next, with per-stage step budgets (§5.4).
- Robustness as a multiverse: variants over recorded cleaning choices, specifications, subgroups and resampling; at least one adversarial check; computed stability label (§5.5).
- Specification curve over the variants and every `ok` experiment node (§5.5).
- Judge blind to effect estimates in experiment stages; Judge reads figures, and a misleading or unreadable figure lowers the score with a stated reason (§5.3).
- Hypothesis contract: one primary estimand, expected direction, refuting result, planned test (§4).
- Holdout set aside at ingest, grouped by an id column when given (§11). No verify command yet.
- `popper resume <run>` restarts from the last completed node (§7.6).
- Import contract for the dependency rules, checked in CI (§3).
- `examples/student_performance_null`: the demo data with the outcome shuffled, a second demo where the right answer is "no effect".
- Publication: robustness section and a table of the main estimate across specifications.
- Paper structure: Abstract, Introduction, Data and Methods (with the change table), Results (exploratory, then main and robustness subsections), Discussion with limitations, Conclusion. A main-results table rendered from results files. At most four figures, each placed next to the paragraph that refers to it with `\ref`. The appendix keeps only the experiment code (§10).
- Harness gaps seen in M0: the submitted script runs in a folder that scratch snippets cannot reach; scratch runs are journaled as `exec`; failed tool calls return an error status to the model (§7.2, §7.5).

**Acceptance.**
- The demo paper shows the study-hours estimate under at least three specifications with a specification curve and a stability label.
- The demo paper follows the section order above, and every figure is referenced in the text.
- On the demo data with the outcome shuffled, the paper claims no effect or labels the result `fragile`.
- On the demo with a real model, the stability label agrees with the variant intervals the paper shows: when every variant interval excludes zero with the main sign and the adversary passes, the label is `stable`, and every variant differs from the main specification.
- Both demos complete on a real model; scripted runs alone do not close the milestone.
- Tests cover stage chaining, estimate redaction in the Judge input, images reaching the Judge, the stability label on fixture variants, holdout rows never reaching a stage input, and resuming a run interrupted mid-stage.

**Out.** Diverse drafts (a later challenger), decision layer, several hypotheses, researcher input, going back, data before/after figures.

**Risks.** Variant count drives cost; the stage budget bounds it. The 80% stability share is a default to revisit in M4.

---

## M2 — Grounded frame

**Outcome.** A researcher gives a research context and a dataset. An agent turns it into a Research Frame (problem, questions, concepts, scope, assumptions, unknowns, directions), the researcher steers it item by item, and a second agent grounds it in the data: what the data measure, how each concept is represented, what is missing. When the data cannot represent the frame, the run goes back to the frame instead of silently changing research intent. The paper states every proposal, concern and warning it relied on.

**Scope.**
- Research context `research.md`: narrative body with optional front matter (`domain`, `objectives`, `variables`, `design`, `assumptions`, `constraints`, `concepts`, `notes`); entries `confirmed`, `proposed` or `unknown`; replaces `brief.md`; `popper run <example_dir | --research R --data D> [--auto]`; validated at ingest against the dataset (§4.1).
- One role-free descriptive-statistics module in the harness behind the Theorist's and Steward's evidence and `inspect_data`, on discovery raw rows and on the prepared data (§4.2).
- Understand as one Theorist session: explore, critique, synthesize; `ask_researcher`; `submit_frame` checked by code (evidence must resolve, no change to confirmed entries); computed framing warnings (§4.1).
- Review: `review.yaml` with stable item ids, signals approve / edit / reject / unknown with notes, status `awaiting_review`, `popper resume [--review FILE]`, one revision session, `--auto` (§4.1).
- Ground as one Data Steward session replacing the `data` tree stage: `submit_ground` re-run from scratch and checked by code; operationalization (proposed), typed concerns, readiness facts; frame concerns return to Understand at most once (§4.3).
- Discover reads the frame and the foundation; hypothesis gates replaced by computed warnings (§4.4).
- Publication: operationalization table, generated limitations, raw-access disclosure (§10).
- Examples move to `research.md`; one keeps a body-only research context.

**Acceptance.**
- The demo stops with `awaiting_review` and a readable `review.yaml`; after `popper resume` the paper has an operationalization table, generated limitations and a positive study-hours effect.
- On the null demo, the paper claims no effect or labels the result `fragile`.
- On the body-only example under `--auto`, the run completes and the paper lists the proposed entries it relied on.
- Tests cover research-context validation, the descriptive module on fixtures, evidence checks, review signal application, the review stop and resume (including a crash between commit and checkpoint), a rejected submit returned to the agent and fixed, one reframe on a frame concern, readiness facts, hypothesis warnings, and holdout rows never reaching a session or tool.

**Out.** Hypothesis gate, hard cluster rule, closed method vocabulary with declared plans, typed rival checks, SESOI contract, confirm partition, sample flow and characteristics tables, literature, several hypotheses, the Discover agent.

**Risks.** Agent sessions can run long; turn and submit limits bound them. A reframe roughly doubles Understand and Ground cost; it is bounded to one. Ground without best-of-N may prepare data less well; M4 compares it with the tree stage.

---

## M3 — Discover agent

**Outcome.** Discovery behaves like an investigation: an agent decides which question to explore, when observations suffice for a hypothesis, and which hypothesis to test, while the tree still runs every stage underneath so attempts stay comparable and every `ok` node is reported. Every tested hypothesis says how it was generated, what it predicted before the test, whether the data allowed the test, and whether the result matched the prediction.

**Scope** (§4.6).
- Research graph under `discover/graph/`: append-only nodes `question`, `observation`, `hypothesis`, `result`, `assessment` with `derived_from`, `branch`, `artifact`, `by` and `reason`; seeded by code from frame questions, directions and unknowns and from foundation concerns, keeping their ids.
- Discover agent session with the moves `explore(question)`, `hypothesize(question)`, `test(hypothesis)` and `finish`, plus `read_artifact` and a code-built graph view; one move at a time, each journaled with its target and reason; ends on `finish`, no open question, or its budget. The phase-3/4 playbook stays available for evaluation.
- Hypotheses with `origin` `frame` or `observation` and `derived_from`; two or three candidates per `hypothesize`, the unchosen ones kept as nodes; a computed flag when a primary estimand repeats an existing hypothesis; computed `suggested_by_test_data`.
- One `primary` prediction per hypothesis (estimand, direction) replaces the free-text refuting result.
- Pre-test description per tested hypothesis from the descriptive module: population and complete cases, exposure levels or support, outcome distribution, co-missingness, clusters; method fit and the cluster warning read it; one Theorist revision of the planned test after reading it.
- Frozen test specification whose hash every test node carries; computed verdict per prediction; `result` nodes with `predicted_before_result`.
- Publication: hypothesis origin, pre-test sample table, verdict beside the stability label, candidate claims from `finish`, and a research-path section from the graph listing dead ends and null results.

**Acceptance.**
- On the demo the agent explores at least two questions it chose, the journal states why each move ran, and the paper shows the origin, the pre-test table and the verdict of the tested hypothesis.
- On the null demo the verdict is `inconclusive` or the result is `fragile`, and the paper claims no effect.
- Tests cover graph append and seeding (a node citing a missing node is rejected), the verdict on fixture intervals for every row of its table, the pre-test description on a fixture (no outcome–exposure relation in its output), `suggested_by_test_data`, the repeated-estimand flag, and a scripted Discover agent run with `FakeLLM` that explores twice, tests once and finishes.

**Out.** `interpret` and the origins `rival` and `followup`; rival and auxiliary predictions; `threshold` and the `negligible` verdict (with SESOI); balance in the pre-test description; several hypotheses tested per run; Critic moves; parallel branches; PI agent across phases; researcher choice of hypotheses.

**Risks.** The agent may explore without converging; the Discover budget and the open-question stop bound it. Candidates may collapse onto one estimand; the repeated-estimand flag makes it visible and M4 measures it.

---

## M4 — Evidence baseline

**Outcome.** Every later change is judged by measurement. The team knows how often Popper reports an effect that is not there, how well it recovers one that is, whether it picks the right estimand and method, and what a run costs.

**Scope** (§13).
- Suites: planted (2 synthetic datasets with known effects, planted data issues, a reference research context, an outcome-derived leak column, a few-cluster design and a bounded outcome), null (1 dataset with no effect, several seeds).
- Headline metrics: null false-finding rate, share of traced numbers. Per-run metrics: effect recovery, role-proposal accuracy against the reference research context, estimand recovery, method fit, cluster-rule adherence, leak pick rate, data-issue fix rate, holdout gap, node failure rate, cost, wall time.
- Comparisons at equal model and budget, using existing config switches and inputs only: agentic vs single-shot nodes (`max_turns = 1`); 1 vs 3 drafts; figure judging on vs off; research-context body only vs with front matter; Research Frame with vs without researcher review; Ground agent vs `data` tree stage; warnings vs gates on roles and clusters.
- Adoption record per comparison in `evals/decisions.md`.

**Acceptance.** One command (`popper-eval`) generates the table, and the shipped defaults follow the recorded decisions.

**Out.** Reference suites (BLADE, DiscoveryBench) and contamination checks, which join once the planted and null suites are stable.

---

## M5 — Publication quality

**Outcome.** The paper compiles without manual fixes and every number and claim can be checked against the run.

**Scope** (§10).
- Figure aggregation from best nodes' saved outputs.
- Writer reflection on build errors and section completeness.
- Figure/caption check by the vision model.
- Number audit and consistency checks, reported in the review file.
- Introduction drawn from the research-context objectives and audience.
- Claims file beside the PDF.
- Critic rubric review (soundness, clarity, limitations, faithfulness) and one Writer revision.
- Ground adds before/after figures for changed columns and range checks on derived variables.
- AI-generation disclosure.
- Search map: a static page of the trees with each node's code, output, figures, score and kind.

**Acceptance.**
- On three datasets the PDF compiles without manual fixes, the review file is written, and the audit reports at most 2 untraced numbers per paper.
- Tests cover the number audit, consistency checks (flag a mismatched mean, pass a correct one) and rendering the search map from a fixture run.

---

## M6 — Research loop

**Outcome.** The run behaves like a research process: it proposes and challenges several hypotheses, lets the researcher choose, learns from results, and goes back when something is wrong.

**Scope.**
- PI becomes an agent across phases, building on the Discover agent, with tools to run a phase, open a new Ground attempt, ask the researcher, update memory and finish; the playbook stays the default order and every return is journaled with a reason (§4, §6).
- The PI may revise the Research Frame after results as a new attempt with a journaled reason; research context gains researcher `hypotheses` (§4.1).
- Hypotheses may state a mechanism with auxiliary predictions, each tested as a secondary estimand (§4, §4.3).
- 3–5 hypotheses with reflection, each in the hypothesis contract with computed warnings, drawn from the research context, exploration and researcher hypotheses, each recording its origin; one experiment tree per chosen hypothesis.
- The `interpret` move: an assessment per result that closes or opens questions; origins `rival` and `followup`; rival predictions tested as robustness variants or adversarial checks, and a hypothesis stands only when its rivals' predictions are not supported (§4.6).
- Critic scores each hypothesis on the hypothesis-quality rubric before the choice and challenges each main result before publication, as graph assessments that never change a result (§4.4, §4.6, §6, §9).
- Label intervals at level 1 − α/k when k hypotheses are tested (§5.5).
- Researcher input on the CLI (choose, edit, note); `--auto` lets the PI choose; choices are attributed.
- Working memory citing node ids, read by the PI and Analysts (§7.3).
- Per-phase and total budgets.
- Publication: one results subsection per tested hypothesis, each with its verdicts and rival outcomes.
- Evaluation: PI agent vs playbook and Critic on vs off, recorded in `evals/decisions.md`.

**Acceptance.**
- On a fixture with a data issue that only shows during experiments (a unit mismatch in one school), the run opens a new Ground attempt and the paper reports it.
- A second-round hypothesis cites first-round results.
- `--auto` makes no researcher calls. A scripted PI run with a reopen and a revision passes.
- The PI agent is the default only if the evaluation does not show it worse than the playbook.

**Out.** Parallel trees, literature.

**Risks.** An agent PI can loop; budgets and the default order bound it.

---

## M7 — Literature

**Outcome.** Framing, hypotheses and the related-work section rest on real, retrieved prior work (§12).

**Scope.** `search_literature` over OpenAlex for Theorist and Writer; Understand adds `domain` background to the research context and proposes background, mechanisms and confounders as `proposed` research-context entries with retrieved evidence (§4.1); literature as a hypothesis origin, with mechanisms that may cite retrieved work; hypotheses record replicate/extend/contradict as coverage; related-work section with BibTeX; only retrieved records are cited; queries carry concepts, never data values.

**Acceptance.** The demo paper cites at least five resolved works with no unresolved keys.

---

## M8 — Verify

**Outcome.** A researcher can confirm a chosen result once on data the search never saw (§11).

**Scope.** `popper verify <run> <result>` locks the scripts and a margin (the hypothesis `sesoi` when it was set before exploration), runs once on the holdout set aside since M1, computes the outcome, and regenerates the paper with only that label changed.

**Acceptance.** Tests show a failed verify is `inconclusive` and cannot be repeated. On the demo dataset the study-hours effect is confirmed.

---

## M9 — Long-term track

Capabilities Popper keeps as goals but does not build yet. Each waits for its trigger; when the trigger is met it becomes a milestone of its own with an outcome, demo gate and, where §1 excludes it today, an ARCHITECTURE scope change first. The M4 evaluation decides whether an item that adds a mechanism stays.

| Item | Why it waits | Trigger to start | ARCHITECTURE |
|---|---|---|---|
| Decision layer (decision model answers Judge questions, `shadow` before `on`) | An optimization of Judge cost and calibration; nothing to calibrate against before M4 | M4 shows Judge cost or disagreement worth reducing | §8 |
| Diverse drafts | Unmeasured benefit | M4 draft-diversity metric shows drafts collapsing onto one approach | §5.2 |
| Hypothesis tournament (pairwise ranking of many hypotheses) | M6 handles 3–5 hypotheses without it | Runs routinely produce more hypotheses than the researcher can compare | §6 |
| Parallel Analysts per stage | Sequential nodes are cheaper to debug; wall time is not yet the bottleneck | Wall time, not cost, blocks the demo gates | §6 |
| Container sandbox and network isolation | Single-user local use only | Before any shared or hosted use | §7.4 |
| Reference suites (BLADE, DiscoveryBench) and contamination checks | Planted and null suites come first | M4 suites stable across two milestones | §13 |
| Working memory across runs | One run per question today | Researchers repeatedly rerun the same dataset with new questions | §7.3 |
| Hypothesis code gate on roles, order, adjustment set and level sizes | Warnings first; a gate could block valid plans | M4 shows warnings missed failures that changed conclusions | §4.4 |
| Typed rival checks and SESOI contract, with prediction `threshold` and the `negligible` verdict | Rivals stated in prose for now | M4 shows hypotheses facing no testable rival or no stated magnitude | §4, §4.4, §4.6 |
| Parallel branches in Discover (one session per branch) | Moves are sequential and cheaper to debug | Wall time of the Discover agent blocks the demo gates | §4.6, §6 |
| Hard cluster rule and declared method plans (`analysis.json`) | Few-cluster advice is a warning | M4 shows few-cluster inference changing labels | §4.5 |
| Confirm partition | Off by default and unbuilt | M4 shows a holdout gap that a partition would close | §11 |
| Shuffled-outcome scratch for the Steward | Ground forbids using, not seeing, relations | M4 shows preparation choices that track the outcome–exposure relation | §4.3 |
| Sample flow and sample characteristics tables | Limitations and the change table cover current needs | M5 publication quality or a reviewer asks for them | §10 |
| Balance and precision groups, `underpowered` label | Need settled roles and a `sesoi` set before exploration | M4 shows role proposals accurate and hypotheses failing for lack of rows | §4.2, §4.3 |
| Diagnostic-triggered robustness variants | No measured failure yet | M4 shows skewed, overdispersed or sparse cases changing labels | §4.4 |
| Method fit as a gate | A label first; a gate could block valid plans | M4 shows `mismatch` plans producing wrong estimates | §4.4 |
| Censored-outcome estimator | Bounded outcomes are stated as limitations | The planted bounded outcome shows attenuation changing conclusions | §4.4 |
| Missing-data mechanism tests (e.g. Little's MCAR test) | Co-missing patterns and missing share by cluster cover current needs | M4 shows missing-data handling driving `fragile` labels | §4.2 |
| Sample representativeness against a target population | Needs population margins the research context does not hold | A researcher supplies population margins | §4.1 |
| Causal-graph adjustment (DAG in the research context) | Confounder lists and role checks cover current needs | M4 shows the gate missing mediators or colliders | §4.3 |
| Multiple datasets and joins per run | Out of scope in §1 | A real research context needs a second table | §1 scope change |
| Non-tabular data (text, images) via feature extraction | Out of scope in §1 | Tabular pipeline and M4 metrics stable | §1 scope change |
| Web UI and API | The CLI and search map serve one researcher | A user outside the team runs Popper | §1 scope change |

---

## Closing a milestone

- Set its Status here in the same change that finishes it.
- If building it changed a contract, update ARCHITECTURE.md in that change.
- Remove its spec and plan from `docs/specs/`.

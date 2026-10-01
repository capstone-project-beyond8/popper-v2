# Roadmap

Product milestones for Popper. Each milestone is a shippable increment: a researcher can run it and gets something more useful than the milestone before. [ARCHITECTURE.md](ARCHITECTURE.md) defines the components and contracts; this document decides which of them ship when, and what "done" means.

## How milestones work

- **Outcome first.** A milestone is stated as what a researcher can do after it ships, then the capabilities that deliver it.
- **Demo gate.** One command a person can run, producing output they can read. A milestone is done only when its gate and acceptance criteria pass on a real model.
- **Size estimate.** A rough guess of `src/` lines for planning, not a limit. Code stays as small as the outcome allows.
- **From milestone to code.** Milestone → spec in `docs/specs/` (refines ARCHITECTURE contracts, never contradicts them) → implementation plan → build → close. A spec is removed once its milestone closes.
- **Scope discipline.** Nothing is built ahead of its milestone. After M3, a new mechanism names the failure it fixes and its evaluation result.

## Product overview

| Milestone | Product outcome | Demo gate | Depends on | Size (est.) | Status |
|---|---|---|---|---|---|
| **M0** Mini scientist | From a brief and a CSV, get a complete paper with one tested hypothesis | `popper run examples/student_performance` → paper with framing, data changes, exploration figures, one hypothesis and a tested result | — | ~2k | done |
| **M1** Trustworthy results | Every main result comes with robustness evidence and a computed stability label, and the run can later be verified | The paper shows baseline, main and robustness results, a specification curve over every attempt and a stability label | M0 | ~2.5k | done |
| **M2** Grounded hypotheses | The researcher reviews an agent-cleaned research context before analysis; the hypothesis rests on what the variables mean, faces its rivals, respects the design's clusters and says which rows tested it | `popper run examples/student_performance` stops for review of the cleaned research context; after `popper resume` → paper with a sample flow, a sample characteristics table, rival explanations with their checks, school fixed effects and the bounded outcome stated | M1 | ~1.5k | todo |
| **M3** Evidence baseline | The team can tell whether a change makes Popper better | `popper-eval` prints the null false-finding rate, effect recovery, estimand recovery, holdout gap and cost for two configurations | M2 | + `evals/` | todo |
| **M4** Publication quality | A paper that compiles cleanly and can be checked claim by claim | Clean compile on three datasets; review, claims file and search map | M1 | ~3k | todo |
| **M5** Research loop | The researcher steers; results change what the run does next | Several critiqued hypotheses, researcher picks, a second round builds on the first, a late data problem reopens the data stage; eval compares it with the playbook | M3, M4 | ~3.5k | todo |
| **M6** Literature | Framing, hypotheses and related work grounded in real prior work | The demo paper cites resolved prior work | M5 | ~4k | todo |
| **M7** Verify | Confirm a chosen result once on held-back data | `popper verify <run> <result>` → a computed outcome | M3 | ~4.5k | todo |
| **M8** Long-term track | Deferred capabilities, each started when its trigger is met | Per item | M3 | per item | parked |

## Capability growth

| Area | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 |
|---|---|---|---|---|---|---|---|---|
| **Ideation** | Profile and framing with one reflection | — | Research context with per-entry provenance; agent proposes variable meanings with evidence; open questions listed; review table and stop before analysis; framing refers to roles | — | Introduction from objectives and audience | Objectives and researcher hypotheses in the research context; clarifying questions asked one at a time; per-entry approval; research-context revision after results | Domain background in the research context; prior work shapes questions | — |
| **Data** | Agentic `data` stage, change log, row counts | Holdout set aside at ingest | One descriptive-statistics module, before and after `data`; confirm partition, off by default | — | Before/after figures, derived-variable checks | Reopened when a later phase finds a problem | — | — |
| **Exploration & hypothesis** | Agentic `explore` stage, one hypothesis | Hypothesis contract (one primary estimand, refuting result) | SESOI, adjustment set, typed rival checks; code gate on roles, order and clusters | — | — | 3–5 hypotheses with mechanism and auxiliary predictions, Critic rubric, researcher choice, revision from results | Relation to prior work | — |
| **Experiment** | One combined stage | `baseline` → `main` → `robustness`, multiverse, adversarial check, stability label | Layered method vocabulary, computed method fit, hard cluster rule; rival checks as variants or adversarial checks | — | — | One tree per chosen hypothesis; label intervals adjusted for several hypotheses | — | Locked re-run on holdout |
| **Search engine** | Draft/debug/improve, typed Judge answers | Judge blind to estimates, reads figures | Judge method reference from the layered vocabulary | — | — | — | — | — |
| **Publication** | Template paper, named-result numbers, fixed label | Standard paper structure, results table, robustness section, specification curve | Sample flow, sample characteristics, rivals and checks, method fit, `tested_on`, unconfirmed assumptions and bounded outcome | — | Figure aggregation, checks, claims file, rubric review, search map, disclosure | Per-hypothesis results, research path | Related work, citations | Verified labels |
| **Roles** | PI playbook, Theorist, Analyst, Judge, Writer | — | Theorist runs ideation, states rivals | — | Critic reviews the paper | PI agent, Critic | Literature for Theorist and Writer | — |
| **Harness** | Agent loop, tools, context, sandbox, journal, run store, budget, failure classes, progress | Vision input, resume, import contract | Research-context ingest, descriptive-statistics module, `awaiting_review` stop | — | — | PI tools, `ask_researcher`, working memory, researcher input, per-phase budgets | Literature tool | Verify package |
| **Evaluation** | — | — | — | Planted (leak, few clusters, bounded outcome) and null suites, headline metrics, first comparisons, adoption records | Traced-number share | PI agent vs playbook, Critic on vs off | — | — |

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
- CLI: `popper run <example_dir | --brief B --data D> [--config C] [--runs-dir R] [--quiet]`, and `popper pdf <run>`.

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

**Risks.** Variant count drives cost; the stage budget bounds it. The 80% stability share is a default to revisit in M3.

---

## M2 — Grounded hypotheses

**Outcome.** A researcher gives a research context and a dataset, reviews the cleaned research context the agent returns (what it understood, what each variable means, what it could not tell), and receives a hypothesis that passes code checks on roles, timing and clusters, faces its rival explanations with typed checks, and states its method fit and which rows tested it. The paper shows who was studied and how the sample was reduced.

**Scope.**
- Research context `research.md`: narrative body with optional front matter holding `variables`, `design`, `assumptions`, `constraints`, `sesoi` and `notes`; each entry `confirmed`, `computed`, `proposed` or `unknown`; replaces `brief.md`; `popper run <example_dir | --research R --data D>`; validated at ingest against the dataset (§4.1).
- Code checks, gates and labels use `confirmed` and `computed` entries; a `proposed` entry only makes a check stricter; `notes` steer prompts only (§4.1).
- Ideation steps 1a, 1b, 1e and 1f (§4.1): code lists the gaps; the Theorist restates the request and proposes meaning, unit, type, role and order with evidence, listing open questions; the run prints the cleaned research context as a table and stops with status `awaiting_review`; `popper resume` commits the researcher's edits; `--auto` skips the stop. Framing keeps questions, directions and data concerns and refers to roles instead of listing key variables.
- One role-free descriptive-statistics module in the harness behind the ingest profile, the Judge's data summary and `inspect_data`: structure, data quality, univariate distribution with floor and ceiling share, cluster count and sizes, sample flow and the sample characteristics table, in the `results.json` schema, on discovery raw rows and on `processed.parquet` (§4.2).
- Confirm partition built and off by default: when on, `data` fits on explore rows and replays on confirm rows, `explore` reads explore rows, experiment stages read confirm rows; every hypothesis records `tested_on` (§11).
- Layered closed method vocabulary replacing the current method list; computed method fit printed in the paper; the cluster rule as a hard check on the planned test and the robustness schedule; thresholds under `analysis` in config (§4.4).
- Hypothesis contract adds `sesoi` (set before exploration, else recorded as `post_exploration`), `adjustment_set` and rival explanations with typed checks: `adjustment` becomes a robustness variant, `negative_control` an adversarial check, `sensitivity` a reported bound. Code gate on roles, order, adjustment set and clusters (§4, §4.3, §5.5).
- Publication: sample flow, sample characteristics table without significance tests, rival explanations and their checks, method fit, the `tested_on` sentence, unconfirmed research-context assumptions and a bounded outcome as limitations (§10).
- `examples/student_performance` and `examples/student_performance_null` move to `research.md`; one keeps a body-only research context to exercise ideation.

**Acceptance.**
- The demo stops with `awaiting_review` and prints the cleaned research context as a table; after `popper resume` the run completes.
- The demo's three schools lead to school fixed effects with the observed-clusters limitation stated, in the planned test and in every robustness variant; no node reports cluster-robust SE or the wild cluster bootstrap.
- The demo outcome's ceiling at 100 is reported as a bounded outcome in the limitations.
- The demo hypothesis names at least one rival explanation; its `adjustment` check appears among the robustness variants and a `negative_control` check, when present, among the adversarial checks, never in the stability share.
- Every number in the sample flow and sample characteristics table resolves to a descriptive-statistics artifact.
- On the null demo, the paper claims no effect or labels the result `fragile`.
- On the body-only example under `--auto`, ideation proposes outcome and exposure roles with evidence, the gate still rejects an `id` or `post_outcome` exposure, and the paper lists the unconfirmed entries it relied on.
- Tests cover research-context validation (missing column, invalid type, role or status), gaps computed from a fixture, the review stop and its resume, a `proposed` entry tightening but never loosening a check, the descriptive-statistics module on fixtures (types, co-missing patterns, cluster sizes, floor and ceiling share), the confirm partition when on (no confirm row reaches `explore` or the fitting of `data`), each gate rule firing on a bad fixture and staying silent on a good one, the cluster rule across the three cluster-count bands, and rival checks routed by type.

**Out.** Mechanism and auxiliary predictions, several hypotheses, Critic rubric on hypotheses, clarifying questions, literature, balance and precision groups, the `underpowered` label, diagnostic-triggered variants, method fit as a gate, a censored-outcome estimator, the confirm partition on by default.

**Risks.** Gate rejections can loop the Theorist; retries are bounded like schema retries. Writing front matter is a burden, so every field stays optional and ideation drafts it. A body-only run under `--auto` rests on proposals; the paper lists them, and M3 measures how often they are wrong.

---

## M3 — Evidence baseline

**Outcome.** Every later change is judged by measurement. The team knows how often Popper reports an effect that is not there, how well it recovers one that is, whether it picks the right estimand and method, and what a run costs.

**Scope** (§13).
- Suites: planted (2 synthetic datasets with known effects, planted data issues, a reference research context, an outcome-derived leak column, a few-cluster design and a bounded outcome), null (1 dataset with no effect, several seeds).
- Headline metrics: null false-finding rate, share of traced numbers. Per-run metrics: effect recovery, role-proposal accuracy against the reference research context, estimand recovery, method fit, cluster-rule adherence, leak pick rate, data-issue fix rate, holdout gap, node failure rate, cost, wall time.
- Comparisons at equal model and budget, using existing config switches and inputs only: agentic vs single-shot nodes (`max_turns = 1`); 1 vs 3 drafts; figure judging on vs off; research-context body only vs with front matter; agent-cleaned research context with vs without researcher review; confirm partition on vs off, which sets its default.
- Adoption record per comparison in `evals/decisions.md`.

**Acceptance.** One command (`popper-eval`) generates the table, and the shipped defaults follow the recorded decisions.

**Out.** Reference suites (BLADE, DiscoveryBench) and contamination checks, which join once the planted and null suites are stable.

---

## M4 — Publication quality

**Outcome.** The paper compiles without manual fixes and every number and claim can be checked against the run.

**Scope** (§10).
- Figure aggregation from best nodes' saved outputs.
- Writer reflection on build errors and section completeness.
- Figure/caption check by the vision model.
- Number audit and consistency checks, reported in the review file.
- Introduction drawn from the research-context objectives and audience.
- Claims file beside the PDF.
- Critic rubric review (soundness, clarity, limitations, faithfulness) and one Writer revision.
- Data stage adds before/after figures for changed columns and range checks on derived variables.
- AI-generation disclosure.
- Search map: a static page of the trees with each node's code, output, figures, score and kind.

**Acceptance.**
- On three datasets the PDF compiles without manual fixes, the review file is written, and the audit reports at most 2 untraced numbers per paper.
- Tests cover the number audit, consistency checks (flag a mismatched mean, pass a correct one) and rendering the search map from a fixture run.

---

## M5 — Research loop

**Outcome.** The run behaves like a research process: it proposes and challenges several hypotheses, lets the researcher choose, learns from results, and goes back when something is wrong.

**Scope.**
- PI becomes an agent on the same loop, with tools to run a stage, propose and revise hypotheses, reopen the data stage, ask the researcher, update memory and finish; the playbook stays the default order and every return is journaled with a reason (§4, §6).
- Ideation step 1c (§4.1): the Theorist asks open questions one at a time through `ask_researcher`, each with a proposed answer and an "unknown" option; the review stop offers per-entry approval on the CLI; the PI may revise the research context after results as a new attempt with a journaled reason.
- Research context gains `objectives` (fixed or open) and researcher `hypotheses` (§4.1).
- Hypotheses may state a mechanism with auxiliary predictions, each tested as a secondary estimand (§4, §4.3).
- 3–5 hypotheses with reflection, each in the hypothesis contract and through the gate, drawn from the research context, exploration and researcher hypotheses, each recording its origin; one experiment tree per chosen hypothesis.
- Critic scores each hypothesis on the hypothesis-quality rubric before the choice and challenges each main result before publication; critiques are assessments and never change a result (§4.3, §6, §9).
- Label intervals at level 1 − α/k when k hypotheses are tested (§5.5).
- Researcher input on the CLI (choose, edit, note); `--auto` lets the PI choose; choices are attributed.
- Working memory citing node ids, read by the PI and Analysts (§7.3).
- Per-phase and total budgets.
- Publication: one results subsection per tested hypothesis and a research-path section generated from the journal.
- Evaluation: PI agent vs playbook and Critic on vs off, recorded in `evals/decisions.md`.

**Acceptance.**
- On a fixture with a data issue that only shows during experiments (a unit mismatch in one school), the run reopens the data stage and the paper reports it.
- A second-round hypothesis cites first-round results.
- `--auto` makes no researcher calls. A scripted PI run with a reopen and a revision passes.
- The PI agent is the default only if the evaluation does not show it worse than the playbook.

**Out.** Parallel trees, literature.

**Risks.** An agent PI can loop; budgets and the default order bound it.

---

## M6 — Literature

**Outcome.** Framing, hypotheses and the related-work section rest on real, retrieved prior work (§12).

**Scope.** `search_literature` over OpenAlex for Theorist and Writer; ideation step 1d adds `domain` to the research context and proposes background, mechanisms and confounders as `proposed` research-context entries with retrieved evidence (§4.1); literature as a hypothesis origin, with mechanisms that may cite retrieved work; hypotheses record replicate/extend/contradict as coverage; related-work section with BibTeX; only retrieved records are cited; queries carry concepts, never data values.

**Acceptance.** The demo paper cites at least five resolved works with no unresolved keys.

---

## M7 — Verify

**Outcome.** A researcher can confirm a chosen result once on data the search never saw (§11).

**Scope.** `popper verify <run> <result>` locks the scripts and a margin (the hypothesis `sesoi` when it was set before exploration), runs once on the holdout set aside since M1, computes the outcome, and regenerates the paper with only that label changed.

**Acceptance.** Tests show a failed verify is `inconclusive` and cannot be repeated. On the demo dataset the study-hours effect is confirmed.

---

## M8 — Long-term track

Capabilities Popper keeps as goals but does not build yet. Each waits for its trigger; when the trigger is met it becomes a milestone of its own with an outcome, demo gate and, where §1 excludes it today, an ARCHITECTURE scope change first. The M3 evaluation decides whether an item that adds a mechanism stays.

| Item | Why it waits | Trigger to start | ARCHITECTURE |
|---|---|---|---|
| Decision layer (decision model answers Judge questions, `shadow` before `on`) | An optimization of Judge cost and calibration; nothing to calibrate against before M3 | M3 shows Judge cost or disagreement worth reducing | §8 |
| Diverse drafts | Unmeasured benefit | M3 draft-diversity metric shows drafts collapsing onto one approach | §5.2 |
| Hypothesis tournament (pairwise ranking of many hypotheses) | M5 handles 3–5 hypotheses without it | Runs routinely produce more hypotheses than the researcher can compare | §6 |
| Parallel Analysts per stage | Sequential nodes are cheaper to debug; wall time is not yet the bottleneck | Wall time, not cost, blocks the demo gates | §6 |
| Container sandbox and network isolation | Single-user local use only | Before any shared or hosted use | §7.4 |
| Reference suites (BLADE, DiscoveryBench) and contamination checks | Planted and null suites come first | M3 suites stable across two milestones | §13 |
| Working memory across runs | One run per question today | Researchers repeatedly rerun the same dataset with new questions | §7.3 |
| Balance and precision groups, `underpowered` label | Need settled roles and a `sesoi` set before exploration | M3 shows role proposals accurate and hypotheses failing for lack of rows | §4.2, §4.3 |
| Diagnostic-triggered robustness variants | No measured failure yet | M3 shows skewed, overdispersed or sparse cases changing labels | §4.4 |
| Method fit as a gate | A label first; a gate could block valid plans | M3 shows `mismatch` plans producing wrong estimates | §4.4 |
| Censored-outcome estimator | Bounded outcomes are stated as limitations | The planted bounded outcome shows attenuation changing conclusions | §4.4 |
| Missing-data mechanism tests (e.g. Little's MCAR test) | Co-missing patterns and missing share by cluster cover current needs | M3 shows missing-data handling driving `fragile` labels | §4.2 |
| Sample representativeness against a target population | Needs population margins the research context does not hold | A researcher supplies population margins | §4.1 |
| Causal-graph adjustment (DAG in the research context) | Confounder lists and role checks cover current needs | M3 shows the gate missing mediators or colliders | §4.3 |
| Multiple datasets and joins per run | Out of scope in §1 | A real research context needs a second table | §1 scope change |
| Non-tabular data (text, images) via feature extraction | Out of scope in §1 | Tabular pipeline and M3 metrics stable | §1 scope change |
| Web UI and API | The CLI and search map serve one researcher | A user outside the team runs Popper | §1 scope change |

---

## Closing a milestone

- Set its Status here in the same change that finishes it.
- If building it changed a contract, update ARCHITECTURE.md in that change.
- Remove its spec and plan from `docs/specs/`.

# Roadmap

Product milestones for Popper. Each milestone is a shippable increment: a researcher can run it and gets something more useful than the milestone before. [ARCHITECTURE.md](ARCHITECTURE.md) defines the components and contracts; this document decides which of them ship when, and what "done" means.

## How milestones work

- **Outcome first.** A milestone is stated as what a researcher can do after it ships, then the capabilities that deliver it.
- **Demo gate.** One command a person can run, producing output they can read. A milestone is done only when its gate and acceptance criteria pass on a real model.
- **Size estimate.** A rough guess of `src/` lines for planning, not a limit. Code stays as small as the outcome allows.
- **From milestone to code.** Milestone → spec in `docs/specs/` (refines ARCHITECTURE contracts, never contradicts them) → implementation plan → build → close. A spec is removed once its milestone closes.
- **Scope discipline.** Nothing is built ahead of its milestone. After M2, a new mechanism names the failure it fixes and its evaluation result.

## Product overview

| Milestone | Product outcome | Demo gate | Depends on | Size (est.) | Status |
|---|---|---|---|---|---|
| **M0** Mini scientist | From a brief and a CSV, get a complete paper with one tested hypothesis | `popper run examples/student_performance` → paper with framing, data changes, exploration figures, one hypothesis and a tested result | — | ~2k | in progress |
| **M1** Trustworthy results | Every main result comes with robustness evidence and a computed stability label, and the run can later be verified | The paper shows baseline, main and robustness results, a specification curve over every attempt and a stability label | M0 | ~2.5k | todo |
| **M2** Evidence baseline | The team can tell whether a change makes Popper better | `popper-eval` prints the null false-finding rate, effect recovery, holdout gap and cost for two configurations | M1 | + `evals/` | todo |
| **M3** Publication quality | A paper that compiles cleanly and can be checked claim by claim | Clean compile on three datasets; review, claims file and search map | M1 | ~3k | todo |
| **M4** Research loop | The researcher steers; results change what the run does next | Several critiqued hypotheses, researcher picks, a second round builds on the first, a late data problem reopens the data stage; eval compares it with the playbook | M2, M3 | ~3.5k | todo |
| **M5** Literature | Framing, hypotheses and related work grounded in real prior work | The demo paper cites resolved prior work | M4 | ~4k | todo |
| **M6** Verify | Confirm a chosen result once on held-back data | `popper verify <run> <result>` → a computed outcome | M2 | ~4.5k | todo |
| **M7** Long-term track | Deferred capabilities, each started when its trigger is met | Per item | M2 | per item | parked |

## Capability growth

| Area | M0 | M1 | M2 | M3 | M4 | M5 | M6 |
|---|---|---|---|---|---|---|---|
| **Ideation & framing** | Profile and framing with one reflection | — | — | — | Researcher confirms or edits framing | Prior work shapes questions | — |
| **Data** | Agentic `data` stage, change log, row counts | Holdout set aside at ingest | — | Before/after figures, derived-variable checks | Reopened when a later phase finds a problem | — | — |
| **Exploration & hypothesis** | Agentic `explore` stage, one hypothesis | Hypothesis contract (one primary estimand, refuting result) | — | — | 3–5 hypotheses, Critic, researcher choice, revision from results | Relation to prior work | — |
| **Experiment** | One combined stage | `baseline` → `main` → `robustness`, multiverse, adversarial check, stability label | — | — | One tree per chosen hypothesis | — | Locked re-run on holdout |
| **Search engine** | Draft/debug/improve, typed Judge answers | Judge blind to estimates, reads figures | — | — | — | — | — |
| **Publication** | Template paper, named-result numbers, fixed label | Standard paper structure, results table, robustness section, specification curve | — | Figure aggregation, checks, claims file, rubric review, search map, disclosure | Per-hypothesis results, research path | Related work, citations | Verified labels |
| **Roles** | PI playbook, Theorist, Analyst, Judge, Writer | — | — | Critic reviews the paper | PI agent, Critic | Literature for Theorist and Writer | — |
| **Harness** | Agent loop, tools, context, sandbox, journal, run store, budget, failure classes, progress | Vision input, resume, import contract | — | — | PI tools, working memory, researcher input, per-phase budgets | Literature tool | Verify package |
| **Evaluation** | — | — | Planted and null suites, headline metrics, first comparisons, adoption records | Traced-number share | PI agent vs playbook, Critic on vs off | — | — |

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
- Paper structure: Abstract, Introduction, Data and Methods (with the change table), Results (exploratory, then main and robustness subsections), Discussion with limitations, Conclusion. A main-results table rendered from results files. At most four figures, each placed next to the paragraph that refers to it with `ef`. The appendix keeps only the experiment code (§10).
- Harness gaps seen in M0: the submitted script runs in a folder that scratch snippets cannot reach; scratch runs are journaled as `exec`; failed tool calls return an error status to the model (§7.2, §7.5).

**Acceptance.**
- The demo paper shows the study-hours estimate under at least three specifications with a specification curve and a stability label.
- The demo paper follows the section order above, and every figure is referenced in the text.
- On the demo data with the outcome shuffled, the paper claims no effect or labels the result `fragile`.
- Tests cover stage chaining, estimate redaction in the Judge input, images reaching the Judge, the stability label on fixture variants, holdout rows never reaching a stage input, and resuming a run interrupted mid-stage.

**Out.** Diverse drafts (a later challenger), decision layer, several hypotheses, researcher input, going back, data before/after figures.

**Risks.** Variant count drives cost; the stage budget bounds it. The 80% stability share is a default to revisit in M2.

---

## M2 — Evidence baseline

**Outcome.** Every later change is judged by measurement. The team knows how often Popper reports an effect that is not there, how well it recovers one that is, and what a run costs.

**Scope** (§13).
- Suites: planted (2 synthetic datasets with known effects and planted data issues), null (1 dataset with no effect, several seeds).
- Headline metrics: null false-finding rate, share of traced numbers. Per-run metrics: effect recovery, data-issue fix rate, holdout gap, node failure rate, cost, wall time.
- Comparisons at equal model and budget, using existing config switches only: agentic vs single-shot nodes (`max_turns = 1`); 1 vs 3 drafts; figure judging on vs off.
- Adoption record per comparison in `evals/decisions.md`.

**Acceptance.** One command (`popper-eval`) generates the table, and the shipped defaults follow the recorded decisions.

**Out.** Reference suites (BLADE, DiscoveryBench) and contamination checks, which join once the planted and null suites are stable.

---

## M3 — Publication quality

**Outcome.** The paper compiles without manual fixes and every number and claim can be checked against the run.

**Scope** (§10).
- Figure aggregation from best nodes' saved outputs.
- Writer reflection on build errors and section completeness.
- Figure/caption check by the vision model.
- Number audit and consistency checks, reported in the review file.
- Claims file beside the PDF.
- Critic rubric review (soundness, clarity, limitations, faithfulness) and one Writer revision.
- Data stage adds before/after figures for changed columns and range checks on derived variables.
- AI-generation disclosure.
- Search map: a static page of the trees with each node's code, output, figures, score and kind.

**Acceptance.**
- On three datasets the PDF compiles without manual fixes, the review file is written, and the audit reports at most 2 untraced numbers per paper.
- Tests cover the number audit, consistency checks (flag a mismatched mean, pass a correct one) and rendering the search map from a fixture run.

---

## M4 — Research loop

**Outcome.** The run behaves like a research process: it proposes and challenges several hypotheses, lets the researcher choose, learns from results, and goes back when something is wrong.

**Scope.**
- PI becomes an agent on the same loop, with tools to run a stage, propose and revise hypotheses, reopen the data stage, ask the researcher, update memory and finish; the playbook stays the default order and every return is journaled with a reason (§4, §6).
- 3–5 hypotheses with reflection, each in the hypothesis contract; one experiment tree per chosen hypothesis.
- Critic challenges each hypothesis before the choice and each main result before publication; critiques are assessments and never change a result (§6, §9).
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

## M5 — Literature

**Outcome.** Framing, hypotheses and the related-work section rest on real, retrieved prior work (§12).

**Scope.** `search_literature` over OpenAlex for Theorist and Writer; hypotheses record replicate/extend/contradict as coverage; related-work section with BibTeX; only retrieved records are cited; queries carry concepts, never data values.

**Acceptance.** The demo paper cites at least five resolved works with no unresolved keys.

---

## M6 — Verify

**Outcome.** A researcher can confirm a chosen result once on data the search never saw (§11).

**Scope.** `popper verify <run> <result>` locks the scripts and a margin, runs once on the holdout set aside since M1, computes the outcome, and regenerates the paper with only that label changed.

**Acceptance.** Tests show a failed verify is `inconclusive` and cannot be repeated. On the demo dataset the study-hours effect is confirmed.

---

## M7 — Long-term track

Capabilities Popper keeps as goals but does not build yet. Each waits for its trigger; when the trigger is met it becomes a milestone of its own with an outcome, demo gate and, where §1 excludes it today, an ARCHITECTURE scope change first. The M2 evaluation decides whether an item that adds a mechanism stays.

| Item | Why it waits | Trigger to start | ARCHITECTURE |
|---|---|---|---|
| Decision layer (decision model answers Judge questions, `shadow` before `on`) | An optimization of Judge cost and calibration; nothing to calibrate against before M2 | M2 shows Judge cost or disagreement worth reducing | §8 |
| Diverse drafts | Unmeasured benefit | M2 draft-diversity metric shows drafts collapsing onto one approach | §5.2 |
| Hypothesis tournament (pairwise ranking of many hypotheses) | M4 handles 3–5 hypotheses without it | Runs routinely produce more hypotheses than the researcher can compare | §6 |
| Parallel Analysts per stage | Sequential nodes are cheaper to debug; wall time is not yet the bottleneck | Wall time, not cost, blocks the demo gates | §6 |
| Container sandbox and network isolation | Single-user local use only | Before any shared or hosted use | §7.4 |
| Reference suites (BLADE, DiscoveryBench) and contamination checks | Planted and null suites come first | M2 suites stable across two milestones | §13 |
| Working memory across runs | One run per question today | Researchers repeatedly rerun the same dataset with new questions | §7.3 |
| Multiple datasets and joins per run | Out of scope in §1 | A real brief needs a second table | §1 scope change |
| Non-tabular data (text, images) via feature extraction | Out of scope in §1 | Tabular pipeline and M2 metrics stable | §1 scope change |
| Web UI and API | The CLI and search map serve one researcher | A user outside the team runs Popper | §1 scope change |

---

## Closing a milestone

- Set its Status here in the same change that finishes it.
- If building it changed a contract, update ARCHITECTURE.md in that change.
- Remove its spec and plan from `docs/specs/`.

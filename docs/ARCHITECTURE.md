# Popper Architecture

Target design of Popper, an AI scientist for quantitative tabular data. Specs and plans take their components, contracts, invariants and defaults from this document; [ROADMAP.md](ROADMAP.md) orders the build. A spec may refine a contract here but not contradict it. A change of contract changes this document first. Sources are numbered in §15; the design decisions behind each component are in §14.

![Popper architecture](images/architecture.svg)

## 1. Scope

- **Input:** a research brief and one tabular dataset. **Output:** a run folder with a LaTeX paper, a claims file, and every attempt, execution and decision that produced them.
- **In scope:** framing, data preparation, exploration, hypothesis generation, analysis by generated code, write-up, review, optional verification on held-back rows.
- **Out of scope:** data collection, multiple datasets per run, non-tabular data, shared multi-user deployment.
- **Quality attributes, in priority order:**
  1. _Traceability_: every number and claim resolves to executed code.
  2. _Honest labelling_: the standing of a result is computed, never asserted.
  3. _Recoverability_: a run resumes and every node re-runs.
  4. _Simplicity_: the smallest mechanism that meets 1–3.

## 2. Principles

1. **Output first.** Every increment ends in a run that produces a readable paper. Infrastructure is added only when a run needs it.
2. **Reproduce, then improve.** A mechanism taken from a published system is first built as published. An addition is a hypothesis tested at equal model and budget (§13).
3. **Agents work, the harness records.** Recording is a side effect of the harness, never a duty of an agent.
4. **Workflow where the steps are known, agents where they are not.** Phase order and stage sequence are code; work inside a node is an agent's [31].
5. **Ground truth from execution.** A result is what a script produced when the harness re-ran it from scratch [31].
6. **Labels, not locks.** Everything outside Verify is `exploratory`. Labels are computed by code and no model can raise them.
7. **Numbers come from artifacts.** Paper numbers are rendered from result files, never typed by a model [6].
8. **Try to break it.** Every main result meets robustness variants and at least one adversarial check [7, 17].
9. **Executable rules over prose rules.** A rule that matters is a check, a label or a renderer [36, 37].
10. **Measured restriction.** A new gate, reviewer or topology change needs an observed failure and an evaluation comparison [37].
11. **Append, never rewrite.** Run files are written once.
12. **One owner per concept.** Each concept has one module and one section here.

### 2.1 Invariants

Hold in every configuration; each is enforced by code and covered by a test.

| Invariant                                                             | Enforced by                                           |
| --------------------------------------------------------------------- | ----------------------------------------------------- |
| Every model call, tool call, execution and decision is journaled      | Harness (§7.5)                                        |
| Run files are write-once; a fix is a new node or assessment           | Run store (§9)                                        |
| `exploratory`, `stable`/`fragile`, `confirmed` are computed           | Label functions; the template prints them (§5.5, §11) |
| Paper numbers resolve to named results; unknown names are flagged     | Renderer and audit (§10)                              |
| Brief, dataset strings, outputs and retrieved text are untrusted data | Context assembly (§7.3)                               |
| No credentials in the run folder or script environments               | Sandbox and run store (§7.4, §7.5)                    |
| Holdout rows never reach a node or tool before the locked run         | Run store at ingest; Verify (§11)                     |
| The Judge never sees effect estimates when scoring                    | Judge input redaction (§5.3)                          |
| The dependency rules of §3 hold                                       | Import contract test (§3)                             |

## 3. Decomposition

| Subsystem       | Package                                                          | Owns                                                                                                             | Section    |
| --------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------- |
| Coordinator     | `coordinator/`                                                   | The playbook: phase order, transitions, run status                                                               | §4         |
| Research phases | `understand/`, `ground/`, `discover/`, `communicate/`, `verify/` | Stage goals, role prompts, phase outputs                                                                         | §4, §10–12 |
| Search engine   | `treesearch/`                                                    | Nodes, step policy, node evaluation, selection, the Analyst's tools                                              | §5         |
| Harness         | `harness/`                                                       | Model client, agent loop, tools mechanism, context, sandbox, journal, run store, budgets, config, decision layer | §7, §8     |
| Evaluation      | `evals/`                                                         | Suites, metrics, comparisons, adoption records                                                                   | §13        |

```text
cli ──► coordinator ──► understand · ground · discover · communicate · (verify)
                               │
                               ▼
                           treesearch ──► harness
```

Dependency rules:

- `harness` imports nothing else in Popper and holds no research logic.
- `treesearch` imports only `harness`; it knows no stage goals.
- Phase packages import only `harness` and `treesearch`, never each other.
- Only `coordinator` knows the playbook.
- `evals/` may import anything; production code never imports `evals/`.
- These rules are an import contract checked in CI, not a convention [36].
- Prompts live in `<package>/prompts/`. Default config ships in `harness/`; `--config` overrides key by key; `POPPER_MODEL` overrides every model route.

## 4. Run lifecycle

| #   | Phase                    | Package        | Contract                                                                                                                                 | Output                                           |
| --- | ------------------------ | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 1   | Ideation & framing       | `understand/`  | Brief + structural data profile → problem statement, research questions, required variables, distinct directions; self-reflection rounds | framing                                          |
| 2   | Data                     | `ground/`      | Search stage `data` (§5.4)                                                                                                               | clean dataset, change log                        |
| 3   | Exploration & hypothesis | `discover/`    | Search stage `explore`; observations → hypotheses in the contract below; Critic challenge; selection by researcher or PI                 | hypotheses                                       |
| 4   | Experiment               | `discover/`    | Per chosen hypothesis: stages `baseline` → `main` → `robustness`                                                                         | best nodes, estimates, figures, stability labels |
| 5   | Publication              | `communicate/` | Pipeline of §10                                                                                                                          | paper, claims file, review                       |
| —   | Verify (optional)        | `verify/`      | Contract of §11                                                                                                                          | verification records                             |

- **Hypothesis contract** [7]: one primary estimand (outcome, exposure, contrast, population), expected direction, the result that would refute it, planned test, source nodes, `supplied_by`. Interactions and moderators are secondary estimands of a hypothesis, never its primary one.
- Phases exchange data only as files in the run folder. A phase never edits another phase's output.
- The PI runs the phases. Form 1 is a fixed playbook. Form 2 (agent) keeps the same default order and may go back with a journaled reason: experiment → hypothesis (4 → 3), or a late data problem reopens `data` as a new child node (3/4 → 2).
- Run status: `running`, `completed`, `budget_exceeded`, `failed:<stage>`.

## 5. Search engine

One engine runs every search stage; a stage supplies only its goal, inputs and required outputs.

### 5.1 Node

- One attempt at the stage goal, built by one Analyst session (§6), which ends by submitting one self-contained script.
- The harness re-runs the submitted script from scratch in the sandbox. Only that run's results file, figures and log count.
- **Results file** `results.json`: named results `{name: {value, ci?, n?, note?}}`, names matching `[A-Za-z][A-Za-z0-9_]*`. A stage declares the names it requires (e.g. `rows_before`, `rows_after` in `data`); a missing one fails the code checks. Rendering, audits, specification curves and Verify read only this file.
- Metadata: `id`, `parent`, `stage`, `kind` (`draft`, `debug`, `improve`, `variant`, `adversarial`), `status` (`ok`, `buggy`), `score`, `debug_depth`, `reason` (one line).

### 5.2 Step policy

Each step starts one Analyst with a task chosen by:

1. fewer than `num_drafts` drafts → **draft**; the Analyst sees summaries of earlier drafts and must take a different approach;
2. else with probability `debug_prob` → **debug** a `buggy` leaf with `debug_depth < max_debug_depth`;
3. else → **improve** the best `ok` node.

Defaults: `num_drafts = 3`, `debug_prob = 0.5`, `max_debug_depth = 3` [1]. A stage ends at its step budget, when an `ok` node meets the goal, or after `patience` steps without a better score.

### 5.3 Node evaluation

1. **Code checks.** Non-zero exit, timeout, missing required output, invalid results file or out-of-range declared value → `buggy`, no model call.
2. **Judge.** A separate session reads projected code, results and figures, writes an analysis, and returns the typed answers of §8. It scores validity, completeness and fidelity, never effect size, sign or significance [24]. Experiment input masks source literals, including signed numbers, except validated outcome/exposure column names projected to role aliases. A code-owned reference supplies closed method vocabulary and specification identity, never raw hypothesis prose or expected direction. Free-form logs/notes/context and result values/intervals are withheld. Only code-generated sample-count diagnostics are attached; unblinded result figures are publication artifacts. Non-experiment stages attach validated PNGs normally. `figure_issues` records presentation reasons, including on schema correction.
3. **Selection.** Highest-scoring `ok` node; ties go to the earlier node. The best node seeds the next stage. Every `ok` node's estimate is still reported (§5.5), so selection cannot hide the spread of attempts.

Each check has a test that it fires on a bad fixture and stays silent on a good one [37].

### 5.4 Stages

| Stage        | Phase       | Goal                                                                                  | Seeds from             | Required outputs                      |
| ------------ | ----------- | ------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------- |
| `data`       | Data        | Clean, validate, derive variables; log every change with rows affected                | raw data, framing      | clean dataset, change log, row counts |
| `explore`    | Exploration | Distributions, relations, group differences relevant to the questions; flag surprises | clean data             | observations with figures             |
| `baseline`   | Experiment  | Simple, transparent model or test for the hypothesis                                  | clean data, hypothesis | key estimate with interval, figure    |
| `main`       | Experiment  | Planned analysis and the follow-ups results call for                                  | best `baseline`        | estimates with intervals, figures     |
| `robustness` | Experiment  | Multiverse and adversarial checks (§5.5)                                              | best `main`            | main estimate under every variant     |

Experiment stages are separate; default step budgets are baseline 3, main 6, robustness 6. `search.stage_steps` overrides individual stages. Scheduled robustness attempts run before optional repairs and do not stop on goal/plateau; repairs retain specification identity and consume the same budget.

### 5.5 Robustness and stability

- **Variants** [21, 22], each re-estimating the main effect: data choices (exclusions, outlier rules, missing-value handling, codings); model choices (covariates, functional form, estimator); resampling (bootstrap, subgroups).
- **Adversarial checks**, at least one [7, 17]: placebo outcome, negative-control exposure, permutation of the key variable, or a confounding sensitivity bound such as the E-value [27].
- **Specification curve** of sorted estimates with intervals across variants and across every `ok` node of the experiment stages [23].
- **Stability label**, computed: `stable` iff the estimate keeps its sign with an interval excluding zero in ≥ `stability_share` (default 0.8) of variants and no adversarial check fails; else `fragile`.

The current executable adversary is one seeded exposure permutation using the same contrast/estimator; its `placebo_estimate` interval must contain zero (endpoints included). This is a diagnostic, not a calibrated permutation test. Require at least `min_variants=3` successful ordinary specifications. Failed/missing planned variants stay in the denominator; failed/missing adversaries force `fragile`. Ordinary intervals touching zero do not support stability. Main sign, not expected hypothesis direction, is the reference; no extra main-significance gate is imposed. All successful baseline/main/robustness attempts, including repairs and placebo estimates, remain in the table/curve. A repaired specification's representative is its highest-scoring successful node, earliest on ties.

### 5.6 Analysis checklist

Carried in the Analyst and Critic prompts [24, 26, 28]; enforcement is by checks and labels, not the prompt:

- justify a processing choice by validity, never by the relation it produces;
- flag derived variables that use the outcome;
- report every rule that drops rows;
- prefer effect sizes with intervals over p-values alone;
- keep association distinct from causation in observational designs.

## 6. Roles

A role is a prompt, a tool set and a model route. A role gets its own session only when it needs different tools or an independent context.

| Role         | Responsibility                                                                                      | Tools                                                         | Session reason                 |
| ------------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------ |
| **PI**       | Runs phases; in agent form, chooses next work, goes back, asks the researcher                       | playbook; later stage, hypothesis, memory, ask-researcher     | Only writer of run-level files |
| **Theorist** | Framing with self-reflection; hypotheses with planned tests from exploration                        | read artifact, literature search                              | No code tools                  |
| **Analyst**  | Builds one node                                                                                     | inspect data, run snippet, view figure, read artifact, submit | Only role that runs code       |
| **Judge**    | Scores one node with typed answers                                                                  | none                                                          | Independent of the author      |
| **Critic**   | Tries to break hypotheses and main results; proposes adversarial checks; rubric review of the draft | read artifact, view figure                                    | Independent of the author      |
| **Writer**   | Writes and revises the paper from artifacts, checks and critique                                    | read artifact, view figure, literature search                 | Long-form output, own template |

Topology constraints:

- one PI per run; role sessions run one at a time and communicate only through artifacts;
- at most two hand-offs per node (Analyst → Judge) [37];
- no role writes another role's outputs;
- parallel Analysts, hypothesis tournaments and hierarchical planners are evaluation challengers, not defaults (§14).

Researcher input (hypothesis choice, framing edits, notes) is recorded with `supplied_by: researcher` and shown in the paper as `researcher_steered` [6, 8].

## 7. Harness

Makes agent work recorded, bounded and recoverable. Holds no research logic.

### 7.1 Agent loop

- A session is a tool-use loop on the configured model route.
- A tool is a name, a JSON schema and a handler returning text or an image.
- A session ends on its terminal tool (`submit`, `finish`, `answer`) or its turn limit.
- Transient provider errors (throttling, timeouts, 5xx) are retried with backoff inside the model client and journaled; they are never research steps.

### 7.2 Tools

| Tool                | Contract                                                          | Limits                                    |
| ------------------- | ----------------------------------------------------------------- | ----------------------------------------- |
| `inspect_data`      | Schema, head, summary, missing counts of a stage input            | Stage inputs only                         |
| `run_python`        | Runs scratch code in the node's scratch folder, returns output    | Sandbox of §7.4; recorded, never a result |
| `view_figure`       | Sends a figure to the model                                       | Run folder only                           |
| `read_artifact`     | Reads results, analyses, change logs, framing, hypotheses, memory | Run folder only; no raw rows              |
| `submit`            | Terminal; the script run as the node                              | Once per Analyst session                  |
| `search_literature` | Metadata and abstracts of prior work                              | Concepts only, never data values          |

Tool rules [33]: errors state the cause and a next step; long output is truncated with a hint to narrow it; paths are absolute; writes stay inside the calling node's folder.

### 7.3 Context assembly

Each session's context is built fresh from the run folder, never inherited from another session [32].

- **Just in time:** artifacts are listed by name and read through tools.
- **Working memory:** short entries citing node ids, persisted across sessions [5, 32].
- **Condensed hand-off:** an Analyst sees its parent through the Judge's analysis, not the parent's session.
- **Size limits per part:** logs keep the tail, files keep the head; long Analyst sessions are compacted, keeping decisions and open errors.
- **Untrusted content** is wrapped and marked; every system prompt states it is data, never instructions.
- **Prompt caching:** the stable prefix of a session (system prompt, tool list, task) is marked for the provider's prompt cache; cache reads and writes are journaled.

### 7.4 Sandbox

- Fresh subprocess per script; working directory is an exclusive execution folder; time limit from config. Scratch processes run outside the evidence tree, then their files are snapshotted into the node.
- Inputs arrive as absolute paths in environment variables; credentials are stripped from the environment.
- No container or network isolation in single-user local use; container isolation is required before shared use [5].
- A worker audit hook permits normal Python reads only in that execution folder, mounted input files and runtime/library resources; writes stay in execution and cannot change harness code/logs or inputs. Resolve symlinks; deny sibling/run-root reads and subprocess launch. This prevents accidental file access, not hostile native extensions.

### 7.5 Journal and run store

- **Journal:** append-only events for model calls/cost, tools/wire status, execution starts/completions, nodes/stages, artifact commits and phases. A truncated tail remains untouched; new events use a numbered segment. Interior corruption fails visibly.
- **Run store:** write-once files (§9); version-2 `run.json` holds initial metadata and a secret-free config snapshot. Later status lives in committed numbered state files, citing prior state and committed artifact paths. Resume restores cost from every recorded model call, uses saved config and policy RNG, preserves incomplete attempts and never resets budgets. Cost not journaled at process death cannot be recovered.
- **Release:** code, outputs, seeds and journal stay in the run folder, so a run ships its own trace [18].

### 7.6 Budgets and failures

| Budget   | Examples                                  | Effect                       |
| -------- | ----------------------------------------- | ---------------------------- |
| Resource | money, turns per session, steps per stage | Hard stop; shown as progress |
| Search   | drafts, debug depth                       | Shapes the step policy       |
| Error    | looks per result                          | Verify only (§11)            |

| Failure class | Example                                 | Handling                               |
| ------------- | --------------------------------------- | -------------------------------------- |
| Technical     | throttling, timeout, 5xx                | Retry with backoff; journaled          |
| Research      | script error, missing output, no submit | Node is `buggy`; informs the next step |
| Budget        | money cap reached                       | Clean stop; status `budget_exceeded`   |
| Terminal      | stage ends with no `ok` node            | Clean stop; status `failed:<stage>`    |

No failure path edits a recorded artifact. Resume restarts from the last completed node, using the run folder and journal as the progress record [34].

### 7.7 Progress

One terminal line per phase and per node, e.g. `[data] data-002 debug → ok score 7 · $0.41`; `--quiet` disables it.

## 8. Decision layer

Judge verdicts are typed answers; code reads the fields, prose goes to the node analysis.

| Question          | Asked by        | Type             |
| ----------------- | --------------- | ---------------- |
| `node_buggy`      | Judge           | bool             |
| `goal_met`        | Judge           | bool             |
| `node_score`      | Judge           | int 1–10         |
| `hypothesis_rank` | PI (agent form) | score per option |

- **Answerers:** the LLM Judge (default, reference) or a decision model returning typed choices, probabilities and scores with confidence [38]. Adding one changes no interface.
- **Modes per question:** `off` (Judge only); `shadow` (both answer, Judge used); `on` (decision model used above a confidence threshold, else Judge).
- **Shadow records:** both answers and their inputs are journaled; evaluation computes agreement, calibration and cost, and a question moves to `on` only if the decision model matches or beats the Judge.
- **Limits:** chooses among given options or scores given facts; never writes code or prose; never computes what code can; never overrides a code check or label.
- **Fallback:** provider unavailable or malformed answer → Judge's answer, reason journaled.

## 9. Data model

```text
runs/<run_id>/
  run.json                 immutable config/inputs/hashes, initial status, format_version
  journal*.jsonl           append-only event segments and authoritative commits
  state/<sequence>.json    committed status/cost snapshots with artifact references
  brief.md, data/          discovery raw.csv, holdout.csv, split.json, processed.parquet
  understand/attempt-*/    profile and committed framing
  hypotheses/attempt-*/   one primary estimand, refuting result, sources/attribution
  discover/robustness/     versioned validated schedule before executions
  discover/evidence/      versioned evidence manifest and numerical summary results.json
  tree/<stage>/<node_id>/  execution/, scratch/, judge_figures/, meta.json, analysis.md
  memory.md                working memory citing node ids
  critiques/               Critic assessments citing node ids
  report/attempt-*/        Writer replies, curve inputs/execution, paper.tex, report.json
    build-*/               immutable PDF/compiler snapshots from temporary scratch
```

| Content kind    | Examples                                                           | Changed by                                 |
| --------------- | ------------------------------------------------------------------ | ------------------------------------------ |
| Source artifact | data versions, code, results, figures, logs                        | Never; a new node or version               |
| Assessment      | Judge analyses, critiques, figure reviews, paper review, decisions | A new attributed assessment beside the old |
| Working memory  | memory entries                                                     | Appended by the PI, each citing artifacts  |

Every assessment and memory entry cites the artifacts it rests on.

## 10. Publication

1. **Collect** framing, change log, exploration figures, hypotheses, best nodes, specification curves, labels.
2. **Aggregate figures** in one plotting script over best nodes' saved outputs [1].
3. **Write** a fixed LaTeX template: Abstract; Introduction; Data and Methods with change table/hypothesis; Results with Exploratory, Main, Robustness subsections; Discussion with limitations; Conclusion [28]. Numbers appear only as named-result references. Code renders all successful experiment attempts and computed stability/reasons, plus a status list of failed/missing attempts. Every number is resolved from `results.json` with canonical node keys and selected-stage aliases. Reserve one of at most four figures for the specification curve, place every figure next to a generated textual reference, and render caption macros too.
4. **Render** named results from result files [6]; an unknown name renders `??` and warns.
5. **Check:** build errors fed back to the Writer for up to `latex_rounds` rounds [1]; vision check of each figure against its caption [1]; number audit of literals not from named results; consistency checks on reported relations (means with n, tests with statistics) [29, 30]; Critic rubric review [2] and one Writer revision.
6. **Claims file** beside the PDF: each claim with its named results, nodes and label [20].
7. **Claim language:** negative and inconclusive results reported with equal standing; observational designs described as association; `fragile` results described as fragile.
8. **Appendix** generated by code: experiment scripts only, attributed by stage/node; data code and the change table are not duplicated. Broader publication audits, reviews, claims files and figure aggregation remain target extensions, not part of the current local writer.
9. **Disclosure** that the paper was generated by an AI system.

LaTeX engine: first found of `tectonic`, `latexmk`, `pdflatex`; build in scratch then preserve each fresh build snapshot. Without an engine the run writes source; `popper pdf` resolves the committed report (or old `report/paper.tex`) and builds later. `popper resume` continues only version-2 runs; completed runs reuse the existing outcome without model calls.

## 11. Verify

- **Holdout:** at ingest, before profiling, `holdout_fraction` (default 0.2; 0 disables) of rows is set aside, grouped by an id column when given. These rows never reach a node or tool. The split ships before Verify because exposure cannot be undone: a run without a holdout can never be verified.
- **Verify a result:** lock the data and analysis scripts that produced it and a margin chosen before looking; run once on the holdout; compute `confirmed`, `not_confirmed` or `inconclusive`. A failed run is `inconclusive` and is not repeated.
- One look per result [25]; assumptions are stated [7]. Exposure and error budgets exist only in `verify/`.

## 12. Knowledge

- `search_literature` returns metadata and abstracts for the Theorist and Writer.
- Queries carry concepts, never data values.
- Prior work shapes directions and related work; it is never evidence for this run's results.
- Hypotheses record `replicates`, `extends` or `contradicts` against retrieved work, as coverage, never a novelty claim [3].
- Only retrieved records are cited.

## 13. Evaluation

`evals/` compares configurations at equal model and budget.

| Suite     | Contains                                                                     | Measures                                              |
| --------- | ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| Planted   | Synthetic data with known effects and planted data issues                    | Effect recovery, data-issue fix rate                  |
| Null      | Synthetic data with no effect                                                | Rate of findings written up; share labelled `fragile` |
| Reference | Public datasets with known findings; BLADE and DiscoveryBench tasks [15, 16] | Agreement with expert analyses                        |

- **Headline metrics:** false-finding rate on the null suite and share of paper numbers traced to named results.
- **Per-run metrics:** node failure rate, audit and consistency warnings, holdout gap (evaluation re-runs the reported script on `data/holdout.csv` after the run; the run never sees it), Critic rubric score, draft diversity, cost, wall time.
- **Comparisons:** agentic vs single-shot nodes (`max_turns = 1`); one vs three drafts; diverse vs free drafts; vision feedback on vs off; PI agent vs playbook; Critic on vs off; multiverse vs single robustness check; decision model vs Judge per question.
- A mechanism whose default is _measured_ (§14) is compared once the suite exists and before the next mechanism is added.
- **Adoption record:** each comparison ends in an entry in `evals/decisions.md` (change, result, default kept).
- **Contamination:** public-data suites also run on perturbed copies; a gap is reported as memorization.
- Evaluation never changes a run's results.

## 14. Design decisions

Each decision names its sources and the alternative it rejects. Decisions marked _measured_ stay open to the comparisons of §13.

| #   | Decision                                                                                     | Sources                 | Rejected alternative                                         | Status   |
| --- | -------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------ | -------- |
| D1  | Staged best-first search over code with draft/debug/improve                                  | [1, 2, 13]              | Linear pipeline with one attempt per step                    | fixed    |
| D2  | Node built by a tool-using agent that tests before submitting                                | [3, 14]                 | One generated program per node                               | measured |
| D3  | Data phase before exploration; analytic choices treated as measurable                        | [15, 16, 21]            | Question-first pipeline with fixed preprocessing             | fixed    |
| D4  | Hypotheses grounded in explored data, challenged by a Critic, chosen by the researcher or PI | [4, 7, 8, 9]            | Hypotheses from literature alone; tournament ranking         | measured |
| D5  | Diverse drafts                                                                               | [19]                    | Unconstrained drafts                                         | measured |
| D6  | Robustness as a multiverse with adversarial checks and a computed stability label            | [17, 21, 22, 23, 27]    | A single robustness check; model-judged robustness           | measured |
| D7  | Code checks before the Judge; typed Judge answers                                            | [31, 36, 37]            | Free-text verdicts parsed by code                            | fixed    |
| D8  | Numbers rendered from named results; audit, consistency checks, claims file                  | [6, 20, 29, 30]         | Model-written numbers with post-hoc review                   | fixed    |
| D9  | Computed labels; strict one-look Verify on held-back rows                                    | [7, 24, 25, 26]         | Model-assessed confidence; repeated holdout looks            | fixed    |
| D10 | One PI, sequential roles, ≤ 2 hand-offs per node                                             | [5, 10, 11, 12, 35, 37] | Parallel agents or hierarchical planners by default          | measured |
| D11 | Fresh, just-in-time context with working memory and condensed hand-offs                      | [5, 32]                 | Carrying full conversations between sessions                 | fixed    |
| D12 | Small consolidated tool set with actionable errors                                           | [33]                    | Many fine-grained tools                                      | fixed    |
| D13 | Journal and write-once run folder as the progress and release record                         | [18, 34]                | Database or mutable state                                    | fixed    |
| D14 | Pluggable decision model behind typed questions, `shadow` before `on`                        | [38]                    | Replacing the Judge outright                                 | measured |
| D15 | Evaluation suites with contamination checks decide every _measured_ default                  | [15, 16, 18]            | Adopting mechanisms because a reference system reports gains | fixed    |
| D16 | Judge blind to effect estimates; every `ok` node reported                                    | [3, 24]                 | Best-first selection on a score that sees the result         | fixed    |
| D17 | Hypothesis with one primary estimand and a stated refuting result                            | [7, 26]                 | Free-text hypotheses of any complexity                       | fixed    |
| D18 | Holdout split at ingest, before Verify exists                                                | [25]                    | Holdout created only when verification is requested          | fixed    |

## 15. References

**AI research systems**

1. Yamada, Y., et al. (2025). [The AI Scientist-v2: workshop-level automated scientific discovery via agentic tree search](https://arxiv.org/abs/2504.08066). arXiv. Code: [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2).
2. Lu, C., et al. (2024). [The AI Scientist: towards fully automated open-ended scientific discovery](https://arxiv.org/abs/2408.06292). arXiv.
3. Beel, J., et al. (2025). [Evaluating Sakana's AI Scientist](https://arxiv.org/abs/2502.14297). arXiv.
4. Gottweis, J., et al. (2025). [Towards an AI co-scientist](https://arxiv.org/abs/2502.18864). arXiv.
5. Mitchener, L., et al. (2025). [Kosmos: an AI scientist for autonomous discovery](https://arxiv.org/abs/2511.02824). arXiv. Engineering notes: [How we built Kosmos](https://advances.edisonscientific.com/research/how-we-built-kosmos/).
6. Ifargan, T., et al. (2024). [Autonomous LLM-driven research — from data to human-verifiable research papers (data-to-paper)](https://arxiv.org/abs/2404.17605). arXiv.
7. Huang, K., et al. (2025). [Automated hypothesis validation with agentic sequential falsifications (POPPER)](https://arxiv.org/abs/2502.09858). arXiv.
8. Schmidgall, S., et al. (2025). [Agent Laboratory: using LLM agents as research assistants](https://arxiv.org/abs/2501.04227). arXiv.
9. Ghareeb, A. E., et al. (2025). [Robin: a multi-agent system for automating scientific discovery](https://arxiv.org/abs/2505.13400). arXiv.
10. Tang, Q., et al. (2026). [FARS: a fully automated research system deployed at scale](https://arxiv.org/abs/2606.31651). arXiv.
11. Nam, J., et al. (2026). [ScientistTwo](https://arxiv.org/abs/2609.19644). arXiv.
12. Bianchi, F., et al. (2025). [Agents4Science: AI authors and reviewers](https://arxiv.org/abs/2511.15534). arXiv.

**Data-science agents and benchmarks**

13. Jiang, Z., et al. (2025). [AIDE: AI-driven exploration in the space of code](https://arxiv.org/abs/2502.13138). arXiv.
14. Hong, S., et al. (2024). [Data Interpreter: an LLM agent for data science](https://arxiv.org/abs/2402.18679). arXiv.
15. Gu, K., et al. (2024). [BLADE: benchmarking language model agents for data-driven science](https://arxiv.org/abs/2408.09667). _EMNLP Findings_.
16. Majumder, B. P., et al. (2025). [DiscoveryBench: towards data-driven discovery with large language models](https://proceedings.iclr.cc/paper_files/paper/2025/file/0d70af566e69f1dfb687791ecf955e28-Paper-Conference.pdf). _ICLR_.

**Critiques of AI scientists**

17. Fa, D., & Culjak, M. (2026). [Sound agentic science requires adversarial experiments](https://arxiv.org/abs/2604.22080). arXiv.
18. Ding, T., et al. (2026). [Autonomous research agents: a survey of AI scientists and the verification gap](https://arxiv.org/abs/2608.05179). arXiv.
19. Tang, Y., & Yang, Y. (2026). [AI research agents narrow scientific exploration](https://arxiv.org/abs/2605.27905). arXiv.
20. Yu, G., & Wang, X. (2026). [Knows: agent-native structured research representations](https://arxiv.org/abs/2604.17309). arXiv.

**Research methodology**

21. Silberzahn, R., et al. (2018). [Many analysts, one data set: making transparent how variations in analytic choices affect results](https://journals.sagepub.com/doi/10.1177/2515245917747646). _Advances in Methods and Practices in Psychological Science_.
22. Steegen, S., Tuerlinckx, F., Gelman, A., & Vanpaemel, W. (2016). [Increasing transparency through a multiverse analysis](https://journals.sagepub.com/doi/10.1177/1745691616658637). _Perspectives on Psychological Science_.
23. Simonsohn, U., Simmons, J. P., & Nelson, L. D. (2020). [Specification curve analysis](https://www.nature.com/articles/s41562-020-0912-z). _Nature Human Behaviour_.
24. Gelman, A., & Loken, E. (2013). _The garden of forking paths._ Columbia University working paper.
25. Dwork, C., et al. (2015). [The reusable holdout: preserving validity in adaptive data analysis](https://www.science.org/doi/10.1126/science.aaa9375). _Science_.
26. Mayo, D. G. (2018). _Statistical Inference as Severe Testing._ Cambridge University Press.
27. VanderWeele, T. J., & Ding, P. (2017). Sensitivity analysis in observational research: introducing the E-value. _Annals of Internal Medicine_.
28. von Elm, E., et al. (2007). The Strengthening the Reporting of Observational Studies in Epidemiology (STROBE) statement. _The Lancet_.
29. Brown, N. J. L., & Heathers, J. A. J. (2017). The GRIM test: a simple technique detects numerous anomalies in the reporting of results in psychology. _Social Psychological and Personality Science_.
30. Nuijten, M. B., et al. (2016). The prevalence of statistical reporting errors in psychology (1985–2013). _Behavior Research Methods_.

**Harness engineering**

31. Anthropic (2024). [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).
32. Anthropic (2025). [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
33. Anthropic (2025). [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents).
34. Anthropic (2025). [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents).
35. Anthropic (2025). [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system).
36. OpenAI (2026). [Harness engineering](https://openai.com/index/harness-engineering/).
37. Marmelab (2026). [The state of AI harness engineering 2026](https://marmelab.com/blog/2026/09/24/the-state-of-ai-harness-engineering-2026.html).

**Decision models**

38. TypeSafe. [Jev decision model](https://openrouter.ai/docs/guides/community/jev). OpenRouter documentation.

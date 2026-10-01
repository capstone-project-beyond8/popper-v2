# Popper Architecture

Target design of Popper, an AI scientist for quantitative tabular data. Specs and plans take their components, contracts, invariants and defaults from this document; [ROADMAP.md](ROADMAP.md) orders the build. A spec may refine a contract here but not contradict it. A change of contract changes this document first. Sources are numbered in §15; the design decisions behind each component are in §14.

![Popper architecture](images/architecture.svg)

## 1. Scope

- **Input:** a research context (a narrative brief with optional structured front matter: domain, objectives, variable meanings and roles, design, constraints; §4.1) and one tabular dataset. **Output:** a run folder with a LaTeX paper, a claims file, and every attempt, execution and decision that produced them.
- **In scope:** ideation with the researcher, data preparation, exploration, hypothesis generation, analysis by generated code, write-up, review, optional verification on held-back rows.
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
| Research context, researcher answers, dataset strings, outputs and retrieved text are untrusted data | Context assembly (§7.3) |
| No credentials in the run folder or script environments               | Sandbox and run store (§7.4, §7.5)                    |
| Holdout rows never reach a node or tool before the locked run         | Run store at ingest; Verify (§11)                     |
| The Judge never sees effect estimates when scoring                    | Judge input redaction (§5.3)                          |
| Descriptive statistics are computed by code; a model never reports them | Initial data analysis (§4.2)                        |
| A `proposed` research-context entry may make a check stricter, never looser | Research-context schema (§4.1)                 |
| With the confirm partition on, confirm rows never reach `explore` or the fitting of `data` rules, and explore rows never reach experiment stages | Run store at ingest (§11) |
| The dependency rules of §3 hold                                       | Import contract test (§3)                             |

## 3. Decomposition

| Subsystem       | Package                                                          | Owns                                                                                                             | Section    |
| --------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------- |
| Coordinator     | `coordinator/`                                                   | The playbook: phase order, transitions, run status                                                               | §4         |
| Research phases | `understand/`, `ground/`, `discover/`, `communicate/`, `verify/` | Stage goals, role prompts, phase outputs                                                                         | §4, §10–12 |
| Search engine   | `treesearch/`                                                    | Nodes, step policy, node evaluation, selection, the Analyst's tools                                              | §5         |
| Harness         | `harness/`                                                       | Model client, agent loop, tools mechanism, context, sandbox, journal, run store, budgets, config, decision layer, research-context schema, role-free descriptive statistics | §4.1, §4.2, §7, §8 |
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
| 1   | Ideation                 | `understand/`  | Research context + initial data analysis → cleaned research context reviewed by the researcher → problem statement, research questions, required variables, distinct directions; self-reflection rounds (§4.1) | cleaned research context, framing |
| 2   | Data                     | `ground/`      | Search stage `data` (§5.4)                                                                                                               | clean dataset, change log                        |
| 3   | Exploration & hypothesis | `discover/`    | Search stage `explore` (explore rows when the confirm partition is on); observations and research context → hypotheses in the contract below; code gate (§4.3); Critic challenge; selection by researcher or PI | hypotheses                                       |
| 4   | Experiment               | `discover/`    | Per chosen hypothesis (confirm rows when the partition is on): stages `baseline` → `main` → `robustness`                                 | best nodes, estimates, figures, stability labels |
| 5   | Publication              | `communicate/` | Pipeline of §10                                                                                                                          | paper, claims file, review                       |
| —   | Verify (optional)        | `verify/`      | Contract of §11                                                                                                                          | verification records                             |

- **Hypothesis contract** [7, 41]: one primary estimand (outcome, exposure, contrast, population, unit), expected direction, the smallest effect size of interest (`sesoi`, in outcome units [42]; from the research context or proposed in ideation, before exploration; a `sesoi` first stated after exploration is recorded as `post_exploration` and never sets a Verify margin), the result that would refute it stated against that magnitude, `rival_explanations` each with a typed check (§4.3), `adjustment_set`, planned test in the method vocabulary (§4.4), source nodes, `supplied_by`, and the computed `tested_on` (§11). A `mechanism` with `auxiliary_predictions` is optional; each auxiliary prediction is tested as a secondary estimand, never as a robustness variant. Interactions and moderators are secondary estimands of a hypothesis, never its primary one.
- Phases exchange data only as files in the run folder. A phase never edits another phase's output.
- The PI runs the phases. Form 1 is a fixed playbook. Form 2 (agent) keeps the same default order and may go back with a journaled reason: experiment → hypothesis (4 → 3), or a late data problem reopens `data` as a new child node (3/4 → 2).
- Run status: `running`, `awaiting_review`, `completed`, `budget_exceeded`, `failed:<stage>`.

### 4.1 Research context and ideation

**Research context** is the researcher's single input besides the dataset: `research.md`, a narrative brief in the Markdown body with optional structured front matter. It is the metadata that initial data analysis starts from [39, 40] and the configuration later phases read, as a research goal is parsed into a plan configuration in [4]. A body-only file is valid. The name is always written in full, never shortened to "context", which means context assembly (§7.3).

| Front-matter field | Holds                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| `domain`           | Background, known findings, terminology                                                                 |
| `objectives`       | Research questions in priority order, audience, the decision the results inform; `fixed` or `open` [6]  |
| `variables`        | Per column: meaning, unit, `type`, `role`, valid range or levels, relative measurement `order`          |
| `design`           | Unit of observation, sampling, collection period, observational or experimental, cluster column          |
| `assumptions`      | Known confounders and other causal assumptions                                                          |
| `constraints`      | Excluded or protected columns, ethical limits                                                           |
| `sesoi`            | Smallest effect size of interest per outcome, in outcome units [42]                                     |
| `hypotheses`       | Researcher hypotheses, recorded with `supplied_by: researcher`                                          |
| `notes`            | Guidance per phase (`data`, `explore`, `hypothesis`, `experiment`, `writing`) [8]                       |

- `type`: `continuous`, `binary`, `categorical`, `ordinal`, `count`, `id`, `time`, `text`; inferred from the column when not given.
- `role`: `outcome`, `exposure`, `covariate`, `id`, `cluster`, `time`, `post_outcome` (measured after or derived from an outcome), `protected`, `ignore`, `unknown`.
- Every entry (one variable, one assumption, one `sesoi`) carries a provenance `status`: `confirmed` (written or approved by the researcher), `computed` (inferred by code from the data: type, levels, observed range, cluster count; never meaning, role or order), `proposed` (written by an agent, with its `evidence`: initial-data-analysis names, a quoted passage of the body, or a retrieved work), or `unknown`. Researcher-written entries default to `confirmed`.
- Code checks, gates and labels use `confirmed` and `computed` entries. A `proposed` entry may make a check stricter, never looser: a proposed cluster column still triggers the cluster rule (§4.4) and a proposed `post_outcome` role still blocks an exposure, but a proposed `outcome` role never lets a hypothesis pass. Under `--auto`, where nothing is confirmed, the checks therefore still bind. Models see `proposed` entries marked as proposals. The paper lists `proposed` and `unknown` entries the analysis relied on as assumptions and limitations; nothing is guessed into `confirmed` [2].
- `notes` steer prompts only; they never change a check, a gate or a label.
- The harness validates the front matter at ingest: a named column missing from the dataset, or an invalid type, role or status, fails ingest with every mismatch listed. Body and front-matter strings are untrusted data (§7.3).

**Ideation** turns the research context into a cleaned research context and a framing. Its steps never see a relation between the outcome and an exposure, and never read holdout rows; they read the research context, initial data analysis and, later, retrieved work [40].

| Step         | By                                  | Does                                                                                                                                                                                 |
| ------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1a Ingest    | Code                                | Validate the research context, split holdout and confirm rows (§11), compute initial data analysis on discovery raw rows (§4.2), list the **gaps**: columns without a confirmed role, type or unit, missing measurement order, an undeclared cluster structure, a missing `sesoi`, values outside a declared range |
| 1b Understand | Theorist                           | Restate the request and the problem setting; propose meaning, unit, type, role and order for each gap with evidence; rank the open questions by their effect on the gate (§4.3)    |
| 1c Clarify   | Theorist and researcher             | Ask the open questions one at a time, each with a proposed answer and an "unknown" option; answers become `confirmed`                                                               |
| 1d Knowledge | Theorist with literature (§12)      | Propose domain background, known mechanisms and confounders, each `proposed` with a retrieved work as evidence                                                                       |
| 1e Review    | Researcher                          | The run writes the cleaned research context, prints it as a table (entry, value, status, evidence) and stops with status `awaiting_review`; the researcher edits or approves it, and `popper resume` commits it as a researcher-supplied attempt. `--auto` skips the stop and keeps proposals `proposed`; evaluation runs use it, and the planted suite scores both paths (§13) |
| 1f Framing   | Theorist, then code, then Theorist  | Questions mapped to objectives, directions with their origin, data concerns, unknowns; key variables are the roles of the cleaned research context, not a second list; code checks that each question has an outcome candidate whose role is not `post_outcome`, `protected` or `ignore`, that no question needs an excluded column, and that directions are distinct; one reflection round |

The cleaned research context is the single source for what the variables mean; the framing attempt holds only agent output (questions, directions, data concerns) and never restates a role. Later phases read it: `data` takes valid ranges, codings and excluded columns; `explore` and the hypothesis take objectives, directions, roles, confounders and `sesoi`; experiments take design and clusters (§4.4); the Writer takes domain, audience, objectives and the assumption list. Revising it after results (§6, PI agent form) writes a new attempt with a journaled reason, as a scientist refines a research goal in [4].

### 4.2 Initial data analysis

Descriptive statistics are computed by code, never by a model [39, 40]. One harness module computes the role-free groups and backs every describer: the ingest profile, the data summary the Judge reads and the Analyst's `inspect_data`. It runs twice, on discovery raw rows at ingest and on `processed.parquet` after `data`, each as a write-once artifact in the `results.json` schema so the renderer and audit read it unchanged. The harness computes numbers only. Groups that need roles are computed in `discover/` from the same primitives, and the rules that act on any group live in phase packages.

| Group                   | Needs roles | Contents                                                                                                        |
| ----------------------- | ----------- | --------------------------------------------------------------------------------------------------------------- |
| Structure               | No          | Rows, columns, types, duplicate rows and keys, constant columns, id uniqueness                                  |
| Data quality            | No          | Missing share per column, co-missing patterns, missing share by cluster, out-of-range values, inconsistent codings, heaping, outliers by a fixed rule |
| Univariate distribution | No          | Location, spread, shape (skewness, share of zeros, floor and ceiling share), quantiles; level counts, rare levels |
| Design structure        | No          | Cluster count and sizes, panel balance, time range and gaps                                                     |
| Sample flow             | No          | Rows at ingest, in the holdout, explore and confirm partitions, and after each `data` rule                      |
| Sample characteristics  | No          | Table 1: each column summarized over the analysed rows, overall, without tests                                  |
| Balance and overlap     | Exposure    | Binary or categorical exposure: standardized mean difference of covariates across levels [43]; continuous exposure: correlation of each covariate with it; exposure support within strata |
| Precision               | Exposure, outcome | Rows per exposure level or cell, events per variable for binary outcomes, minimum detectable effect        |

None of these groups relates the outcome to an exposure: initial data analysis does not touch the research question [40]. Relations involving the outcome are exploration, and so are associations among predictors until a rule reads them; the Analyst computes them in `explore`. The outcome ICC is not computed: with few clusters it is unstable, and the cluster rule reads cluster counts (§4.4). An outcome whose floor or ceiling share exceeds `bound_share` is **bounded**: the paper states the bound as a limitation (§10) and method fit reads it (§4.4). Sample tables and balance checks carry no significance tests [43]; assumption checks use descriptive measures with fixed thresholds, not normality or variance tests. The 0.1 default for `smd_threshold` is a convention, not a consensus [43].

### 4.3 Hypothesis quality

| Criterion                          | Enforced by                                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Refutable, with a stated magnitude | Schema: `refuting_result` against `sesoi`                                                                           |
| One specific primary estimand      | Schema (§4)                                                                                                         |
| Explains, not only associates      | Schema: optional `mechanism`, `auxiliary_predictions` tested as secondary estimands; Critic rubric                  |
| Faces its rivals [41]              | Schema: each rival explanation has a typed check, `adjustment` (a robustness variant of the same estimand), `negative_control` (an adversarial check) or `sensitivity` (a reported bound) (§5.5); Critic rubric |
| Testable with these data           | Gate; `underpowered` label (§4.2 precision)                                                                          |
| Independent of the confirming rows | Confirm partition when on (§11); `tested_on` printed either way                                                     |
| Relevant and informative           | Critic rubric against `objectives`; prior-work coverage (§12)                                                       |

**Gate**, run by code on every proposal; a failure returns its reasons to the Theorist like a schema error:

- outcome and exposure never have role `id`, `cluster`, `post_outcome`, `protected` or `ignore`, under any status; when their roles are `confirmed`, they are `outcome` and `exposure`;
- the exposure's `order` does not follow the outcome's, under any status;
- `adjustment_set` holds no outcome or `post_outcome` column and names every confirmed confounder, or a rival explanation states why not;
- the planned test and the robustness schedule follow the cluster rule (§4.4);
- a categorical exposure has at least `min_rows_per_level` rows in every compared level.

When precision gives a minimum detectable effect above a `sesoi` set before exploration, the hypothesis is labelled `underpowered`; the label is printed and the run continues.

### 4.4 Analysis methods

The method vocabulary is layered and closed. One module owns it and replaces any flat method list; the hypothesis schema, method fit, the gate and the Judge's method reference read it.

| Layer         | Values                                                                                                                                                                            |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Preprocessing | log transform, rank transform, winsorize, standardize, imputation                                                                                                                 |
| Estimator     | difference in means, OLS, logistic, Poisson, negative binomial, fixed effects, mixed effects, Mann–Whitney/Hodges–Lehmann, Kruskal–Wallis, chi-square, Fisher exact, Pearson, Spearman, Kendall, partial correlation, random forest, smooth (spline/GAM) |
| Inference     | analytic, bootstrap, permutation, robust SE, cluster-robust SE, wild cluster bootstrap                                                                                            |

Primary estimators by outcome and exposure type; correlation coefficients serve exploration and diagnostics, never a primary estimand:

| Outcome \ Exposure | Binary                                                        | Categorical (> 2 levels)                                 | Continuous                                             |
| ------------------ | ------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------ |
| Continuous         | Difference in means, OLS; Mann–Whitney as a variant           | OLS with planned contrasts; Kruskal–Wallis as a variant  | OLS contrast at two stated values; smooth as a variant |
| Binary             | Risk difference or ratio, logistic; Fisher when cells are small | Logistic                                               | Logistic with a marginal contrast                      |
| Count              | Poisson or negative binomial rate ratio                       | Poisson or negative binomial                             | Poisson or negative binomial                           |

- **Method fit**, computed from the table and the variable types: `ok`, `mismatch`, or `unchecked` for outcomes with no row (ordinal, bounded). It is printed in Data and Methods; whether a `mismatch` blocks the hypothesis is a measured decision (D22).
- **Bounded outcomes** keep the continuous row; linear estimates near the bound are attenuated, and the paper says so. A censored-outcome estimator joins the vocabulary only after the planted suite measures the need.
- **Clusters** (a hard rule): cluster-robust SE over-reject with few clusters, and the wild cluster bootstrap-t holds down to about five, less well when clusters are unbalanced [44]. With at least `min_clusters` (default 30) clusters, inference uses cluster-robust SE or mixed effects; from `min_wild_clusters` (default 5) up to that, the wild cluster bootstrap; below `min_wild_clusters`, cluster fixed effects, and the paper states that the result describes the observed clusters only; an exposure constant within clusters is then not estimable and fails the gate. The rule reads any cluster column that is `confirmed`, `computed` or `proposed`, and binds the planned test and every robustness variant.
- **Diagnostics** from §4.2 add required robustness variants and never change the primary method: skewness above `skew_threshold` in an unbounded outcome adds a log or rank variant; a count variance-to-mean ratio above `overdispersion_ratio` adds negative binomial; a level below `rare_level_share` adds a merged-level variant; a standardized mean difference above `smd_threshold` adds an adjusted variant.
- Thresholds live in config under `analysis`, including `bound_share` (default 0.1).

## 5. Search engine

One engine runs every search stage; a stage supplies only its goal, inputs and required outputs.

### 5.1 Node

- One attempt at the stage goal, built by one Analyst session (§6), which ends by submitting one self-contained script.
- The harness re-runs the submitted script from scratch in the sandbox. Only that run's results file, figures and log count.
- **Results file** `results.json`: named results `{name: {value, ci?, n?, note?}}`, names matching `[A-Za-z][A-Za-z0-9_]*`. A stage declares the names it requires (e.g. `rows_before`, `rows_after` in `data`); a missing one fails the code checks. Rendering, audits, specification curves and Verify read only this file.
- Metadata: `id`, `parent`, `stage`, `kind` (`draft`, `debug`, `improve`, `variant`, `adversarial`), `status` (`ok`, `buggy`), `score`, `debug_depth`, `reason` (one line).

### 5.2 Step policy

Each step starts one Analyst with a task chosen by:

1. fewer than `min(num_drafts, steps − 1)` drafts (at least one) → **draft**, so every stage keeps a step to debug or improve; the Analyst sees summaries of earlier drafts and must take a different approach;
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
| `explore`    | Exploration | Relations involving the outcome, group differences relevant to the questions; flag surprises | clean data (explore rows when the confirm partition is on), initial data analysis | observations with figures |
| `baseline`   | Experiment  | Simple, transparent model or test for the hypothesis                                  | clean data (confirm rows when the partition is on), hypothesis | key estimate with interval, figure |
| `main`       | Experiment  | Planned analysis and the follow-ups results call for                                  | best `baseline`        | estimates with intervals, figures     |
| `robustness` | Experiment  | Multiverse and adversarial checks (§5.5)                                              | best `main`            | main estimate under every variant     |

Experiment stages are separate; default step budgets are baseline 3, main 6, robustness 6. `search.stage_steps` overrides individual stages. Scheduled robustness attempts run before optional repairs and do not stop on goal/plateau; repairs retain specification identity and consume the same budget.

### 5.5 Robustness and stability

- **Variants** [21, 22], each re-estimating the main effect: data choices (exclusions, outlier rules, missing-value handling, codings); model choices (covariates, functional form, estimator); resampling (bootstrap, subgroups). Diagnostic-triggered variants (§4.4) and rival checks of type `adjustment` (§4.3) are required variants. Every variant re-estimates the same estimand; anything else stays out of the stability denominator.
- **Adversarial checks**, at least one [7, 17]: placebo outcome, negative-control exposure or outcome, or permutation of the key variable; rival checks of type `negative_control` are added here. Confounding sensitivity bounds such as the E-value [27], including rival checks of type `sensitivity`, are reported beside the label and do not set it.
- **Specification curve** of sorted estimates with intervals across variants and across every `ok` node of the experiment stages [23].
- **Stability label**, computed: `stable` iff the estimate keeps its sign with an interval excluding zero in ≥ `stability_share` (default 0.8) of variants and no adversarial check fails; else `fragile`. When a run tests k hypotheses, the intervals the label reads are at level 1 − α/k.

The current executable adversary is one seeded exposure permutation using the same contrast/estimator; its `placebo_estimate` interval must contain zero (endpoints included). This is a diagnostic, not a calibrated permutation test. Require at least `min_variants=3` successful ordinary specifications. Failed/missing planned variants stay in the denominator; failed/missing adversaries force `fragile`. Ordinary intervals touching zero do not support stability. Main sign, not expected hypothesis direction, is the reference; no extra main-significance gate is imposed. All successful baseline/main/robustness attempts, including repairs and placebo estimates, remain in the table/curve. A repaired specification's representative is its highest-scoring successful node, earliest on ties.

### 5.6 Analysis checklist

Carried in the Analyst and Critic prompts [24, 26, 28]; enforcement is by checks and labels, not the prompt:

- justify a processing choice by validity, never by the relation it produces;
- flag derived variables that use the outcome;
- report every rule that drops rows;
- prefer effect sizes with intervals over p-values alone;
- choose assumption handling from descriptive measures, not normality or variance tests;
- keep association distinct from causation in observational designs.

## 6. Roles

A role is a prompt, a tool set and a model route. A role gets its own session only when it needs different tools or an independent context.

| Role         | Responsibility                                                                                      | Tools                                                         | Session reason                 |
| ------------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------ |
| **PI**       | Runs phases; in agent form, chooses next work, goes back, asks the researcher                       | playbook; later stage, hypothesis, memory, ask-researcher     | Only writer of run-level files |
| **Theorist** | Ideation: understands the request, proposes variable meanings, asks the researcher, frames with self-reflection; hypotheses with mechanism, rivals and planned tests from the research context and exploration | read artifact, literature search, ask researcher (ideation) | No code tools                  |
| **Analyst**  | Builds one node                                                                                     | inspect data, run snippet, view figure, read artifact, submit | Only role that runs code       |
| **Judge**    | Scores one node with typed answers                                                                  | none                                                          | Independent of the author      |
| **Critic**   | Tries to break hypotheses and main results; scores hypotheses on the §4.3 rubric; proposes adversarial checks; rubric review of the draft | read artifact, view figure                                    | Independent of the author      |
| **Writer**   | Writes and revises the paper from artifacts, checks and critique                                    | read artifact, view figure, literature search                 | Long-form output, own template |

Topology constraints:

- one PI per run; role sessions run one at a time and communicate only through artifacts;
- at most two hand-offs per node (Analyst → Judge) [37];
- no role writes another role's outputs;
- parallel Analysts, hypothesis tournaments and hierarchical planners are evaluation challengers, not defaults (§14).

Researcher input (research-context answers and review, hypothesis choice, framing edits, notes) is recorded with `supplied_by: researcher` and shown in the paper as `researcher_steered` [6, 8].

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
| `ask_researcher`    | One question with a proposed answer and an "unknown" option; the answer is journaled | Theorist in ideation, PI agent; never under `--auto` |

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
  research.md              research context as given (validated)
  data/                    discovery raw.csv, holdout.csv, split.json (holdout rows; confirm rows when on),
                           processed.parquet, ida-raw.json, ida.json
  understand/attempt-*/    gaps, open questions and answers, cleaned research context (agent draft, then
                           researcher-reviewed attempt), committed framing
  hypotheses/attempt-*/   one primary estimand, typed rival checks, refuting result, gate result, method fit,
                           tested_on, sources/attribution
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

1. **Collect** cleaned research context, initial data analysis, framing, change log, exploration figures, hypotheses, best nodes, specification curves, labels.
2. **Aggregate figures** in one plotting script over best nodes' saved outputs [1].
3. **Write** a fixed LaTeX template: Abstract; Introduction; Data and Methods with sample flow, sample characteristics table (no significance tests), change table, the hypothesis with its rival explanations and their checks (and mechanism when stated), method fit, and one fixed sentence stating which rows tested it (`tested_on`); Results with Exploratory, Main, Robustness subsections; Discussion with limitations, including unconfirmed research-context assumptions and a bounded outcome; Conclusion [28]. Numbers appear only as named-result references. Code renders all successful experiment attempts and computed stability/reasons, plus a status list of failed/missing attempts. Every number is resolved from `results.json` with canonical node keys and selected-stage aliases. Reserve one of at most four figures for the specification curve, place every figure next to a generated textual reference, and render caption macros too.
4. **Render** named results from result files [6]; an unknown name renders `??` and warns.
5. **Check:** build errors fed back to the Writer for up to `latex_rounds` rounds [1]; vision check of each figure against its caption [1]; number audit of literals not from named results; consistency checks on reported relations (means with n, tests with statistics) [29, 30]; Critic rubric review [2] and one Writer revision.
6. **Claims file** beside the PDF: each claim with its named results, nodes and label [20].
7. **Claim language:** negative and inconclusive results reported with equal standing; observational designs described as association; `fragile` results described as fragile; `underpowered` hypotheses described as unable to detect the stated smallest effect.
8. **Appendix** generated by code: experiment scripts only, attributed by stage/node; data code and the change table are not duplicated. Broader publication audits, reviews, claims files and figure aggregation remain target extensions, not part of the current local writer.
9. **Disclosure** that the paper was generated by an AI system.

LaTeX engine: first found of `tectonic`, `latexmk`, `pdflatex`; build in scratch then preserve each fresh build snapshot. Without an engine the run writes source; `popper pdf` resolves the committed report (or old `report/paper.tex`) and builds later. `popper resume` continues only version-2 runs; completed runs reuse the existing outcome without model calls.

## 11. Verify

- **Holdout:** at ingest, before profiling, `holdout_fraction` (default 0.2; 0 disables) of rows is set aside, grouped by an id column when given. These rows never reach a node or tool. The split ships before Verify because exposure cannot be undone: a run without a holdout can never be verified.
- **Confirm partition:** after the holdout, `confirm_fraction` (default 0, off; the comparison of §13 decides the default) of discovery rows is marked confirm, grouped the same way, and recorded in `split.json`. When on, `data` fits its rules on explore rows and its committed script is replayed unchanged on confirm rows; `explore` reads only explore rows; experiment stages read only confirm rows. Initial data analysis (§4.2) uses all discovery rows. Each hypothesis records the computed `tested_on` (`all_discovery` or `confirm`), printed in Data and Methods; no new label is added, since every result outside Verify is already `exploratory`. Off, a weak effect keeps its power; on, about half the rows test it.
- **Verify a result:** lock the data and analysis scripts that produced it and a margin chosen before looking (the hypothesis `sesoi` when it was set before exploration); run once on the holdout; compute `confirmed`, `not_confirmed` or `inconclusive`. A failed run is `inconclusive` and is not repeated.
- One look per result [25]; assumptions are stated [7]. Exposure and error budgets exist only in `verify/`.

## 12. Knowledge

- `search_literature` returns metadata and abstracts for the Theorist and Writer; in ideation it supplies `proposed` research-context entries with the retrieved work as evidence (§4.1).
- Queries carry concepts, never data values.
- Prior work shapes directions and related work; it is never evidence for this run's results.
- Hypotheses record `replicates`, `extends` or `contradicts` against retrieved work, as coverage, never a novelty claim [3].
- Only retrieved records are cited.

## 13. Evaluation

`evals/` compares configurations at equal model and budget.

| Suite     | Contains                                                                     | Measures                                              |
| --------- | ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| Planted   | Synthetic data with known effects, planted data issues, a reference research context, an outcome-derived leak column, a few-cluster design and a bounded outcome | Effect recovery, data-issue fix rate, role-proposal accuracy, estimand recovery, method fit, cluster-rule adherence, leak pick rate |
| Null      | Synthetic data with no effect                                                | Rate of findings written up; share labelled `fragile` |
| Reference | Public datasets with known findings; BLADE and DiscoveryBench tasks [15, 16] | Agreement with expert analyses                        |

- **Headline metrics:** false-finding rate on the null suite and share of paper numbers traced to named results.
- **Per-run metrics:** node failure rate, audit and consistency warnings, holdout gap (evaluation re-runs the reported script on `data/holdout.csv` after the run; the run never sees it), Critic rubric score, draft diversity, cost, wall time.
- **Comparisons:** research-context body only vs with front matter; agent-cleaned research context with vs without researcher review; confirm partition on vs off; agentic vs single-shot nodes (`max_turns = 1`); one vs three drafts; diverse vs free drafts; vision feedback on vs off; PI agent vs playbook; Critic on vs off; multiverse vs single robustness check; decision model vs Judge per question.
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
| D4  | Hypotheses grounded in the research context and explored data, gated by code, challenged by a Critic, chosen by the researcher or PI | [4, 7, 8, 9, 41] | Hypotheses from literature alone; tournament ranking         | measured |
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
| D17 | Hypothesis with one primary estimand, typed rival checks and a refuting result against a magnitude set before exploration; optional mechanism with tested auxiliary predictions | [7, 26, 41, 42] | Free-text hypotheses of any complexity; rival checks mixed into the stability denominator | fixed    |
| D18 | Holdout split at ingest, before Verify exists                                                | [25]                    | Holdout created only when verification is requested          | fixed    |
| D19 | One research context (narrative body, optional front matter with per-entry provenance), cleaned in ideation and reviewed by the researcher before analysis; proposals only tighten checks | [4, 6, 8, 39, 40] | Free-text brief only; separate brief and study files; agent-inferred variable meanings used as facts; checks that only read confirmed entries and so do nothing under `--auto` | measured |
| D20 | Descriptive statistics computed by one code module behind every describer, before and after `data` | [39, 40]       | Model-computed descriptives; several describers               | fixed    |
| D21 | Optional explore and confirm partitions within discovery rows, off by default until measured; `tested_on` always printed | [24, 25] | Testing on the suggesting rows without saying so; a partition that `data` still fits on | measured |
| D22 | Layered closed method vocabulary; computed method fit (a gate only if measured); hard few-cluster rule; diagnostic-triggered variants | [40, 43, 44] | Flat method list; normality tests choosing the method; cluster-robust SE with few clusters | measured |

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

**Initial data analysis and hypothesis design**

39. Huebner, M., le Cessie, S., Schmidt, C. O., & Vach, W. (2018). [A contemporary conceptual framework for initial data analysis](https://doi.org/10.1353/obs.2018.0014). _Observational Studies_.
40. Baillie, M., le Cessie, S., Schmidt, C. O., Lusa, L., & Huebner, M. (2022). [Ten simple rules for initial data analysis](https://doi.org/10.1371/journal.pcbi.1009819). _PLoS Computational Biology_.
41. Platt, J. R. (1964). [Strong inference](https://doi.org/10.1126/science.146.3642.347). _Science_.
42. Lakens, D., Scheel, A. M., & Isager, P. M. (2018). [Equivalence testing for psychological research: a tutorial](https://doi.org/10.1177/2515245918770963). _Advances in Methods and Practices in Psychological Science_.
43. Austin, P. C. (2009). [Balance diagnostics for comparing the distribution of baseline covariates between treatment groups in propensity-score matched samples](https://doi.org/10.1002/sim.3697). _Statistics in Medicine_.
44. Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). [Bootstrap-based improvements for inference with clustered errors](https://doi.org/10.1162/rest.90.3.414). _Review of Economics and Statistics_.

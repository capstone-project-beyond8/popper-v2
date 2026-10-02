# Popper Architecture

Target design of Popper, an AI scientist for quantitative tabular data. Specs and plans take their components, contracts, invariants and defaults from this document; [ROADMAP.md](ROADMAP.md) orders the build. A spec may refine a contract here but not contradict it. A change of contract changes this document first. Sources are numbered in §15; the design decisions behind each component are in §14.

![Popper architecture](images/architecture.svg)

## 1. Scope

- **Input:** a research context (a narrative brief with optional structured front matter: domain, objectives, variable meanings and roles, design, constraints; §4.1) and one tabular dataset. **Output:** a run folder with a LaTeX paper, a claims file, and every attempt, execution and decision that produced them.
- **In scope:** understanding the research problem with the researcher, grounding it in the data (preparation and assessment), exploration, hypothesis generation, analysis by generated code, write-up, review, optional verification on held-back rows.
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
4. **Agents drive a phase; trees serve where attempts must be compared.** Phase order is code. Inside Understand and Ground one agent session decides its own steps; in Discover an agent chooses moves over a research graph, and tree search runs inside the moves that compare attempts (§4.6) [31].
5. **Ground truth from execution.** A result is what a script produced when the harness re-ran it from scratch [31].
6. **Labels, not locks.** Everything outside Verify is `exploratory`. Labels are computed by code and no model can raise them.
7. **Numbers come from artifacts.** Paper numbers are rendered from result files, never typed by a model [6].
8. **Try to break it.** Every main result meets robustness variants and at least one adversarial check [7, 17].
9. **Executable rules over prose rules.** A rule that matters is a check, a label or a renderer [36, 37].
10. **Measured restriction.** A new gate, reviewer or topology change needs an observed failure and an evaluation comparison [37].
11. **Append, never rewrite.** Run files are written once.
12. **One owner per concept.** Each concept has one module and one section here.
13. **The harness records, re-runs and labels; it does not steer.** A rule without an observed failure is a computed warning printed in the paper, not a gate (principle 10 applied to existing rules).

Agents get scientific freedom; the harness keeps integrity hard where it truly matters.

### 2.1 Invariants

Hold in every configuration; each is enforced by code and covered by a test.

| Invariant                                                             | Enforced by                                           |
| --------------------------------------------------------------------- | ----------------------------------------------------- |
| Every model call, tool call, execution and decision is journaled      | Harness (§7.5)                                        |
| Run files are write-once; a fix is a new node, attempt or assessment  | Run store (§9)                                        |
| A result is what the harness produced by re-running the submitted script from scratch | Search engine and Ground submit (§4.3, §5.1) |
| `exploratory`, `stable`/`fragile`, prediction verdicts, `confirmed` are computed | Label functions; the template prints them (§4.6, §5.5, §11) |
| Research-graph nodes are append-only and cite their source nodes and artifacts | Discover graph store (§4.6) |
| Paper numbers resolve to named results; unknown names are flagged     | Renderer and audit (§10)                              |
| Research context, researcher answers, dataset strings, outputs and retrieved text are untrusted data | Context assembly (§7.3) |
| No credentials in the run folder or script environments               | Sandbox and run store (§7.4, §7.5)                    |
| Holdout rows never reach a node, session or tool before the locked run | Run store at ingest; Verify (§11)                    |
| The Theorist never sees a relation between columns or holdout rows    | Understand inputs (§4.1)                              |
| Agents never set the status `confirmed`; only researcher input does   | Research-context schema (§4.1)                        |
| The Judge never sees effect estimates when scoring                    | Judge input redaction (§5.3)                          |
| Descriptive statistics are computed by code; a model never reports them | Initial data analysis (§4.2)                        |
| The dependency rules of §3 hold                                       | Import contract test (§3)                             |

**Computed warnings** (code computes them, the paper prints them, nothing blocks): outcome or exposure role and type conflicts, an exposure measured after the outcome, an excluded or protected column in use, few clusters for the planned inference, Ground readiness facts, and every `proposed` or `unknown` entry a result relies on (§4.4, §4.5, §10).

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
| 1   | Understand               | `understand/`  | Theorist session: research context + initial data analysis → Research Frame (cleaned research context with concepts, framing) steered by researcher signals (§4.1) | Research Frame |
| 2   | Ground                   | `ground/`      | Data Steward session: understand, repair, interrogate and assess the data against the frame; frame concerns return to 1 (§4.3) | prepared data, change log, operationalization, concerns, readiness |
| 3   | Exploration & hypothesis | `discover/`    | Search stage `explore` (explore rows when the confirm partition is on); observations, Research Frame and foundation → hypotheses in the contract below; computed warnings (§4.4); Critic challenge; selection by researcher or PI. Target: the Discover agent runs 3 and 4 as moves over the research graph (§4.6) | hypotheses                                       |
| 4   | Experiment               | `discover/`    | Per chosen hypothesis (confirm rows when the partition is on): pre-test description, then stages `baseline` → `main` → `robustness`, then a computed verdict per prediction (§4.6) | best nodes, estimates, figures, stability labels, verdicts |
| 5   | Publication              | `communicate/` | Pipeline of §10                                                                                                                          | paper, claims file, review                       |
| —   | Verify (optional)        | `verify/`      | Contract of §11                                                                                                                          | verification records                             |

- **Hypothesis contract** [7, 41]: one primary estimand (outcome, exposure, contrast, population, unit), expected direction, the result that would refute it, rival explanations, planned test, source nodes and `supplied_by`. Target (§4.6): an `origin` with the graph nodes it derives from, and the expected direction and refuting result stated as structured predictions whose verdict code computes. Measured additions (§14 D17): a smallest effect size of interest (`sesoi`, in outcome units [42], recorded `post_exploration` when first stated after exploration), typed rival checks (§4.4), an `adjustment_set`, a planned test in the layered vocabulary (§4.5) and the computed `tested_on` (§11). A `mechanism` with `auxiliary_predictions` is optional; each auxiliary prediction is tested as a secondary estimand, never as a robustness variant. Interactions and moderators are secondary estimands of a hypothesis, never its primary one.
- Phases exchange data only as files in the run folder. A phase never edits another phase's output.
- The PI runs the phases. Form 1 is a fixed playbook; it already goes back once from Ground to Understand when the data cannot represent the frame (2 → 1, bounded by `max_reframes`). Form 2 (agent) keeps the same default order and may also go back with a journaled reason: experiment → hypothesis (4 → 3), or a late data problem opens a new Ground attempt (3/4 → 2).
- Run status: `running`, `awaiting_review`, `completed`, `budget_exceeded`, `failed:<stage>`.

### 4.1 Research context and Understand

**Research context** is the researcher's single input besides the dataset: `research.md`, a narrative brief in the Markdown body with optional structured front matter. It is the metadata that initial data analysis starts from [39, 40] and the configuration later phases read, as a research goal is parsed into a plan configuration in [4]. A body-only file is valid. The name is always written in full, never shortened to "context", which means context assembly (§7.3).

| Front-matter field | Holds                                                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| `domain`           | Background, known findings, terminology                                                                 |
| `objectives`       | Research questions in priority order, audience, the decision the results inform [6]                     |
| `variables`        | Per column: meaning, unit, `type`, `role`, valid range or levels, relative measurement `order`          |
| `design`           | Unit of observation, sampling, collection period, observational or experimental, cluster, id and time columns |
| `assumptions`      | Known confounders and other causal assumptions                                                          |
| `constraints`      | Excluded or protected columns, ethical limits                                                           |
| `concepts`         | Research concepts: id, name, definition; never a column (the mapping to columns belongs to Ground)      |
| `notes`            | Guidance per phase (`understand`, `ground`, `explore`, `hypothesis`, `experiment`, `writing`) [8]       |

- `type`: `continuous`, `binary`, `categorical`, `ordinal`, `count`, `id`, `time`, `text`.
- `role`: `outcome`, `exposure`, `covariate`, `id`, `cluster`, `time`, `post_outcome` (measured after or derived from an outcome), `protected`, `ignore`, `unknown`.
- Every entry carries a provenance `status`: `confirmed` (written or approved by the researcher), `proposed` (written by an agent, with its `evidence`: an initial-data-analysis result name or an exact quote of the body), or `unknown`. A bare researcher value is `confirmed`; agents can never set `confirmed`.
- Models see `proposed` entries marked as proposals. Checks never loosen on a proposal: only a `confirmed` role can block a submission (§4.3). The paper lists every `proposed` and `unknown` entry a result relied on [2].
- `notes` steer prompts only; they never change a check, a warning or a label.
- The harness validates the front matter at ingest: a named column missing from the dataset (exact match), an unknown key, or an invalid type, role or status fails ingest with every mismatch listed, before any model call. Body and front-matter strings are untrusted data (§7.3).

**Understand** turns the research context into a **Research Frame**: shared research meaning the researcher can recognize and correct. It is one Theorist session (§6) that sees the research context and the role-free initial data analysis of discovery rows, and never a relation between columns or holdout rows [40].

- **Explore, critique, synthesize.** The agent chooses its own order and may repeat: restate and widen the problem, sharpen questions, find ambiguities, implicit assumptions and competing explanations, propose meaning, unit, type, role and order for undeclared attributes with evidence; critique its own framing (what is missing, alternative framings, the weakest assumption); then submit.
- **`ask_researcher`** asks one question with a proposed answer and an `unknown` option; an answer becomes `confirmed`. Under `--auto` or without an interactive researcher the tool says so and the item stays `proposed` or `unknown`.
- **`submit_frame`** carries a research-context patch (`proposed`/`unknown` entries and concepts) and a framing: title, problem, questions (id, objective served, outcome candidate), scope, important unknowns, and directions (id, origin, competing explanations). Code checks schema, columns, ids and evidence, refuses any change to a `confirmed` entry, and returns failures to the agent to fix (§7.1). Framing never restates a role or an assumption.
- **Review.** The run writes `review.yaml` and stops with status `awaiting_review`. Items are keyed by stable ids (`variables.<column>.<attribute>`, `assumptions.<id>`, `concepts.<id>`, `questions.<id>`, `directions.<id>`). The researcher marks each `approve`, `edit` (with a value), `reject` or `unknown`, with optional notes; `popper resume` applies them in code (approve and edit confirm; reject records the value so it cannot be proposed again). Edits, rejections or notes start one short Theorist revision session; there is no second review. `--auto` skips the stop and keeps proposals `proposed`; evaluation runs use it, and the planted suite scores both paths (§13).
- **Computed framing warnings:** a question whose outcome candidate has role `id`, `cluster`, `post_outcome`, `protected` or `ignore`, a question needing an excluded column, duplicate directions.

The reviewed research context is the single source for what variables and concepts mean; the framing holds only agent output. Later phases read it: Ground takes concepts, valid ranges, codings and excluded columns; `explore` and the hypothesis take objectives, directions, roles, confounders and the foundation (§4.3); experiments take design and clusters (§4.5); the Writer takes domain, audience, objectives and the assumption list. Revising it after Ground or after results writes a new attempt with a journaled reason, as a scientist refines a research goal in [4].

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

The groups that need roles also run per hypothesis, restricted to its estimand and population, as the pre-test description (§4.6). None of these groups relates the outcome to an exposure: initial data analysis does not touch the research question [40]. Relations involving the outcome are exploration, and so are associations among predictors until a rule reads them; the Analyst computes them in `explore`. The outcome ICC is not computed: with few clusters it is unstable, and the cluster rule reads cluster counts (§4.5). An outcome whose floor or ceiling share exceeds `bound_share` is **bounded**: the paper states the bound as a limitation (§10) and method fit reads it (§4.5). Sample tables and balance checks carry no significance tests [43]; assumption checks use descriptive measures with fixed thresholds, not normality or variance tests. The 0.1 default for `smd_threshold` is a convention, not a consensus [43].

### 4.3 Ground

**Ground** connects the Research Frame to what the data actually observe and produces an **empirical foundation**: what the data measure, how far they can be trusted, how each concept is represented, what is missing, and whether discovery can start. It is one Data Steward session (§6) on discovery raw rows; there is no tree and no Judge.

- **Responsibilities**, in the order the agent chooses: understand (semantics, observation unit, structure, provenance, which columns or proxies measure each concept), repair (cleaning, restructuring, transformation, derived variables), interrogate (anomalies, distributions, missingness by group, figures), assess (what the data cannot support). Enrichment from other sources is out of scope (§1).
- **`submit_ground`** carries a script and two judgments. The harness re-runs the script from scratch; only that run's `processed.parquet`, `changes.json` and `results.json` count. The judgments are an **operationalization** (concept → columns, proxy strength `direct`, `proxy`, `weak` or `none`, rationale) and **concerns** (`frame`: unmeasured concept, weak proxy, unit mismatch, missing variable, scope conflict; `data`: quality, sample, structure, other), each with evidence that resolves to a result, a change or a descriptive key.
- **Code checks** return failures to the agent to fix: row counts match, every change names a counted result and a nonempty validity reason, at least one row remains, every outcome with a `confirmed` role remains, every concept has an operationalization item, named columns and evidence exist. A `proposed` role never blocks.
- **After acceptance** code writes initial data analysis on the prepared data and **readiness facts**: each outcome and exposure exists and varies, its missing share, cluster count, floor and ceiling share. Readiness is printed, never blocking.
- **Operationalization is a proposal.** It stays `proposed`; Discover reads it as such, and the paper prints it as proposed by the data agent.
- **Frame concerns go back.** Ground never edits the research context. A `frame` concern opens a Theorist revision with the concerns as input, a review stop, and a new Ground attempt from raw rows, at most `max_reframes` times (default 1); what remains goes to Limitations.
- **Forbidden to use, not forbidden to see.** The Steward needs the outcome to prepare data, so code cannot stop it from seeing an outcome–exposure relation. No preparation decision may be justified by the relation it produces [24]: the prompt forbids computing such relations, every change states a validity reason, every snippet is journaled, and the paper discloses that preparation had raw-data access. Scratch runs on a copy with the outcome shuffled across rows are an evaluation challenger (§13).

### 4.4 Hypothesis quality

| Criterion                          | Enforced by                                                                                                         |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Refutable                          | Schema: `refuting_result`; target: structured predictions with a computed verdict (§4.6); stated against `sesoi` once that addition is measured (D17) |
| One specific primary estimand      | Schema (§4)                                                                                                         |
| Explains, not only associates      | Schema: optional `mechanism`, `auxiliary_predictions` tested as secondary estimands; Critic rubric                  |
| Faces its rivals [41]              | Schema: rival explanations; target: each with a typed check, `adjustment` (a robustness variant of the same estimand), `negative_control` (an adversarial check) or `sensitivity` (a reported bound) (§5.5); Critic rubric |
| Testable with these data           | Computed warnings; pre-test description (§4.6); `underpowered` label (§4.2 precision)                                           |
| Origin stated                      | Target: `origin` and `derived_from` (§4.6); `suggested_by_test_data` computed                                       |
| Independent of the confirming rows | Confirm partition when on (§11); `tested_on` printed either way                                                     |
| Relevant and informative           | Critic rubric against `objectives`; prior-work coverage (§12)                                                       |

**Computed warnings** on every hypothesis, stored beside it and printed in the paper, never blocking:

- outcome or exposure with role `id`, `cluster`, `post_outcome`, `protected` or `ignore`, or type `id`, under any status;
- an exposure whose `order` follows the outcome's;
- an excluded or protected column in use;
- a cluster column with fewer clusters than the inference needs (§4.5);
- an outcome or exposure mapped only by `weak` or `none` operationalization items (§4.3);
- every `proposed` or `unknown` entry the hypothesis relies on.

A **code gate** on roles, order, the adjustment set, clusters and level sizes is a target item: it becomes a gate only when the planted suite shows the warning missed failures that changed conclusions (§13, D4). When precision gives a minimum detectable effect above a `sesoi` set before exploration, the hypothesis is labelled `underpowered`; the label is printed and the run continues.

### 4.5 Analysis methods

The method vocabulary is layered. One module owns it and replaces any flat method list; it classifies plans rather than limiting what an agent may do; the hypothesis schema, method fit, the warnings and the Judge's method reference read it.

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
- **Clusters** (a computed warning now; a hard rule once measured, D22): cluster-robust SE over-reject with few clusters, and the wild cluster bootstrap-t holds down to about five, less well when clusters are unbalanced [44]. With at least `min_clusters` (default 30) clusters, inference uses cluster-robust SE or mixed effects; from `min_wild_clusters` (default 5) up to that, the wild cluster bootstrap; below `min_wild_clusters`, cluster fixed effects, and the paper states that the result describes the observed clusters only; an exposure constant within clusters is then not estimable and fails the gate. The rule reads any cluster column that is `confirmed` or `proposed`; until it is measured, a plan that departs from it is printed as a limitation of inference.
- **Diagnostics** from §4.2 add required robustness variants and never change the primary method: skewness above `skew_threshold` in an unbounded outcome adds a log or rank variant; a count variance-to-mean ratio above `overdispersion_ratio` adds negative binomial; a level below `rare_level_share` adds a merged-level variant; a standardized mean difference above `smd_threshold` adds an adjusted variant.
- Thresholds live in config under `analysis`, including `bound_share` (default 0.1).

### 4.6 Discover

**Discover** turns the open questions of the Research Frame and the foundation into evidence, and lets evidence open the next questions. A **Discover agent** chooses one move at a time over a shared, append-only **research graph**; each move adds nodes that resolve to executed artifacts. The graph is the global scientific state; a tree (§5) is the local mechanism inside a move that compares attempts. The agent coordinates and never writes scientific content itself: roles write nodes, code computes verdicts. The phase-3/4 playbook of §4 is the fixed form of the same moves.

```text
Research Frame + foundation ──seed──► RESEARCH GRAPH ◄── every move appends nodes
                                            │ view built by code (open questions, latest results, budget)
                                            ▼
                                     Discover agent ── one move + reason (journaled)
         ┌─────────────┬───────────────┬─────┴──────────┬──────────────┐
      explore      hypothesize        test           interpret       finish
     (tree)        (Theorist)   (pre-test → tree      (Theorist;     (candidate
                                 → verdict)            Critic later)   claims)
```

**Graph.** Files under `discover/graph/`, written once (§9). Every node has `id`, `kind`, `derived_from` (node ids), `branch` (a lineage label), `artifact` (the tree node, `results.json` or attempt it rests on), `by` (role) and `reason`.

| Node kind     | Written by           | Holds                                                                                         |
| ------------- | -------------------- | --------------------------------------------------------------------------------------------- |
| `question`    | Code, at seeding     | Frame questions, directions and unknowns, and foundation concerns and weak operationalizations, keeping their stable ids |
| `observation` | `explore`            | Named results and figures of the best `explore` node for one focus question                    |
| `hypothesis`  | `hypothesize`        | A hypothesis in the contract of §4 with `origin` and predictions; candidates not pursued stay as nodes |
| `result`      | `test`               | Pre-test description, test specification, evidence manifest, stability label and verdicts     |
| `assessment`  | `interpret`, Critic  | What a result changes: questions closed, questions opened, rivals raised; an attributed opinion, never a label |

A question is closed by an `assessment` that cites it, never by editing it. Dead ends and null results stay in the graph and in the paper.

**Moves.** The agent's tools; each returns the new node ids, and each choice is journaled with its target node and reason.

| Move                    | Does                                                                                                                      |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `explore(question)`     | Runs stage `explore` with the question as focus                                                                           |
| `hypothesize(question)` | Theorist session: two or three candidates with origins and predictions, one chosen with a reason; code computes the hypothesis warnings (§4.4) and flags a primary estimand that repeats an existing hypothesis |
| `test(hypothesis)`      | Pre-test description, test specification, stages `baseline` → `main` → `robustness`, verdicts                            |
| `interpret(result)`     | Reads verdicts, stability and warnings; writes an `assessment` that closes or opens questions                            |
| `finish`                | Names the `result` nodes offered to Communicate as candidate claims                                                       |

Discover ends on `finish`, when no question is open, or at its budget. Later moves (`challenge` by the Critic, a new Ground attempt, merging branches) add a row here and change no node kind.

**Hypothesis origin.** Every hypothesis states how it was generated and derives from the nodes that produced it.

| `origin`      | Method                                                                                          | `derived_from`                       |
| ------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------ |
| `frame`       | Deduction from a question, direction or researcher hypothesis                                   | `question`                           |
| `observation` | Induction or abduction from what exploration showed                                             | `observation`                        |
| `rival`       | Strong inference [41]: an alternative explanation of an existing result (confounding, reverse direction, selection, measurement) | `result` and the challenged hypothesis |
| `followup`    | A moderator, mechanism or anomaly an assessment opened                                          | `assessment`                         |

Code computes `suggested_by_test_data`: true when the hypothesis derives from an observation on the rows its test reads. It is printed beside the result; with the confirm partition on it is false by construction (§11).

**Predictions.** A hypothesis states what must happen if it holds, written before its test:

- `id`; `role`: `primary` (the primary estimand), `rival` (what a rival explanation predicts instead) or `auxiliary` (a secondary estimand);
- the estimand it reads, `direction` (`positive`, `negative`, or `none` for a placebo or negative control), and an optional `threshold` in outcome units (the `sesoi` once measured, D17).

A rival prediction is tested where its type puts it (§4.4): an adjustment as a robustness variant, a negative control as an adversarial check.

**Pre-test description.** Computed by code at the start of `test` from the estimand, from the primitives of §4.2, before any estimate exists, and written in the `results.json` schema: rows in the population and complete cases over the estimand's columns; exposure levels with rows per level, or exposure spread and support; outcome distribution in the population (skewness, zero, floor and ceiling share); co-missingness of the estimand's columns and missing share by exposure level; cluster count and sizes in the population; and, once that group is built, covariate balance across exposure levels. It never relates the outcome to the exposure: that relation is the test. Code reads it to compute method fit and the cluster warning (§4.5); the Theorist may revise the planned test once after reading it; the Analyst receives it as stage input; the paper renders the sample table from it.

**Test specification.** Frozen after the pre-test description and before `baseline`: estimand, estimator, inference, adjustment set, population. Its hash is the specification identity the Judge reference already carries (§5.3); every node of the test carries it.

**Verdict.** Computed per prediction from the 95% interval of the selected `main` estimate (or the adversarial estimate for a `none` prediction); never written by a model.

| Interval                                                               | Verdict        |
| ---------------------------------------------------------------------- | -------------- |
| Excludes zero on the predicted side, and clears `threshold` when set   | `supported`    |
| Excludes zero on the other side                                        | `contradicted` |
| Within ±`threshold` (only when set)                                    | `negligible`   |
| Otherwise                                                              | `inconclusive` |
| `direction: none`: contains zero / excludes zero                       | `passed` / `failed` |

The verdict answers whether the result matches what the hypothesis predicted; the stability label (§5.5) answers whether it survives other analyses. Both are printed; neither sets the other. A hypothesis stands when its primary prediction is `supported` and its rival predictions are not. In observational designs `supported` is worded as an association consistent with the hypothesis (§10).

**Evidence.** The `result` node is the unit Communicate cites: hypothesis and prediction ids, `origin`, specification hash, the evidence manifest of every attempt (§5.5), verdicts, stability and reasons, and two computed facts, `predicted_before_result` (the prediction precedes every execution of its test in the journal) and `suggested_by_test_data`.

## 5. Search engine

One engine runs every Discover stage; a stage supplies only its goal, inputs and required outputs. Understand and Ground are agent sessions, not search stages (§4.1, §4.3). In Discover the stages run inside the `explore` and `test` moves (§4.6); the engine knows no graph.

### 5.1 Node

- One attempt at the stage goal, built by one Analyst session (§6), which ends by submitting one self-contained script.
- The harness re-runs the submitted script from scratch in the sandbox. Only that run's results file, figures and log count.
- **Results file** `results.json`: named results `{name: {value, ci?, n?, note?}}`, names matching `[A-Za-z][A-Za-z0-9_]*`. A stage or Ground declares the names it requires (e.g. `rows_before`, `rows_after` in Ground); a missing one fails the code checks. Rendering, audits, specification curves and Verify read only this file.
- Metadata: `id`, `parent`, `stage`, `kind` (`draft`, `debug`, `improve`, `variant`, `adversarial`), `status` (`ok`, `buggy`), `score`, `debug_depth`, `reason` (one line).

### 5.2 Step policy

Each step starts one Analyst with a task chosen by:

1. fewer than `min(num_drafts, steps − 1)` drafts (at least one) → **draft**, so every stage keeps a step to debug or improve; the Analyst sees summaries of earlier drafts and must take a different approach;
2. else with probability `debug_prob` → **debug** a `buggy` leaf with `debug_depth < max_debug_depth`;
3. else → **improve** the best `ok` node.

Defaults: `num_drafts = 3`, `debug_prob = 0.5`, `max_debug_depth = 3` [1]. A stage ends at its step budget, when an `ok` node meets the goal, or after `patience` steps without a better score.

### 5.3 Node evaluation

1. **Code checks.** Non-zero exit, timeout, missing required output, invalid results file or out-of-range declared value → `buggy`, no model call.
2. **Judge.** A separate session reads projected code, results and figures, writes an analysis, and returns the typed answers of §8. It scores validity, completeness and fidelity, never effect size, sign or significance [24]. Experiment input masks source literals, including signed numbers, except validated outcome/exposure column names projected to role aliases. A code-owned reference supplies closed method vocabulary and specification identity, never raw hypothesis prose or expected direction. Robustness references follow each attempt's recorded operations, including its transforms. Free-form logs/notes/context and result values/intervals are withheld. Only code-generated sample-count diagnostics are attached; unblinded result figures are publication artifacts. Non-experiment stages attach validated PNGs normally. `figure_issues` records presentation reasons, including on schema correction.
3. **Selection.** Highest-scoring `ok` node; ties go to the earlier node. The best node seeds the next stage. Every `ok` node's estimate is still reported (§5.5), so selection cannot hide the spread of attempts.

Each check has a test that it fires on a bad fixture and stays silent on a good one [37].

### 5.4 Stages

| Stage        | Phase       | Goal                                                                                  | Seeds from             | Required outputs                      |
| ------------ | ----------- | ------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------- |
| `explore`    | Exploration | Relations involving the outcome, group differences relevant to the questions; flag surprises | prepared data (explore rows when the confirm partition is on), initial data analysis, foundation | observations with figures |
| `baseline`   | Experiment  | Simple, transparent model or test for the hypothesis                                  | clean data (confirm rows when the partition is on), hypothesis | key estimate with interval, figure |
| `main`       | Experiment  | Planned analysis and the follow-ups results call for                                  | best `baseline`        | estimates with intervals, figures     |
| `robustness` | Experiment  | Multiverse and adversarial checks (§5.5)                                              | best `main`            | main estimate under every variant     |

Experiment stages are separate; default step budgets are baseline 3, main 6, robustness 6. `search.stage_steps` overrides individual stages. New robustness schedules reserve a step for repair; recorded schedules remain replayable. Scheduled attempts run before repairs and do not stop on goal/plateau; repairs retain specification identity and consume the same budget. Failed execution feedback includes stdout and stderr so repairs can see the underlying fit failure as well as the final exception.

### 5.5 Robustness and stability

- **Variants** [21, 22], each re-estimating the main effect: data choices (exclusions, outlier rules, missing-value handling, codings); model choices (covariates, functional form, estimator); resampling (bootstrap, subgroups). Diagnostic-triggered variants (§4.5) and rival checks of type `adjustment` (§4.4) are required variants. Every variant re-estimates the same estimand; anything else stays out of the stability denominator.
- **Adversarial checks**, at least one [7, 17]: placebo outcome, negative-control exposure or outcome, or permutation of the key variable; rival checks of type `negative_control` are added here. Confounding sensitivity bounds such as the E-value [27], including rival checks of type `sensitivity`, are reported beside the label and do not set it.
- **Specification curve** of sorted estimates with intervals across variants and across every `ok` node of the experiment stages [23].
- **Stability label**, computed: `stable` iff the estimate keeps its sign with an interval excluding zero in ≥ `stability_share` (default 0.8) of variants and no adversarial check fails; else `fragile`. When a run tests k hypotheses, the intervals the label reads are at level 1 − α/k. The label is independent of the prediction verdict (§4.6).

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
| **PI**       | Runs phases; in agent form, chooses next work, goes back, asks the researcher | playbook; later stage, hypothesis, memory, ask-researcher     | Only writer of run-level files |
| **Discover agent** | The PI's form inside Discover: chooses one move at a time over the research graph and names candidate claims; never writes hypotheses, results or assessments (§4.6) | read artifact; moves `explore`, `hypothesize`, `test`, `interpret`, `finish` | Reads the graph, not role sessions |
| **Theorist** | Understand: explores, critiques and synthesizes the Research Frame, asks the researcher, revises from review signals and Ground concerns; Discover: hypotheses with origin, predictions, rivals and planned tests, and interpretation of results (§4.6) | read artifact, ask researcher, submit frame; later literature search | No code tools                  |
| **Data Steward** | Ground: understands, repairs, interrogates and assesses the data; proposes the operationalization and concerns | inspect data, run snippet, view figure, read artifact, submit ground | Runs code; never edits the research context |
| **Analyst**  | Builds one node                                                                                     | inspect data, run snippet, view figure, read artifact, submit | Only role that runs code       |
| **Judge**    | Scores one node with typed answers                                                                  | none                                                          | Independent of the author      |
| **Critic**   | Tries to break hypotheses and main results; scores hypotheses on the §4.4 rubric; proposes adversarial checks; rubric review of the draft | read artifact, view figure                                    | Independent of the author      |
| **Writer**   | Writes and revises the paper from artifacts, checks and critique                                    | read artifact, view figure, literature search                 | Long-form output, own template |

Topology constraints:

- one PI per run, and the Discover agent is its form inside Discover; role sessions and moves run one at a time and communicate only through artifacts and graph nodes;
- at most two hand-offs per node (Analyst → Judge) [37]; Understand and Ground are single sessions with code-checked submits;
- no role writes another role's outputs;
- parallel Analysts, hypothesis tournaments and hierarchical planners are evaluation challengers, not defaults (§14).

Researcher input (research-context answers and review, hypothesis choice, framing edits, notes) is recorded with `supplied_by: researcher` and shown in the paper as `researcher_steered` [6, 8].

## 7. Harness

Makes agent work recorded, bounded and recoverable. Holds no research logic.

### 7.1 Agent loop

- A session is a tool-use loop on the configured model route.
- A tool is a name, a JSON schema and a handler returning text or an image.
- Tools with structured inputs derive their JSON schema and validation from the same typed input model. Input validation completes before the handler runs; phase-specific checks remain in the phase.
- A session ends on its terminal tool (`submit`, `submit_frame`, `submit_ground`, `finish`, `answer`) or its turn limit. A terminal tool may carry a code check: a failure returns to the model as a tool error and the session continues, up to its submit limit.
  Calls in a batch run in order. The first accepted terminal submission ends dispatch; each rejected submission consumes one rejection allowance. Calls received after acceptance or exhaustion of that allowance are journaled as skipped without invoking their handlers.
- Transient provider errors (throttling, timeouts, 5xx) are retried with backoff inside the model client and journaled; they are never research steps.

### 7.2 Tools

| Tool                | Contract                                                          | Limits                                    |
| ------------------- | ----------------------------------------------------------------- | ----------------------------------------- |
| `inspect_data`      | Schema, head, summary, missing counts of a stage input            | Stage inputs only                         |
| `run_python`        | Runs scratch code in the node's scratch folder, returns output    | Sandbox of §7.4; recorded, never a result |
| `view_figure`       | Sends a figure to the model                                       | Run folder only                           |
| `read_artifact`     | Reads results, analyses, change logs, framing, hypotheses, memory | Run folder only; no raw rows              |
| `submit`            | Terminal; the script run as the node                              | Once per Analyst session                  |
| `submit_frame`      | Terminal; research-context patch and framing, checked by code; a failure returns to the Theorist | `understand.max_submits`     |
| `submit_ground`     | Terminal; script re-run from scratch plus operationalization and concerns, checked by code; a failure returns to the Steward | `ground.max_submits` |
| Discover moves      | `explore`, `hypothesize`, `test`, `interpret`, `finish` (terminal); each runs its stage or role session and returns new graph node ids (§4.6) | Discover agent only; Discover budget |
| `search_literature` | Metadata and abstracts of prior work                              | Concepts only, never data values          |
| `ask_researcher`    | One question with a proposed answer and an "unknown" option; the answer is journaled | Theorist in Understand (`understand.max_questions`), PI agent; never under `--auto` |

Tool rules [33]: errors state the field, cause and a next step. The journal keeps complete tool arguments and results. Long errors return complete diagnostic lines within the context budget, with a write-once full report accessible through `read_artifact`. Artifact and execution-log reads return a page and the next character offset; execution errors identify the full log paths. Paths in tool arguments are relative to the run folder; writes stay inside the calling node's folder, or the harness diagnostic folder for error reports.

Artifact readers enforce a per-session allowlist of filenames and owning directories against resolved paths. The Theorist may read framing artifacts under `understand/` and its own diagnostic reports; it cannot read other phases' artifacts, execution logs or another role's diagnostics. Researcher answers returned to the model are fenced as untrusted data; their original text remains in the recorded evidence.

### 7.3 Context assembly

Each session's context is built fresh from the run folder, never inherited from another session [32].

- **Just in time:** artifacts are listed by name and read through tools.
- **Working memory:** short entries citing node ids, persisted across sessions [5, 32].
- **Condensed hand-off:** an Analyst sees its parent through the Judge's analysis, not the parent's session.
- **Size limits per part:** logs keep the tail, files keep the head; cuts are journaled and contract lists are never cut. Session compaction is deferred.
- **Untrusted content** is wrapped and marked; every system prompt states it is data, never instructions.
- **Prompt caching:** supported sessions cache the stable prefix and growing conversation; one-shot requests do not write unused cache entries. Cache reads and writes are journaled.

### 7.4 Sandbox

- Fresh subprocess per script; working directory is an exclusive execution folder; time limit from config. Scratch processes run outside the evidence tree, then their files are snapshotted into the node.
- Inputs arrive as absolute paths in environment variables; credentials are stripped from the environment.
- No container or network isolation in single-user local use; container isolation is required before shared use [5].
- A worker audit hook permits normal Python reads only in that execution folder, mounted input files and runtime/library resources; writes stay in execution and cannot change harness code/logs or inputs. Resolve symlinks; deny sibling/run-root reads and subprocess launch. This prevents accidental file access, not hostile native extensions.

### 7.5 Journal and run store

- **Journal:** append-only events for model calls/cost, tools/wire status, execution starts/completions, nodes/stages, artifact commits and phases. Sessions, context cuts and explicit budget raises are traceable. A truncated tail remains untouched; new events use a numbered segment. Interior corruption fails visibly.
- **Run store:** write-once files; version-4 `run.json` holds initial metadata and a secret-free config snapshot. Later status lives in committed numbered state files, citing prior state and committed artifact paths. Resume restores cost from every recorded model call, uses saved config and policy RNG, preserves incomplete attempts and never resets spend. Explicit budget raises are recovered from the journal and reflected in later state. Interactive resume supplies a new researcher callback; the saved automatic-run setting disables it. Cost not journaled at process death cannot be recovered.
- **Release:** code, outputs, seeds and journal stay in the run folder, so a run ships its own trace [18].

### 7.6 Budgets and failures

Money caps, token prices and cache-price multipliers must be finite and nonnegative. Zero is valid for a zero-spend cap or free usage.

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

Only an explicit, journaled researcher action may raise a stopped run's money cap; agents and config reloads cannot. Raising the cap never resets recorded spend.

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
  data/                    discovery raw.csv, holdout.sealed, split.json (holdout rows; confirm rows when on),
                           processed.parquet, ida-raw.json, ida.json (one per accepted Ground attempt)
  understand/attempt-*/    research.json/.md (cleaned research context), framing.json, questions.json, warnings.json,
                           review.yaml; then the researcher-reviewed attempt
  ground/attempt-*/        submit-*/execution/ (script, processed.parquet, changes.json, results.json),
                           operationalization.json, concerns.json, readiness.json
  hypotheses/attempt-*/   one primary estimand, rival explanations, refuting result, warnings, method fit,
                           tested_on, sources/attribution
  discover/graph/          append-only research-graph nodes (question, observation, hypothesis, result, assessment)
  discover/pretest/        pre-test description and frozen test specification per tested hypothesis
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
3. **Write** a fixed LaTeX template: Abstract; Introduction; Data and Methods with the change table, the operationalization table (proposed by the data agent), the hypothesis with its rival explanations (and mechanism when stated); target additions are sample flow, a sample characteristics table without significance tests, method fit and the `tested_on` sentence; Results with Exploratory, Main, Robustness subsections; Discussion with generated limitations: `proposed` and `unknown` entries relied on, unresolved frame concerns, data concerns, readiness and hypothesis warnings, a bounded outcome, and the fixed sentence that data preparation had raw-data access; Conclusion [28]. Numbers appear only as named-result references. Code renders all successful experiment attempts and computed stability/reasons, plus a status list of failed/missing attempts. Every number is resolved from `results.json` with canonical node keys and selected-stage aliases. Reserve one of at most four figures for the specification curve, place every figure next to a generated textual reference, and render caption macros too.
4. **Render** named results from result files [6]; an unknown name renders `??` and warns.
5. **Check:** build errors fed back to the Writer for up to `latex_rounds` rounds [1]; vision check of each figure against its caption [1]; number audit of literals not from named results; consistency checks on reported relations (means with n, tests with statistics) [29, 30]; Critic rubric review [2] and one Writer revision.
6. **Claims file** beside the PDF: each claim with its named results, nodes and label [20]. With the Discover agent, claims come from the `result` nodes named at `finish`, each with its origin, verdicts, stability and computed facts (§4.6); a research-path section generated from the graph lists every move, including dead ends and null results.
7. **Claim language:** negative and inconclusive results, and `contradicted`, `negligible` and `inconclusive` verdicts, reported with equal standing; observational designs described as association; `fragile` results described as fragile; `underpowered` hypotheses described as unable to detect the stated smallest effect.
8. **Appendix** generated by code: experiment scripts only, attributed by stage/node; data code and the change table are not duplicated. Broader publication audits, reviews, claims files and figure aggregation remain target extensions, not part of the current local writer.
9. **Disclosure** that the paper was generated by an AI system.

LaTeX engine: first found of `tectonic`, `latexmk`, `pdflatex`; build in scratch then preserve each fresh build snapshot. Without an engine the run writes source; `popper pdf` resolves the committed report (or old `report/paper.tex`) and builds later. `popper resume` continues only version-4 runs; completed runs reuse the existing outcome without model calls.

## 11. Verify

- **Holdout:** at ingest, before profiling, `holdout_fraction` (default 0.2; 0 disables) of rows is set aside, grouped by an id column when given. These rows never reach a node or tool. The split ships before Verify because exposure cannot be undone: a run without a holdout can never be verified. Holdout rows are sealed with a per-run key kept outside the run directory; scripts never receive it.
- **Confirm partition:** after the holdout, `confirm_fraction` (default 0, off; the comparison of §13 decides the default) of discovery rows is marked confirm, grouped the same way, and recorded in `split.json`. When on, the Ground script fits its rules on explore rows and is replayed unchanged on confirm rows; `explore` reads only explore rows; experiment stages read only confirm rows. Initial data analysis (§4.2) uses all discovery rows. Each hypothesis records the computed `tested_on` (`all_discovery` or `confirm`), printed in Data and Methods; no new label is added, since every result outside Verify is already `exploratory`. Off, a weak effect keeps its power; on, about half the rows test it.
- **Verify a result:** lock the data and analysis scripts that produced it and a margin chosen before looking (the hypothesis `sesoi` when it was set before exploration); run once on the holdout; compute `confirmed`, `not_confirmed` or `inconclusive`. A failed run is `inconclusive` and is not repeated.
- One look per result [25]; assumptions are stated [7]. Exposure and error budgets exist only in `verify/`.

## 12. Knowledge

- `search_literature` returns metadata and abstracts for the Theorist and Writer; in Understand it supplies `proposed` research-context entries with the retrieved work as evidence (§4.1).
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
- **Per-run metrics:** node failure rate, audit and consistency warnings, holdout gap (evaluation re-runs the reported script on the unsealed holdout after the run; the run never sees it), Critic rubric score, draft diversity, cost, wall time.
- **Comparisons:** research-context body only vs with front matter; agent-cleaned research context with vs without researcher review; confirm partition on vs off; agentic vs single-shot nodes (`max_turns = 1`); one vs three drafts; diverse vs free drafts; vision feedback on vs off; Ground agent vs `data` tree stage; shuffled-outcome scratch for the Steward on vs off; warnings vs gates on roles and clusters; Discover agent vs the phase-3/4 playbook; PI agent vs playbook; Critic on vs off; multiverse vs single robustness check; decision model vs Judge per question.
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
| D3  | Ground before exploration, run by one agent session with code-checked submits; analytic choices recorded and measurable | [15, 16, 21] | Question-first pipeline with fixed preprocessing; best-of-N cleaning chosen by a Judge | measured |
| D4  | Hypotheses grounded in the Research Frame, foundation and explored data, with computed warnings, challenged by a Critic, chosen by the researcher or PI | [4, 7, 8, 9, 41] | Hypotheses from literature alone; tournament ranking; code gates before an observed failure | measured |
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
| D17 | Hypothesis with one primary estimand, rival explanations and a refuting result; typed rival checks and a magnitude set before exploration are measured additions; optional mechanism with tested auxiliary predictions | [7, 26, 41, 42] | Free-text hypotheses of any complexity; rival checks mixed into the stability denominator | measured |
| D18 | Holdout split at ingest, before Verify exists                                                | [25]                    | Holdout created only when verification is requested          | fixed    |
| D19 | One research context (narrative body, optional front matter with per-entry provenance and concepts), framed by a Theorist session and steered by item-level researcher signals before analysis | [4, 6, 8, 39, 40] | Free-text brief only; separate brief and study files; agent-inferred meanings used as facts; researcher filling a form | measured |
| D20 | Descriptive statistics computed by one code module behind every describer, before and after `data` | [39, 40]       | Model-computed descriptives; several describers               | fixed    |
| D21 | Optional explore and confirm partitions within discovery rows, off by default until measured; `tested_on` always printed | [24, 25] | Testing on the suggesting rows without saying so; a partition that `data` still fits on | measured |
| D22 | Layered method vocabulary that classifies plans; computed method fit and few-cluster advice as warnings (gates only if measured); diagnostic-triggered variants | [40, 43, 44] | Flat method list; normality tests choosing the method; cluster-robust SE with few clusters unflagged | measured |
| D23 | Understand and Ground as agent sessions; tree search kept where attempts are compared (Discover); a bounded return from Ground to Understand | [3, 4, 31, 37] | Tree search in every phase; Ground silently changing research intent | measured |
| D24 | Discover as one agent choosing moves over an append-only research graph; trees inside moves; hypotheses with a stated origin and structured predictions; a pre-test description per estimand; verdicts computed from predictions | [4, 5, 7, 40, 41] | A linear explore → hypothesis → experiment pipeline; parallel branch agents by default; model-asserted support or contradiction; free-text refuting results | measured |

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

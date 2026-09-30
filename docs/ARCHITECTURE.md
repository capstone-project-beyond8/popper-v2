# Popper v2 Architecture

Popper is an AI scientist for quantitative tabular data. Given a research brief and a dataset, it frames the problem, prepares and explores the data, forms hypotheses from what it sees, runs and debugs its own analysis code, looks at its own figures, and writes the study up as a LaTeX report. The researcher can choose, correct and redirect along the way.

This document describes the design the code follows: what is built, the rules the code keeps, and, marked with a milestone, what is next. Order of work lives in [ROADMAP.md](ROADMAP.md). The long-horizon design of Popper v1 (`../popper/docs/`) is background. What v2 adopts from it is restated here (§11), so this document stands alone.

## 1. Principles

1. **Output first.** Every milestone ends in a run that produces a report someone can read. Infrastructure is added only when a run needs it.
2. **Improve on demonstrated systems.** Start from mechanisms with published evidence (§11), reproduce them, then measure what Popper adds. Neither a reference system's success nor combining several mechanisms proves Popper's own performance.
3. **Agents work; the harness records.** Agents use tools and write code. The harness runs the code, assembles each agent's context, and records every call as a side effect. Recording never asks an agent to declare anything.
4. **Roles, not agent sprawl.** A role is a prompt, a tool set and a model route. Separate agent sessions exist where an independent context helps, as with critique or judging. Parallelism and extra roles are added when evaluation shows they pay.
5. **Typed decisions, measured.** Bounded judgments ("is this node buggy?", "is the goal met?", "which hypothesis first?") are typed questions with a rule fallback. A decision model may answer them, but only after it has been measured.
6. **Labels, not locks.** Every result says how it was produced. Everything outside Verify is `exploratory`. Labels are computed by code, never raised by a model or a reviewer.
7. **Numbers come from artifacts.** Values in the report are read from `results.json` files written by executed scripts.
8. **Measured restriction.** A new gate, reviewer, rule or topology change needs a failure seen in real runs and a comparison on the evaluation set (M4). Without evidence, the simpler version stays.
9. **One owner per concept.** Each concept is defined in one module and one section of this document.

## 2. Phases

A run passes through five phases. This is the AI Scientist-v2 pipeline (ideation → experiments → write-up) with data work inserted before it, because tabular research starts from a given dataset.

| # | Phase | Function | Package | Does | Output |
|---|---|---|---|---|---|
| 1 | **Ideation & framing** | Understand | `understand/` | Read the brief and a structural profile of the data. Restate the problem, list research questions and the variables they need, sketch directions. Self-reflection rounds | `framing.json` |
| 2 | **Data** | Ground | `ground/` | Tree-search stage: fix types, missing values, duplicates, impossible values and categories; derive the variables the questions need; record every change and the rows it affected | `data/processed.parquet`, `changes.json` |
| 3 | **Exploration & hypothesis** | Discover | `discover/` | Tree-search stage of exploratory analysis. The observations then become testable hypotheses, each with planned experiments; from M2 these are critiqued and ranked | `hypotheses.json` |
| 4 | **Experiment** | Discover | `discover/` | Staged tree search per chosen hypothesis: baseline → main → robustness (Sakana stages 2–4) | Best nodes with estimates, figures, stability label |
| 5 | **Publication** | Communicate | `communicate/` | Aggregate figures, write the LaTeX paper, check figures and numbers, review | `report/paper.pdf`, `review.json` |
| — | *Verify (optional)* | Verify | `verify/` (M6) | Re-run a frozen experiment once on held-out rows; the outcome is computed by code | `verify/*.json` |

The **PI** (package `coordinator/`) runs the phases in order. Until M2 it is a fixed playbook. From M2 it is an agent (§3.2) that follows the same order by default, but can loop back with a recorded reason:
- an experiment result may add or revise a hypothesis (4 → 3);
- a data problem found later reopens the data stage as a new child node (3/4 → 2).

## 3. Subsystems

| Subsystem | Package | Owns | Section |
|---|---|---|---|
| **Research phases** | `understand/`, `ground/`, `discover/`, `communicate/`, `verify/` | Goals, prompts and outputs of each phase | §2, §6, §7, §9 |
| **Agent team** | role prompts in their phase packages; PI in `coordinator/` | Who does what, with which tools and model, and in which session | §3.2 |
| **Harness** | `harness/` | Model access, agent loop, tools, context assembly, execution, recording, budgets, failure handling, config | §3.3 |
| **Decision layer** | `harness/decisions.py` (M1) | Typed Judge answers, a second answerer (Jev), off/shadow/on modes, and disagreement records | §3.4 |
| **Tree search** | `treesearch/` | The generic stage engine: nodes, steps, checks, selection | §6 |
| **State and memory** | the run directory, written through `harness/store.py` | Artifacts, assessments, working memory, attribution | §5 |
| **Knowledge** | `understand/literature.py` (M5) | Prior work for framing, hypotheses and related work | §10 |
| **Evaluation** | `evals/` (M4) | Suites, metrics, comparisons, adoption decisions | §10 |

### 3.1 Dependencies

```text
cli ──► coordinator ──► understand · ground · discover · communicate · (verify)
                               │
                               ▼
                           treesearch ──► harness (llm · agent loop · tools · context · interpreter · store · journal · budget · decisions · config)
```

- `harness` imports nothing else in Popper and holds no research logic.
- `treesearch` imports only `harness`. It knows nodes, steps and scoring, but no stage goals.
- Phase packages import only `harness` and `treesearch`. They never import each other; results pass between them as files in the run directory.
- `coordinator` is the only package that knows the playbook.
- `evals/` may import anything; production code never imports `evals/`.
- Prompts live next to the code that uses them (`<package>/prompts/*.md`).
- Default configuration ships as `src/popper/harness/default_config.yaml`. A `--config` file overrides it key by key, and `POPPER_MODEL`, when set, overrides every model route.

### 3.2 Agent team

A **role** is a prompt, a tool set and a model route. v2 creates a separate role only for one of two reasons:
- it needs different tools;
- it needs an **independent context**, so that it judges work without inheriting the author's reasoning.

That gives six roles instead of v1's ten profiles.

| Role | Does | Tools | Why separate | From |
|---|---|---|---|---|
| **PI** | Runs the playbook. From M2 it chooses next work from results and memory, loops back, and asks the researcher | M0: none (fixed playbook). M2: `run_stage`, `propose_hypotheses`, `revise_hypothesis`, `reopen_data`, `ask_researcher`, `update_memory`, `finish` | Only role that writes run-level files | M0 / M2 |
| **Theorist** | Framing with self-reflection; turns exploration results into hypotheses with planned experiments | `read_artifact`, `search_literature` (M5) | Reasons over artifacts and needs no code tools | M0 |
| **Analyst** | Builds one tree node: inspects, tries, submits a script | `inspect_data`, `run_python`, `view_figure`, `read_artifact`, `submit` | The only role that runs code | M0 |
| **Judge** | Reads a node's code, output, results and (M1) figures; writes `analysis.md`; answers the node questions (§3.4) | none; context only | Scores work it did not write | M0 |
| **Critic** | Independent critique: confounders, alternative explanations, claims beyond the design. Applied to hypotheses and main results (M2) and to the draft paper (M3, rubric review) | `read_artifact`, `view_figure` | Must not share the author's context | M2 |
| **Writer** | Writes the paper from artifacts and revises from checks and critique | `read_artifact`, `view_figure`, `search_literature` (M5) | Long-form output with its own template | M0 |

**Topology.** One run has one PI. The PI starts role sessions one at a time and waits for their artifacts. Roles never write each other's outputs. Parallel analysts per stage (Sakana uses four) and hypothesis tournaments (Co-Scientist) are M4 comparisons, not defaults.

### 3.3 Harness

The harness is the environment every agent works in. Its job is to make free agent work **recorded, bounded and recoverable** without steering the research.

**Agent loop.** `agent_loop(role, system, task, tools, max_turns)` runs a Bedrock Converse tool-use session.
- A tool is a name, a JSON schema and a handler. Handlers return text or an image.
- The loop ends when the agent calls its terminal tool (`submit`, `finish`, or the role's answer tool) or reaches `max_turns`.

**Tools.**

| Tool | Does | Limits |
|---|---|---|
| `inspect_data(name)` | Schema, head, describe and missing counts of a stage input | Stage inputs only |
| `run_python(code)` | Runs a scratch snippet in the node's `scratch/` folder and returns its output | Same interpreter rules as nodes; recorded, never a result |
| `view_figure(path)` | Sends a PNG to the model | Run directory only |
| `read_artifact(path)` | Reads run files: `results.json`, `analysis.md`, `changes.json`, `framing.json`, `hypotheses.json`, `memory.md` | Run directory only; no raw data rows beyond `inspect_data` |
| `submit(code)` | Terminal: the script the harness runs as the node | One per node agent |
| PI tools (M2) | Listed in §3.2 | PI only |
| `search_literature(query)` (M5) | OpenAlex metadata and abstracts | Concepts only, never data values |

Tools read the run directory and write only inside the calling node's folder. Stage outputs are created only by submitted scripts, and run-level files only by the PI.

**Context assembly.** Each agent's context is built from the run directory, never carried over from another agent's conversation.
- `harness/context.py` assembles the role prompt, the task, the relevant artifacts and working memory (M2).
- Each part has a character limit, and truncation keeps the tail of logs and the head of files.
- Brief text, dataset strings, script output and retrieved text are wrapped in `<untrusted>` tags, and every system prompt states that their content is data, never instructions.

**Recording.** Every model call (role, tokens, cost), tool call (arguments, truncated result), script execution (code hash, exit, duration) and decision (§3.4) is appended to `journal.jsonl`. This is a side effect of the harness, not a duty of the agent.

**Budgets.**
- *Resource budgets* (USD, per-phase USD from M2, `max_turns` per session, `steps_per_stage`) end work safely and are printed as progress.
- *Search budgets* (drafts, debug depth) are soft task structure.
- *Error budgets* exist only inside Verify.

**Failure classes.**

| Class | Example | Handling |
|---|---|---|
| Technical | throttling, timeout, 5xx | Retry with backoff inside `llm`, journaled; not a research step |
| Research | script error, missing output, no submit | The node becomes `buggy` and informs the next step |
| Budget | USD cap reached | Stop, write `run.json` with `budget_exceeded` |
| Terminal | a stage with no working node | Stop, write `run.json` with `failed` and the stage |

No failure path edits a recorded artifact. Resume after a crash is deferred (M7).

**Execution.** Each script runs in a fresh subprocess with the node folder as working directory and a timeout. Credentials are stripped from the environment, and inputs are passed as `POPPER_INPUT_<NAME>`. Accepted pilot limitation: there is no container or network isolation, which is fine for one researcher running their own data locally. Containers come before shared use (M7).

**Progress.** One terminal line per phase and per node, for example `[data] data-002 debug → ok score 7 · $0.41`. `--quiet` turns it off.

### 3.4 Decision layer (M1 shadow, M4 measured)

The Judge's verdict is a **typed answer**, not free text:

| Question | Type |
|---|---|
| `node_buggy` | yes/no |
| `goal_met` | yes/no |
| `node_score` | 1–10 |

From M2 the PI also answers `hypothesis_rank`, a score per option. Code reads these fields; the prose goes to `analysis.md`.

Because the answers are typed, **any answerer can fill them**: the LLM Judge (the default and the reference) or a decision model such as TypeSafe **Jev** (System One). This keeps v1's decision-layer idea but changes where it sits. v1 placed decisions as a separate layer on pipeline steps. In v2 the decision model is a second answerer for the same questions the Judge already answers, so adopting it changes no interface.

- **Modes per question**:
  - `off`: only the Judge answers;
  - `shadow`: both answer, and the Judge's answer is used;
  - `on`: the decision model's answer is used when its confidence clears the threshold, otherwise the Judge's.

  Every question starts `off`, and M1 ships them in `shadow`.
- **Every disagreement becomes evaluation data.** In `shadow`, each run appends both answers and the facts they saw to the journal. M4 checks a sample of disagreements by hand and computes agreement, calibration and cost per question. A question goes `on` only if the decision model matches or beats the Judge. This is the main improvement over v1: v1 required calibration evidence but had no built-in way to collect it.
- **Limits** (kept from v1):
  - a decision picks among given options or scores given facts;
  - it never writes code or prose;
  - it never computes a number that code can compute;
  - it never overrides a code check or a label.
- **Fallback**: an unavailable provider or malformed answer uses the Judge's answer, and the reason is journaled. Popper works fully without Jev.

## 4. Positioning

What Popper takes from each reference system, and what it adds. Each addition is a claim to be tested in M4, not an assumed gain.

| Reference | Mechanism reproduced | Popper adds |
|---|---|---|
| **AI Scientist-v2** | Staged best-first tree search, debug limits, VLM figure feedback, LaTeX write-up, LLM reviewer | Data-first phases. Nodes are tool-using agents instead of one-shot code. Code checks run before the judge. Numbers are traced through `\R{}`. Labels are computed by code. A decision layer handles node judgments. Stability labels come from robustness. Verify is optional |
| **Co-Scientist** | Generate → critique → rank → evolve hypotheses; researcher steering | Hypotheses grounded in explored data and tested in the same run; typed ranking with a recorded rule baseline |
| **Kosmos** | A shared world model that shapes the next task | `memory.md` entries cite node ids; the experiment tree keeps every attempt re-runnable |
| **data-to-paper** | Tracing reported numbers back to code | Tracing covers the whole run, including tree history and data changes |
| **POPPER (Huang et al.)** | Falsification tests for measurable implications | Held out until requested; runs as the optional Verify with a code-computed outcome |

## 5. State and memory

A run is a folder. There is no database. Files are written once, and a change creates a new file or a new node, never an edit.

```text
runs/<run_id>/
  run.json                 config snapshot (no secrets), inputs, status, cost
  journal.jsonl            append-only: model calls, tool calls, executions, decisions, phase events, errors
  brief.md                 input brief (copied)
  data/raw.csv             input data (copied); data/holdout.csv only with --holdout (M6)
  data/processed.parquet   written by the best data node
  understand/profile.json  structural profile of the raw data
  understand/framing.json  problem, questions, needed variables, directions (with supplied_by)
  hypotheses.json          hypotheses with planned experiments, source nodes, supplied_by
  tree/<stage>/<node_id>/  stages: data, explore, baseline, main, robustness
    code.py                the submitted script, as run
    scratch/               outputs of run_python snippets (not results)
    meta.json              parent, kind, status, score, goal_met, debug_depth, reason
    stdout.txt  stderr.txt
    results.json           values the script reports: {name: {value, ci?, n?, note?}}
    figures/*.png
    analysis.md            the judge's reading (an assessment)
  memory.md                working memory citing node ids (M2)
  critiques/*.md           Critic assessments citing node ids (M2)
  report/paper.tex  report/paper.pdf  report/compile.log  report/review.json
```

Three kinds of content, adopted from v1:

| Kind | Examples | Changes by |
|---|---|---|
| **Source artifact** | data versions, `code.py`, `results.json`, figures, outputs | Never edited; a new node or version |
| **Assessment** | `analysis.md`, critiques, figure reviews, `review.json`, decisions | A new attributed assessment beside the old one |
| **Working memory** | `memory.md` (M2) | New entries appended by the PI, each citing artifacts |

An assessment or memory entry cites the artifacts it rests on. A wrong interpretation is corrected by a new assessment, without touching the execution it interprets.

**Attribution.** Framing fields, hypotheses and choices record `supplied_by`: `agent` or `researcher`. Researcher edits and choices (M2) are labelled `researcher_steered` and shown in the paper.

**Node kinds.** `draft`, `debug`, `improve` and `robustness`. Each child records a one-line `reason`, so a reader sees why it exists.

## 6. Tree search

The engine adapts the AI Scientist-v2 `bfts` loop.

**Node.** Each node is built by an **Analyst** agent (§3.2) and ends with one self-contained Python script. The script reads the stage inputs, writes `results.json` and figures into its node folder, and prints a short log. The harness re-runs the submitted script from scratch, and only that run's outputs are the node's result. So there is no hidden state, and every node can be re-run.

**Step.** Each step runs one Analyst, with the task set by the action:
1. If the stage has fewer than `num_drafts` root nodes, **draft** a new approach.
2. Otherwise, with probability `debug_prob`, pick a buggy leaf whose debug depth is below `max_debug_depth` and **debug** it.
3. Otherwise, **improve** the best working node (in the robustness stage, add a **robustness** child).

The Analyst gets the stage goal, the context, and for debug or improve the parent's code, errors and analysis. It uses its tools within `max_turns`, then calls `submit`. An Analyst that never submits yields a `buggy` node.

**Checks, then the judge.**
1. **Code checks first.** A non-zero exit, a timeout, a missing required output or an invalid `results.json` makes the node `buggy` without a model call.
2. **Then the judge** (§3.2) reads the code, output and results, and from M1 the figures. It writes `analysis.md` and gives typed answers to `node_buggy`, `goal_met` and `node_score` (§3.4).
3. **Best node.** The highest-scoring `ok` node wins; ties go to the earlier node.

Scripts receive inputs through `POPPER_INPUT_<NAME>` (absolute paths). `results.json` maps snake_case names to `{"value": number | string, "ci": [low, high]?, "n": int?, "note": str?}`.

**Stages.** One engine runs every stage; only the goal, the inputs and the required outputs change. The best node of one stage seeds the next.

| Stage | Phase | Goal | Input | Required outputs |
|---|---|---|---|---|
| `data` | Data | Clean, validate and derive variables; document every change and the rows it affected | `raw.csv`, framing | `processed.parquet`, `changes.json`, `rows_before`/`rows_after` |
| `explore` | Exploration & hypothesis | Distributions, relations and group differences relevant to the questions; flag surprises | processed data, framing | Figures and observations in `results.json` |
| `baseline` | Experiment | A simple, transparent model or test for the hypothesis | processed data, hypothesis | Key estimate with interval, figure |
| `main` | Experiment | The planned analysis and the follow-ups results call for | best baseline node | Estimates with intervals, figures |
| `robustness` | Experiment | Sensitivity to cleaning choices, alternative specifications, subgroups, resampling | best main node | The main estimate under each variant |

A stage ends when it reaches `steps_per_stage`, or earlier when an `ok` node meets the goal. M0 runs `data`, `explore` and one combined `experiment` stage. M1 splits `experiment` into `baseline` → `main` → `robustness`.

**Stability label (M1).** Code computes a label from the robustness outputs, adopted from v1: `stable` when the main estimate keeps its sign and its interval excludes zero in at least 80% of the variants, `fragile` otherwise. The label is printed next to the result in the paper, and no model sets it.

**Analysis practice.** The Analyst and Critic prompts carry a short checklist adopted from v1's methodology:
- justify a processing choice by validity, never by the relation it produces;
- flag a derived variable that uses the outcome;
- report every rule that drops rows;
- prefer effect sizes with intervals over p-values alone;
- keep association distinct from causation.

## 7. Publication

1. **Collect** the framing, data changes, exploration figures, hypotheses, best experiment nodes, and stability labels.
2. **Write.** The writer fills a fixed LaTeX template section by section: abstract, introduction, data, exploration, hypotheses, methods, results, robustness, limitations. Numbers are written as `\R{stage.name}`, and figures are referenced by file name.
3. **Render.** `\R{}` values come from `results.json`. An unknown name shows as `??` and produces a warning.
4. **Check** (M3):
   - aggregate figures in one plotting script;
   - feed compile errors back to the writer;
   - have the vision model check each figure with its caption;
   - audit numbers (any number in the prose not produced by `\R{}` is listed);
   - get the Critic's rubric review as `review.json` and revise once.
5. **Claim language.** The Writer and Critic follow the checklist of §6. Negative and inconclusive results are reported with the same standing as positive ones, and an observational design is described as association.
6. **Appendix**, generated by code: the data changes, the experiment tree summary, the code of reported nodes, researcher-steered choices, and the label.

The LaTeX source is compiled with the first engine found, in the order `tectonic`, `latexmk`, `pdflatex` (run twice). Its output goes to `report/compile.log`. With no engine, or on a failed compile, the run still writes `paper.tex`; `popper pdf RUN_DIR` rebuilds the PDF later.

## 8. Always-on rules

| Rule | How the code keeps it |
|---|---|
| Every execution is recorded | The harness journals every model call, tool call, execution and decision |
| History is appended | Run files are write-once; a fix is a new child node or a new assessment |
| Labels are computed | `exploratory`, `stable`/`fragile` and `confirmed` come from code; the template prints them and no prompt can change them |
| Numbers resolve to artifacts | `\R{}` values come from `results.json`; unknown names are warnings (errors once M4 shows they are rare) |
| Untrusted text is data | Brief, dataset strings, outputs and retrieved text are wrapped and never treated as instructions |
| Secrets stay out | `run.json` holds no credentials; scripts get no credential variables |

## 9. Verify (optional, M6)

Verify is one package with two touch points on the rest of the system:

1. `--holdout FRACTION` splits rows at run start (grouped by an id column when given). `data/holdout.csv` never reaches a node or a tool.
2. `popper verify <run> <result>`:
   1. freezes the data script and the experiment script that produced the result, and records a margin chosen before the look;
   2. runs both once on the holdout;
   3. computes `confirmed`, `not_confirmed` or `inconclusive` in code. A failed run is `inconclusive` and is not re-run.

The contract comes from v1 (frozen before read, run once, outcome by code) and is strict when used. No other package knows about exposure or error budgets. v1's `science/` (method cards, intervals, error control) is the source to port when Verify needs more than one test.

## 10. Knowledge and evaluation

**Knowledge (M5).** `search_literature` returns OpenAlex metadata and abstracts for the Theorist and Writer.
- Queries carry concepts, never data values.
- Prior work shapes directions and related work, and is never evidence for this run's results.
- Hypotheses record whether they replicate, extend or contradict prior findings. This describes search coverage, never a novelty claim.

**Evaluation (M4).** `evals/` runs Popper on suites and compares configurations at equal model and budget. Adopted from v1:

| Suite | Contains | Measures |
|---|---|---|
| Planted | Synthetic data with known effects and planted data issues | Effect recovery, data-issue fix rate |
| Null | Synthetic data with no real effect | How often an exploratory result is written as a finding, and whether it is labelled `fragile` |
| Reference | Public datasets with well-known findings | Agreement with the known findings |

- **Every run reports:** Critic rubric score, share of numbers traced, cost, time, failure rate.
- **Comparisons:**
  - agentic vs one-shot nodes;
  - drafts 1 vs 3;
  - vision on vs off;
  - PI agent vs fixed playbook;
  - Critic on vs off;
  - for each Judge question, the decision model vs the LLM Judge, using the disagreements collected in shadow.
- **Decisions:** each comparison ends in a record in `evals/decisions.md` (what changed, the result, the default kept). Evaluation never changes a run's results.

## 11. From v1 to v2

v1 is a reference, not a template. Each v1 idea below was kept only in a form that serves v2's goal, and made smaller or stronger where v2's design allows. Ideas that only served v1's strict confirmation path wait for Verify, or are dropped.

| v1 concept | v2 form | What improved |
|---|---|---|
| Analysis Ledger + durable read intent before every data read | `journal.jsonl` written by the harness as a side effect; the holdout never reaches a node, so exposure needs no tracking outside Verify | No gate on the exploratory path; one record instead of a ledger store plus events |
| Research Graph (typed nodes and relations, projections, schema versions) | The run directory: node folders linked by `meta.json`; views such as `tree.html` are derived from it | One source of truth; nothing to migrate |
| Source artifact / assessment / working memory | Kept: code and results are artifacts; `analysis.md`, critiques and reviews are assessments; `memory.md` is memory. The folder layout shows the kind | The separation holds without a type system |
| Registered method cards and tools | Free analysis code in tree nodes; the robustness stage and a code-computed `stable`/`fragile` label take the place of pre-registration for exploratory work | Open method space; fragility is measured instead of prevented |
| Nine semantic rails (enforce/shadow) | Code checks on every node, the Judge, and the Critic | Fewer mechanisms; each one has a single owner |
| Eleven fixed pipeline steps | Five phases on one tree engine; the PI can loop back (M2) | Results change the next step |
| Ten role profiles | Six roles, separated only for tools or independent context | Fewer sessions and prompts to maintain |
| Decision layer on pipeline steps | Typed Judge answers with a second answerer and built-in disagreement collection | Calibration data comes from normal runs |
| Confirmation rounds, grants, partitions, error plans | One holdout split, one frozen look, an outcome computed by code (Verify, M6); v1's `science/` is ported only when a second test type is needed | Verify is isolated and strict; the rest of the system never pays for it |
| Integrity audit that blocks views | Number audit as warnings; they become errors once M4 shows false alarms are rare | Measured before enforced |
| Eleven publication views and a registered chart catalog | One paper, `tree.html`, and figures from executed code | Output first; every figure still traces to its code |
| Suites S0–S3, yield metrics, decision classes | Planted, null and reference suites run by one command; `evals/decisions.md` records each adoption | Same discipline, a fraction of the machinery |
| Settings API with tiers | One YAML file, `--config`, and `POPPER_MODEL` | Nothing to serve |
| Domain packs, programs and lineages, disclosure control, tenant auth, venue profiles | Not in v2 until a milestone needs them | — |

Kept unchanged, because they are cheap and central:
- the five research functions;
- record, don't gate;
- computed labels;
- append-only history;
- the failure and budget classes;
- untrusted-content handling;
- negative results reported with equal standing;
- the analysis-practice and claim-language checklists;
- the strict Verify contract;
- measured restriction.

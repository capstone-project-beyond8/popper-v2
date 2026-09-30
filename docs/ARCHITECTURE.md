# Popper v2 Architecture

Popper is an AI scientist for quantitative tabular data. Given a research brief and a dataset, it proposes hypotheses, prepares the data, runs and debugs its own analysis code, looks at its own figures, and writes up the study as a LaTeX report. The researcher can choose, correct and redirect along the way.

This document describes the design that the code follows. It records what is built and the rules the code keeps. Order of work lives in [ROADMAP.md](ROADMAP.md). The long-horizon design of Popper v1 (`../popper/docs/architecture.md`) is background reading, not a contract. Anything taken from it is restated here when it is adopted.

## 1. Principles

1. **Output first.** Every milestone ends in a run that produces a report someone can read. Infrastructure is added only when a run needs it.
2. **Learn from demonstrated systems.** The experiment engine adapts the staged tree search of [AI Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) (itself built on AIDE) to tabular analysis. Other mechanisms (Co-Scientist ideation, Kosmos memory) come in when evaluations call for them.
3. **Agents write code; the harness records.** The model writes whole analysis scripts. The harness runs them, records what ran, and returns the outputs. Recording never asks the agent to declare anything.
4. **Labels, not locks.** Every result says how it was produced. Everything outside Verify is `exploratory`. Labels are set by code, never by a model.
5. **Numbers come from artifacts.** Values in the report are read from the `results.json` files that scripts wrote, not typed by the model.
6. **Measured restriction.** A new gate, reviewer, rule or topology change needs a failure seen in real runs and a comparison on the evaluation set (M4). Without evidence, the simpler version stays.
7. **One owner per concept.** Each concept is defined in exactly one module and one section of this document.

## 2. Phases and research functions

A run passes through five phases. This is the AI Scientist-v2 pipeline (ideation → experiments → write-up) with data work inserted before it, because tabular research starts from a given dataset rather than from an idea alone. Each phase belongs to one of Popper's research functions.

| # | Phase | Function | Package | Does | Output |
|---|---|---|---|---|---|
| 1 | **Ideation & framing** | Understand | `understand/` | Read the brief and a structural profile of the data. Restate the problem, list research questions and the variables they need, sketch directions. Self-reflection rounds (Sakana ideation) | `framing.json` |
| 2 | **Data** | Ground | `ground/` | Tree-search stage: fix types, missing values, duplicates, impossible values and categories; derive the variables the questions need; record every change and the rows it affected | `data/processed.parquet`, data report |
| 3 | **Exploration & hypothesis** | Discover | `discover/` | Tree-search stage of exploratory analysis on the processed data (distributions, relations, groups, figures). The observations then become testable hypotheses, each with planned experiments | `hypotheses.json` |
| 4 | **Experiment** | Discover | `discover/` | Staged tree search per chosen hypothesis: baseline → main test → robustness/ablation (Sakana stages 2–4) | Best nodes with estimates and figures |
| 5 | **Publication** | Communicate | `communicate/` | Aggregate figures, write the LaTeX paper, check figures, review | `report/paper.pdf`, `review.json` |
| — | *Verify (optional)* | Verify | `verify/` (M6) | Re-run a frozen experiment script once on held-out rows; the outcome is computed by code | `verify/*.json` |

The **coordinator** (`coordinator/`) runs the phases in order. From M2 on, results can send the run back:
- an experiment result may add or revise a hypothesis (4 → 3);
- a data problem found during exploration or an experiment reopens data preparation as a new child of the data stage (3/4 → 2).

The order is a playbook, not a state machine. Changing it does not change the packages.

## 3. Layers and dependencies

```text
cli ──► coordinator ──► understand · ground · discover · communicate · (verify)
                               │
                               ▼
                           treesearch ──► harness ──► llm (Bedrock) · interpreter (subprocess) · store · journal · budget · config
```

- `harness` depends on nothing else in Popper. It holds no research logic.
- `treesearch` is the generic stage engine (§5). It depends only on `harness`. It knows nodes, steps and scoring, but no stage goals.
- Function packages depend only on `harness` and `treesearch`. They never import each other, and results pass between them as files in the run directory.
- Default run configuration ships inside the package (`src/popper/harness/default_config.yaml`). A user file passed with `--config` overrides it key by key, and the `POPPER_MODEL` environment variable, when set, overrides every model role.
- `coordinator` wires the functions together and is the only package that knows the playbook.
- Prompts live next to the code that uses them (`<package>/prompts/*.md`) and are loaded as text.

## 4. Run directory (state)

A run is a folder. There is no database. Files are written once. A change creates a new file or a new node, never an edit.

```text
runs/<run_id>/
  run.json                 config snapshot (no secrets), inputs, status, cost
  journal.jsonl            append-only: every model call, script execution, stage transition, error
  brief.md                 input brief (copied)
  data/raw.csv             input data (copied); data/holdout.csv only when --holdout (M6)
  understand/profile.json  structural profile of the raw data
  understand/framing.json  problem restatement, questions, needed variables, directions
  hypotheses.json          from exploration: hypotheses with planned experiments and source nodes
  tree/<stage>/<node_id>/  stages: data, explore, baseline, main, robustness
    code.py                the script as run
    meta.json              parent, kind (draft|debug|improve|robustness), status (ok|buggy), score, timings
    stdout.txt  stderr.txt
    results.json           values the script chose to report: {name: {value, ci?, n?, note?}}
    figures/*.png
    analysis.md            model's reading of the outputs and figures
  data/processed.parquet   written by the best data-prep node
  memory.md                running summary citing node ids (M2)
  report/paper.tex  report/paper.pdf  report/review.json
```

The run directory is the Research Graph of v2. Nodes link to their parents through `meta.json`, results link to the node that produced them, and figures link to the code that drew them. Persistence beyond files (SQLite and similar) waits until resume or multi-run work needs it.

## 5. Discover: staged tree search

The engine adapts the AI Scientist-v2 `bfts` loop.

**Node.** One self-contained Python script. It reads the stage input (`data/raw.csv` for data prep, `data/processed.parquet` afterwards), writes `results.json` and figures into its own folder, and prints a short log. Each node runs in a fresh subprocess with a timeout, so there is no hidden state and every node can be re-run.

**Step.** Each step creates one node:

1. If the stage has fewer than `num_drafts` root nodes, **draft** a new approach.
2. Otherwise, with probability `debug_prob`, pick a buggy leaf whose debug depth is below `max_debug_depth` and **debug** it.
3. Otherwise, pick the best working node and **improve** it (in stage 4: add a **robustness** child).

After a node runs, code checks it first. A non-zero exit, a timeout, a missing required output or an invalid `results.json` makes the node `buggy` without a model call. Otherwise the feedback model reads the code, output and results. It can still mark the node `buggy` (for nonsensical values), writes `analysis.md`, gives a 1–10 score against the stage goal, and says whether the goal is met. The best node of a stage is the highest-scoring `ok` node; ties go to the earlier node.

Scripts receive their inputs through environment variables (`POPPER_INPUT_<NAME>`, absolute paths) and write outputs to their working directory. `results.json` maps snake_case names to `{"value": number | string, "ci": [low, high]?, "n": int?, "note": str?}`.

**Stages.** The same engine runs every tree stage; only the goal, the input and the required outputs change. The best node of one stage seeds the next.

| Stage | Phase | Goal | Input | Required outputs |
|---|---|---|---|---|
| `data` | Data | Clean, validate and derive variables; document every change and the rows it affected | `raw.csv`, framing | `processed.parquet`, before/after table in `results.json` |
| `explore` | Exploration & hypothesis | Describe distributions, relations and group differences relevant to the questions; flag surprises | `processed.parquet`, framing | Figures and observations in `results.json`. Afterwards, a separate model step turns these into `hypotheses.json` |
| `baseline` | Experiment | A simple, transparent model or test for the hypothesis | processed data, hypothesis | Key estimate with interval, figure |
| `main` | Experiment | The planned analysis, plus follow-ups the results call for | best baseline node | Estimates with intervals, figures, the interpretation |
| `robustness` | Experiment | Sensitivity to cleaning choices, alternative specifications, subgroups, bootstrap (Sakana's ablation stage) | best main node | Stability of the main estimates |

A stage ends when it reaches `steps_per_stage`, or earlier when the feedback model judges the stage goal met by an `ok` node. M0 runs `data`, `explore` and one combined `experiment` stage. M1 splits `experiment` into `baseline` → `main` → `robustness`.

## 6. Communicate

1. **Collect.** Gather the framing, the data report, the exploration figures, the hypotheses, and the best experiment nodes' results and figures.
2. **Write.** The writeup model fills a fixed LaTeX template section by section, following the phases: abstract, introduction (framing), data, exploration, hypotheses, methods, results, robustness, limitations. Numbers are written as `\R{name}`, and figures are referenced by file name.
3. **Render.** The `\R{}` macros are generated from `results.json`. A reference to an unknown name produces a warning and a visible `??` in the PDF; it does not fail the build.
4. **Check** (M3). The vision model reads each figure with its caption. The writer revises one round, and the LLM reviewer writes `review.json`.
5. **Appendix.** Generated automatically: the data-prep changes, the experiment tree summary, the code of the reported nodes, and the label `exploratory, autonomously generated`.

If tectonic is not installed, the run still writes `paper.tex` and prints how to compile it.

## 7. Always-on rules (pilot strength)

| Rule | How the code keeps it |
|---|---|
| Every execution is recorded | `interpreter` writes the code, output, exit status and duration of every node; `journal` records every model call with its token cost |
| History is appended | Node folders and journal lines are write-once; a fix is a new child node |
| Labels are computed | The report template prints the label from the run's production path; no prompt can change it |
| Numbers resolve to artifacts | `\R{}` macros come from `results.json`; unknown names produce warnings (they become errors only once M4 shows the warnings are rare) |
| Secrets stay out of runs | `run.json` stores the config without credentials; scripts get no AWS variables in their environment |

Accepted pilot limitations: scripts run as local subprocesses without a container or network isolation, and the model sees row-level data samples. Both are acceptable for one researcher running their own data on their own machine. Containers come before the system is shared (M7).

## 8. Verify (optional, M6)

Verify is one package with exactly two touch points on the rest of the system:

1. `--holdout FRACTION` splits the rows at run start. `data/holdout.csv` is never passed to a node.
2. `popper verify <run> <result_name>` re-runs the stage-3 node that produced the result once, unchanged, on the holdout, compares the estimate with a margin fixed before the run, and writes `verify/<result_name>.json` with the outcome label `confirmed`, `not_confirmed` or `inconclusive`.

No other package knows about exposure, reservations or error budgets. Results from runs without a holdout cannot be confirmed on their own data; confirming them needs new data.

## 9. Deliberately deferred

The following are left out until evaluations show a need (see [ROADMAP.md](ROADMAP.md) M7): parallel workers, literature search and citations (OpenAlex), resume after crash, container sandbox, multiple datasets and joins, web UI and API, research programs across runs, domain packs, disclosure control, decision layer (Jev), and formal error control.

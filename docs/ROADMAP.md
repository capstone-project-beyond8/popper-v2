# Roadmap

Every milestone ends at a **demo gate**: one command that a person can run, producing output they can read. Each milestone also has a **size cap** on `src/` lines (counted by `wc -l` over `src/popper/**/*.py`, prompts and templates excluded). Going over the cap stops work for a review; the cap is never raised quietly. Design context lives in [ARCHITECTURE.md](ARCHITECTURE.md).

## Overview

| Milestone | Theme | Demo gate | Cap | Status |
|---|---|---|---|---|
| M0 | Mini scientist, end to end | `popper run examples/student_performance` → a paper with framing, data changes, exploration figures, one hypothesis and a tested result | 1,800 | todo |
| M1 | Full experiment stages, figure feedback, decision layer | The paper has baseline, main and robustness results with a stability label; the judge reads figures; node decisions are recorded in shadow | 2,500 | todo |
| M2 | Science loop (PI agent, Critic) | Several critiqued hypotheses; the researcher picks; a second round builds on the first; a data problem found later reopens the data stage | 3,200 | todo |
| M3 | Write-up and review | Compiles without manual fixes on three datasets; `review.json` and `tree.html` | 3,600 | todo |
| M4 | Evaluation | Table over planted, null and reference suites and configurations; Judge questions: decision model vs Judge on checked disagreements | + `evals/` | todo |
| M5 | Literature | Framing, hypotheses and paper cite real prior work | 4,100 | todo |
| M6 | Verify (optional) | `popper verify <run> <result>` → a confirmed or not-confirmed outcome on held-out rows | 4,600 | todo |
| M7 | Evidence-led extensions | Only what M4 shows is needed | — | — |

## How each phase grows

| Phase | M0 | M1 | M2 | M3 | M5 | M6 |
|---|---|---|---|---|---|---|
| **Ideation & framing** | Profile + framing with one reflection | — | Researcher confirms or edits the framing | — | Literature search shapes questions and directions | — |
| **Data** | Agentic `data` stage; `processed.parquet` + `changes.json` | Before/after figures; checks on derived variables | Reopened as a new child when a later phase finds a data problem | — | — | Holdout split before any node reads data |
| **Exploration & hypothesis** | Agentic `explore` stage; one hypothesis | Figures judged by the vision model | 3–5 hypotheses with reflection; the researcher picks; hypotheses revised from results | — | Hypotheses related to prior work | — |
| **Experiment** | One combined agentic stage | `baseline` → `main` → `robustness`; replication by resampling | Several hypotheses, one tree each; results feed memory | — | — | Frozen re-run on the holdout |
| **Publication** | Template paper, `\R{}` numbers, fixed label | Robustness section | Several hypotheses, rounds and steering history | Writer reflection, figure/caption check, Critic rubric review, `tree.html` | Related work and citations | Confirmed/not-confirmed labels |
| **Harness** | Agent loop, node tools, context assembly with untrusted wrapping, retry, failure classes, progress, journal, budget | Vision in the Judge | PI tools, `memory.md` in context, human-input tool, per-phase budgets | — | `search_literature` tool | `verify` package |
| **Agent team** | PI (fixed playbook), Theorist, Analyst, Judge, Writer | Judge reads figures | PI becomes an agent; Critic | Critic reviews the paper | Literature for Theorist and Writer | — |
| **Decision layer** | Judge gives typed answers | Second answerer (Jev) in `shadow`, disagreements journaled | `hypothesis_rank` in `shadow` | — | — | — |

---

## M0 — Mini scientist, end to end

**Goal:** one complete pass, rough but real, through all five phases. Each tree node is an agent with tools.

### Agent team
PI (fixed playbook), Theorist (framing and hypotheses), Analyst (node agent), Judge and Writer, each in its own session with its own tools (ARCHITECTURE §6).

### Harness (runtime)
- **config**: package default `src/popper/harness/default_config.yaml`, then a `--config` file key by key, then the `POPPER_MODEL` environment variable for every role.
- **llm**: Bedrock Converse with text, images and tool use, plus token and cost accounting.
  - Retry with exponential backoff (up to 5 attempts) on throttling, timeouts and 5xx; other errors are not retried.
  - Retries are journaled and are not research steps.
  - `FakeLLM` replays scripted text and tool calls for tests.
- **agent loop**: `agent_loop(role, system, task, tools, max_turns)`.
  - Tools are registered with a JSON schema and a handler.
  - Every tool call and result is journaled.
  - The loop ends when the agent calls `submit`, or when it reaches `max_turns` (the node is then `buggy`).
- **interpreter**: runs a script in a subprocess with a timeout. Credentials are stripped from the environment, and inputs are passed as `POPPER_INPUT_<NAME>`.
- **store**: a write-once run directory.
- **journal**: append-only JSONL.
- **budget**: a USD cap checked before every model call.
- **context**: `harness/context.py` assembles each session's context from run files, with a character limit per part; brief, data strings and outputs are wrapped as untrusted.
- **failure classes**: technical (retried), research (buggy node), budget and terminal (stop with status) — ARCHITECTURE §7.6.
- **progress**: one terminal line per phase and per node (`[data] data-002 debug → ok score 7 · $0.41`); `--quiet` turns it off.

### Tree search (`treesearch/`)
- Draft, debug and improve steps as in ARCHITECTURE §5.2. Each step runs a **node agent** with these tools:

| Tool | Does |
|---|---|
| `inspect_data(name)` | Schema, head, describe and missing counts of an input |
| `run_python(code)` | Runs a scratch snippet in the node's `scratch/` folder and returns its output. Recorded, never a result |
| `view_figure(path)` | Sends a PNG to the model |
| `read_artifact(path)` | Reads files of the parent node or of earlier stages (`results.json`, `analysis.md`, `changes.json`, `framing.json`) |
| `submit(code)` | The final script. The harness re-runs it from scratch as the node, and only its outputs count |

- Code checks run before the feedback model is called (exit status, timeout, required outputs, `results.json` shape).
- The feedback model scores the node 1–10 and says whether the goal is met. The best node is the highest-scoring `ok` one.

### Phases
1. **Ideation & framing**: a structural profile, then `framing.json` (problem, questions, key variables, directions, data concerns) with one reflection round.
2. **Data**: the `data` stage writes `processed.parquet`, `changes.json` (step, rows affected, reason) and `rows_before`/`rows_after`.
3. **Exploration & hypothesis**: the `explore` stage (distributions, relations, groups, at least two figures), then one model step producing one hypothesis with planned experiments and its source node.
4. **Experiment**: one combined `experiment` stage testing the hypothesis, with estimates, intervals and n.
5. **Publication**:
   - fixed LaTeX template with sections following the phases;
   - `\R{stage.name}` numbers from `results.json`, with unknown names shown as `??` and warned about;
   - the fixed label `exploratory — autonomously generated`;
   - an appendix with the data changes and the reported code;
   - tectonic compile, falling back to `.tex` only.

### CLI
`popper run <example_dir | --brief B --data D> [--config C] [--runs-dir R] [--quiet]`

### Tests
- **Unit:** config merge; budget stop; JSON parse retry; model-call retry; tool-loop turn limit; node selection; `results.json` validation; number filling.
- **Integration:** the interpreter (timeout, credentials, inputs); one stage with scripted tool calls (bad replies, then recovery, then failure); one end-to-end run with `FakeLLM`.

### Exit criteria
- The real-model demo on `student_performance`:
  - reports the planted data issues it fixed (duplicates, `absent`, impossible values, income labels);
  - finds a positive effect of study hours;
  - has no `??`;
  - costs under $5 and takes under 45 minutes.
- The CI checks pass, and `src/` is ≤ 1,800 lines.

**Out:** split experiment stages, vision in feedback, several hypotheses, researcher input, loops back, Critic, `tree.html`, holdout.

---

## M1 — Full experiment stages and figure feedback

**Goal:** the experiment phase follows Sakana's stages, and figures are judged, not just drawn.

- **Stages**: `baseline` → `main` → `robustness`. The best node of each seeds the next, and each stage has its own goal and required outputs (ARCHITECTURE §5.4).
- **Stage end**: `steps_per_stage` is reached, or an `ok` node meets the goal. A per-stage override for `steps_per_stage` is added to the config.
- **Robustness as a multiverse** (ARCHITECTURE §5.5):
  - variants over the cleaning choices recorded in `changes.json`, alternative specifications, subgroups and resampling, each re-estimating the main effect;
  - at least one adversarial check (placebo outcome, negative control or permutation);
  - a specification-curve figure of the estimates across variants.
- **Figure feedback**: the feedback model receives the node's figures as images. A misleading or unreadable figure lowers the score, and the reason goes into `analysis.md`.
- **Data**: before/after distribution figures for changed columns, and checks that derived variables have plausible ranges.
- **Stability label**: computed by code from the robustness outputs (`stable` or `fragile`, ARCHITECTURE §5.5) and printed beside the result.
- **Diverse drafts**: each draft sees summaries of the earlier drafts and must take a different approach.
- **Decision layer**:
  - `harness/decisions.py` defines the typed questions, the `Answerer` interface and the modes (off, shadow, on);
  - the Jev adapter (optional dependency; its key lives in `.env`) answers `node_buggy`, `goal_met` and `node_score` in `shadow` beside the Judge;
  - every disagreement is journaled with both answers and the facts they saw;
  - without a key, every question stays `off`.
- **Publication**: a robustness section and a table of the main estimate across specifications.
- **Tests:**
  - stage chaining (seed code passed on) with `FakeLLM`;
  - the feedback prompt receives images when figures exist.
  - the stability label on fixture variants;
  - a decision in shadow records both answers and keeps the rule result; an unavailable provider falls back.
- **Exit:**
  - the demo paper shows the study-hours estimate under at least three specifications;
  - a fixture figure with unlabeled axes gets a lower score than a good one.

**Out:** several hypotheses, researcher input, loops back.

---

## M2 — Science loop (PI agent)

**Goal:** results change what the run does next. The PI becomes an agent that uses the same tool loop.

- **PI tools:**
  - `run_stage(stage, goal_note)`;
  - `propose_hypotheses(n)`;
  - `revise_hypothesis(id, reason)`;
  - `reopen_data(issue)`, which starts a new `data` node whose parent is the previous best;
  - `ask_researcher(question, options)`;
  - `update_memory(text)`;
  - `finish(reason)`.
- **Playbook**: the five phases stay the default order, stated in the PI prompt. The PI may loop back with a recorded reason. Per-phase and total budgets bound the loop.
- **Hypotheses**: 3–5 from exploration with one reflection round, each with a rationale, planned experiments and source nodes. Each chosen hypothesis gets its own experiment trees.
- **Critic**: a separate session critiques each hypothesis before the choice, and each main result before publication (confounders, alternative explanations, claims beyond the design). The critique is written to `critiques/` as an assessment. It can prompt a robustness child or a limitation, but never changes a result.
- **Decisions**: `hypothesis_rank` in `shadow`; the PI's ranking is the reference, and disagreements are journaled.
- **Researcher input**: `ask_researcher` on the CLI (choose, edit, or add a note). `--auto` lets the PI pick. Every choice is labelled `researcher_steered` or `agent_supplied`.
- **Working memory**: `memory.md`, updated after each stage. Each entry cites node ids, and it is read by the PI and by node agents (`read_artifact`).
- **Publication**: one results subsection per tested hypothesis, plus a "research path" section generated from the journal (what was tried, why it changed).
- **Tests:**
  - a scripted PI run with a reopen and a revision;
  - `--auto` makes no input calls.
- **Exit:**
  - on a fixture dataset with a data issue that only shows during experiments (a unit mismatch in one school), the run reopens the data stage and the paper reports it;
  - a second-round hypothesis cites first-round results.

**Out:** parallel trees, literature.

---

## M3 — Write-up and review

**Goal:** the paper is readable and checked the way Sakana's write-up is.

- **Figure aggregation**: one final plotting script per paper, run from the best nodes' saved outputs, producing consistent publication figures.
- **Writer reflection**: compile errors and LaTeX warnings are fed back for up to three rounds. Section completeness is checked.
- **Figure and caption check**: the vision model reads each figure with its caption and flags mismatches.
- **Number audit**: every number in the prose that did not come from `\R{}` is listed as a warning in `review.json`.
- **Consistency checks**: simple relations among reported values (means with sample sizes, tests with their statistics) are recomputed, and mismatches are listed in `review.json`.
- **Claims file**: a structured file beside the PDF lists each claim with the named results, nodes and label it rests on.
- **Disclosure**: the paper states that it was generated by an AI system.
- **Critic rubric review** (separate session): the Critic scores the draft on a fixed rubric (soundness, clarity, limitations, faithfulness to results) and writes `review.json`; the Writer revises once from it.
- **`tree.html`**: a static page of the experiment trees, showing each node's code, output, figures, score and kind.
- **Tests:**
  - the number audit on a fixture text;
  - `tree.html` renders from a fixture run directory;
  - consistency checks flag a fixture with a mismatched mean and pass a correct one.
- **Exit:** on three datasets, the PDF compiles without manual fixes, `review.json` is written, and the audit reports at most 2 untraced numbers per paper.

---

## M4 — Evaluation

**Goal:** measure what helps before adding anything else.

- **Suites** (in `evals/`):
  - **planted**: 3 synthetic datasets with known effects and data issues, of different kinds (grouped, time-ordered, nonlinear);
  - **null**: 2 synthetic datasets with no real effect;
  - **reference**: 1–2 public datasets with well-known findings, plus a few BLADE or DiscoveryBench tasks; public data also run on perturbed copies to expose memorization.
- **Metrics:**
  - planted-effect recovery (direction, and magnitude within a band);
  - on null data, the share of runs that report a finding as if it held, and whether it is labelled `fragile`;
  - data-issue fix rate;
  - share of numbers traced to `\R{}`, and consistency warnings;
  - draft diversity;
  - Critic rubric score;
  - cost, wall time and failure rate.
- **Comparisons** at equal model and budget:
  - agentic nodes vs single-shot nodes;
  - `num_drafts` 1 vs 3;
  - vision feedback on vs off;
  - PI agent vs fixed playbook;
  - Critic on vs off;
  - multiverse robustness vs a single robustness check;
  - diverse drafts vs free drafts;
  - each Judge question: the decision model vs the LLM Judge on a hand-checked sample of shadow disagreements (agreement, calibration, cost); a question goes `on` only when the decision model matches or beats the Judge.
- **Decisions**: each comparison ends in a short record in `evals/decisions.md`: what changed, the result, and the default kept.
- **Exit:** the table is generated by one command (`popper-eval`), and the defaults in `default_config.yaml` follow the decisions.

---

## M5 — Literature

- **Tool**: `search_literature(query)` over OpenAlex, returning metadata and abstracts. It is available to the framing, hypothesis and writer agents.
- Framing records related work. Hypotheses note whether they replicate, extend or contradict prior findings; this is "coverage", never a novelty claim.
- **Paper**: a related-work section and BibTeX citations. Every citation resolves to a fetched record.
- **Exit:** the demo paper cites at least five resolved works, with no unresolved citation keys.

---

## M6 — Verify (optional)

- `popper run --holdout 0.2` splits rows (grouped by an id column when given) before any node reads data. `data/holdout.csv` is never passed to a node.
- `popper verify <run> <result>`:
  1. freezes the processed-data script and the experiment script that produced the result;
  2. records a margin chosen before the look;
  3. runs both once on the holdout;
  4. computes `confirmed`, `not_confirmed` or `inconclusive` in code.
- The paper is regenerated with the new label on that result, and nothing else changes.
- **Tests:**
  - the holdout never reaches a node;
  - a failed verify run is `inconclusive` and cannot be re-run.
- **Exit:** on the demo dataset, the study-hours effect is confirmed on the holdout.

---

## M7 — Evidence-led extensions

Candidates, each adopted only when M4 shows the need:
- parallel workers per stage;
- container sandbox (required before shared use);
- resume after crash;
- multiple datasets and joins;
- web UI and API;
- runs across programs.

---

## Rules for every milestone

- Update the Status column and ARCHITECTURE.md in the same change that finishes a milestone. ARCHITECTURE.md describes built behaviour. Plans live in `docs/specs/` and are removed once done.
- A mechanism added after M4 names the failure it fixes and its result on the evaluation set.

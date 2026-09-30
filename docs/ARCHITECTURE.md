# Popper Architecture

Popper is an AI scientist for quantitative tabular data. Given a research brief and a dataset, it frames the problem, prepares and explores the data, forms hypotheses from what it sees, tests them with analysis code it writes, runs and debugs itself, looks at its own figures, and writes the study up as a LaTeX paper. The researcher can choose, correct and redirect along the way.

![Popper architecture](images/architecture.svg)

This document is the target design and the rules the code keeps. [ROADMAP.md](ROADMAP.md) says what is built and in which order. Sources are numbered and listed in §15.

## 1. Design stance

Popper starts from one demonstrated system and adds only what the evidence says is missing.

- **The base is AI Scientist-v2** [1]. It runs ideation, a staged best-first tree search over experiment code, figure review by a vision model, a LaTeX write-up with reflection, and an automated reviewer. It is compact and produces a readable paper end to end. One of its three workshop submissions passed peer review [1].
- **Its documented weaknesses set the upgrades.**
  - An independent evaluation found that 42% of its experiments failed on coding errors, and that papers contained fabricated numbers, placeholder text, and old or wrong citations [3].
  - A 2026 survey of AI scientists finds that none of nine fully autonomous systems has externally validated verification, and that the bottleneck has moved "from task completion to claim verification" [18].
  - Other work shows that agents narrow exploration toward their starting literature [19], and that iterating code until a result looks publishable is not validation [17].
  - Systems run at scale report the same pattern. FARS produced 166 papers with "recurring failure modes: narrow experimental scope, methodological shortcomings, and integrity issues" [10]. ScientistTwo and Agents4Science rely on automated ablations and AI reviewers, whose judgments still need checking against the executed work [11, 12].
- **The domain changes the pipeline.** Tabular research starts from a given dataset, and different reasonable analyses of the same data disagree [21]. So Popper puts data work first and treats analytic choices as something to measure (§5).
- **Harness engineering decides the rest.** The loop, tools, context, sandbox, records and budgets follow published harness practice [31–37] (§7).

The result is AI Scientist-v2's shape with four upgrades:
1. every number is traced to the code that produced it;
2. robustness is a measured multiverse, not a single check;
3. critique tries to break results, not polish them;
4. a harness that records everything, so claims can be verified afterwards.

## 2. Principles

1. **Output first.** Every increment ends in a run that produces a paper someone can read. Infrastructure is added only when a run needs it.
2. **Reproduce, then improve.** A mechanism from a reference system is first reproduced as published. An addition is a hypothesis about Popper, tested at equal model and budget (§13). A reference system's success does not prove Popper's.
3. **Agents work, the harness records.** Agents use tools and write code. The harness runs the code, builds each agent's context and records every call as a side effect. Recording never asks an agent to declare anything.
4. **Workflow where the steps are known, agents where they are not.** The phase order and stage sequence are fixed code. Inside a node, an agent decides freely. This follows the split between workflows and agents in [31].
5. **Ground truth from execution.** A result is what a script produced when the harness re-ran it from scratch. What the agent said about it is not a result [31].
6. **Labels, not locks.** Every result says how it was produced. Everything outside Verify is `exploratory`. Labels are computed by code, and no model or reviewer can raise them.
7. **Numbers come from artifacts.** Every number in the paper is filled in from a result file written by executed code, never typed by a model [6].
8. **Try to break it.** Every main result gets robustness variants and at least one adversarial check before it is written up [17, 7].
9. **Executable rules over prose rules.** A rule that matters is enforced in code: a check, a label or a renderer. A prompt asks, and code makes sure [36, 37].
10. **Measured restriction.** A new gate, reviewer, rule or topology change needs a failure seen in real runs and a comparison on the evaluation suites. Without evidence, the simpler version stays. Extra reviewer agents and long hand-off chains have lowered success in practice [37].
11. **Append, never rewrite.** Run files are written once. A fix is a new node or a new assessment beside the old one.
12. **One owner per concept.** Each concept is defined in one module and one section of this document.

### 2.1 Always-on rules

These hold in every configuration and are enforced by code:

| Rule | How the code keeps it |
|---|---|
| Every execution is recorded | The harness journals every model call, tool call, execution and decision (§7.5) |
| History is appended | Run files are write-once; a fix is a new node or a new assessment (§9) |
| Labels are computed | `exploratory`, `stable`/`fragile` and `confirmed` come from code; the template prints them and no prompt can change them |
| Numbers resolve to artifacts | Paper numbers are filled in from results files; unknown names are flagged (§10) |
| Untrusted text is data | Brief, dataset strings, outputs and retrieved text are wrapped and never treated as instructions (§7.3) |
| Secrets stay out | The run folder holds no credentials; scripts get no credential variables (§7.4) |

## 3. Phases

A run passes through five phases. This is AI Scientist-v2's pipeline (ideation → experiments → write-up) with a data phase inserted, because the dataset exists before the question is refined.

| # | Phase | Function | Package | Does | Output |
|---|---|---|---|---|---|
| 1 | **Ideation & framing** | Understand | `understand/` | Read the brief and a structural profile of the data. Restate the problem, list research questions and the variables they need, sketch distinct directions. Self-reflection rounds | Framing |
| 2 | **Data** | Ground | `ground/` | Search stage: fix types, missing values, duplicates, impossible values and categories; derive the variables the questions need; record every change and the rows it affected | Clean dataset, change log |
| 3 | **Exploration & hypothesis** | Discover | `discover/` | Search stage of exploratory analysis. Observations become testable hypotheses, each with a planned test and the nodes it came from. The Critic challenges them, and the researcher (or the PI) chooses | Hypotheses |
| 4 | **Experiment** | Discover | `discover/` | Staged search per chosen hypothesis: baseline → main → robustness | Best nodes, estimates, figures, stability labels |
| 5 | **Publication** | Communicate | `communicate/` | Aggregate figures, write the paper, check numbers and figures, review, revise | Paper, claims file, review |
| — | *Verify (optional)* | Verify | `verify/` | Re-run a locked analysis once on held-back rows; the outcome is computed by code | Verification records |

The **PI** (package `coordinator/`) runs the phases. Its first form is a fixed playbook. Its agent form follows the same order by default, but can go back with a recorded reason:
- an experiment result may add or revise a hypothesis (4 → 3);
- a data problem found later reopens the data stage as a new child node (3/4 → 2).

A phase never edits another phase's output. Results pass between phases as files in the run directory.

## 4. Subsystems

| Subsystem | Package | Owns | Section |
|---|---|---|---|
| **Research phases** | `understand/`, `ground/`, `discover/`, `communicate/`, `verify/` | Goals, prompts and outputs of each phase | §3, §9, §11 |
| **Search engine** | `treesearch/` | Nodes, steps, checks, selection, stage sequence, the Analyst's tools | §5 |
| **Agent team** | role prompts in their phase packages; PI in `coordinator/` | Who does what, with which tools and model, in which session | §6 |
| **Harness** | `harness/` | Model access, agent loop and tool mechanism, context, sandbox, journal, run store, budgets, failures, config | §7 |
| **Decision layer** | `harness/` | Typed Judge answers, an optional second answerer, modes, disagreement records | §8 |
| **State and memory** | the run directory | Artifacts, assessments, working memory, attribution | §9 |
| **Knowledge** | `understand/` | Prior work for framing, hypotheses and related work | §12 |
| **Evaluation** | `evals/` | Suites, metrics, comparisons, adoption decisions | §13 |

```text
cli ──► coordinator ──► understand · ground · discover · communicate · (verify)
                               │
                               ▼
                           treesearch ──► harness
```

- `harness` imports nothing else in Popper and holds no research logic.
- `treesearch` imports only `harness`. It knows nodes, steps and scoring, but no stage goals.
- Phase packages import only `harness` and `treesearch`, and never each other.
- `coordinator` is the only package that knows the playbook.
- `evals/` may import anything, and production code never imports `evals/`.
- Prompts live next to the code that uses them (`<package>/prompts/`). Default configuration ships inside `harness/`. A `--config` file overrides it key by key, and `POPPER_MODEL` overrides every model route.

## 5. Search engine

The engine adapts AI Scientist-v2's best-first tree search [1], which itself follows AIDE's search over code [13]. One engine runs every search stage; only the goal, inputs and required outputs change.

### 5.1 Node

A node is one attempt at the stage goal.
- An **Analyst** agent (§6) builds it. The Analyst inspects the inputs, tries snippets, fixes errors, and then submits one self-contained script.
- The harness **re-runs the submitted script from scratch** in the sandbox. Only that run's outputs count: a results file, figures and a log. So a node has no hidden state and can always be re-run.
- The node records its parent, kind, status, score, debug depth and a one-line reason for existing.

In AI Scientist-v2 a node is one generated program. In Popper the Analyst can look at the data and test snippets before it commits. This targets the high share of runs that failed on coding errors [3], at the cost of more tokens per node, and the trade is measured (§13).

### 5.2 Step policy

Each step runs one Analyst, with a task set by the action:
1. If the stage has fewer than `num_drafts` first attempts, **draft** a new approach. A draft sees summaries of the earlier drafts and must take a different approach, because agents otherwise cluster near their starting point [19].
2. Otherwise, with probability `debug_prob`, pick a broken leaf below `max_debug_depth` and **debug** it.
3. Otherwise, **improve** the best working node.

The defaults are AI Scientist-v2's: 3 drafts, debug probability 0.5, debug depth 3 [1]. A stage ends when it reaches its step budget, when an `ok` node meets the goal, or when the best score stops improving.

### 5.3 Checks, then the Judge

1. **Code checks first.** A non-zero exit, a timeout, a missing required output, an invalid results file, or a value outside a declared range makes the node `buggy` without a model call. This is the programmatic gate between steps recommended in [31].
2. **Then the Judge** (§6) reads the code, output, results and figures in a separate session. It writes an analysis and gives typed answers (§8): is the node buggy, is the goal met, and a score.
3. **Best node.** The highest-scoring `ok` node wins, and ties go to the earlier node. The best node of one stage seeds the next.

Checks are tested both ways: they must fire on bad outputs and stay silent on good ones [37].

### 5.4 Stages

| Stage | Phase | Goal | Seeds from | Required outputs |
|---|---|---|---|---|
| `data` | Data | Clean, validate and derive variables; document every change and the rows it affected | raw data, framing | clean dataset, change log, row counts |
| `explore` | Exploration | Distributions, relations and group differences relevant to the questions; flag surprises | clean data | observations with figures |
| `baseline` | Experiment | A simple, transparent model or test for the hypothesis | clean data, hypothesis | key estimate with interval, figure |
| `main` | Experiment | The planned analysis, plus the follow-ups the results call for | best baseline | estimates with intervals, figures |
| `robustness` | Experiment | The multiverse of §5.5, plus adversarial checks | best main | the main estimate under every variant |

AI Scientist-v2's four stages (preliminary, tuning, agenda, ablation) map to baseline, main and robustness. Hyperparameter tuning has no direct counterpart in inferential work, and ablation becomes part of robustness. The first build may run one combined experiment stage.

### 5.5 Robustness as a multiverse

Different reasonable choices of cleaning, coding and specification can change the conclusion. Many analysts given one dataset reported odds ratios from 0.89 to 2.93 [21]. Popper therefore treats robustness as a small **multiverse** [22] instead of one extra check:

- **Variants.** The robustness stage enumerates reasonable alternatives:
  - data choices (exclusions, outlier rules, missing-value handling, variable codings);
  - model choices (covariate sets, functional forms, estimators);
  - resampling (bootstrap, subgroups).

  Each variant re-estimates the main effect.
- **Adversarial checks.** At least one variant tries to break the result [17, 7]:
  - a placebo outcome;
  - a negative-control exposure;
  - a permutation of the key variable;
  - a sensitivity bound for unmeasured confounding, such as the E-value [27].
- **Specification curve.** The paper shows the sorted estimates with their intervals across variants [23].
- **Stability label**, computed by code: `stable` when the estimate keeps its sign and its interval excludes zero in at least 80% of the variants, and no adversarial check fails; otherwise `fragile`. The label is printed next to the result, and no model sets it.

### 5.6 Analysis practice

The Analyst and Critic prompts carry a short checklist, drawn from research-methodology practice [24, 26, 28]:
- justify a processing choice by validity, never by the relation it produces;
- flag a derived variable that uses the outcome;
- report every rule that drops rows;
- prefer effect sizes with intervals over p-values alone;
- keep association distinct from causation in an observational design.

The checklist asks in prose. Code checks and labels are what enforce it.

## 6. Agent team

A **role** is a prompt, a tool set and a model route. A role gets its own session only for one of two reasons:
- it needs **different tools**;
- it needs an **independent context**, so that it judges work without inheriting the author's reasoning.

| Role | Does | Tools | Why a separate session |
|---|---|---|---|
| **PI** | Runs the phases. In agent form, chooses next work from results and memory, goes back when needed, and asks the researcher | Playbook first; later stage, hypothesis, memory and ask-researcher tools | The only role that writes run-level files |
| **Theorist** | Framing with self-reflection; turns exploration results into hypotheses with planned tests | read artifacts; literature search | Reasons over artifacts and needs no code tools |
| **Analyst** | Builds one node: inspects, tries, submits a script | inspect data, run snippet, view figure, read artifact, submit | The only role that runs code |
| **Judge** | Reads one node and scores it with typed answers | none; context only | Scores work it did not write |
| **Critic** | Tries to break hypotheses and main results (confounders, alternative explanations, claims beyond the design), proposes adversarial checks, and reviews the draft paper against a rubric | read artifacts, view figures | Must not share the author's context |
| **Writer** | Writes the paper from artifacts and revises from checks and critique | read artifacts, view figures; literature search | Long-form output with its own template |

**Topology.** One run has one PI, which starts role sessions one at a time and waits for their artifacts.
- A node involves at most two hand-offs (Analyst → Judge), well below the chain length where multi-agent systems start to fail [37].
- Roles never write each other's outputs.
- Multi-agent systems use about 15 times the tokens of a chat [35]. So parallel Analysts per stage (AI Scientist-v2 runs four [1]) and hypothesis tournaments [4] are measured challengers, not defaults. The same holds for richer PI designs, such as hierarchical task graphs [14] or paired literature and analysis agents [9].

**Researcher.** The researcher can pick hypotheses, edit framing and add notes. Every choice records who supplied it (`agent` or `researcher`), and researcher choices appear in the paper as `researcher_steered`. Human input at each stage improved output quality in Agent Laboratory [8] and data-to-paper [6].

## 7. Harness

The harness is the environment every agent works in. Its job is to make free agent work **recorded, bounded and recoverable** without steering the research. It holds no research logic.

### 7.1 Agent loop

A session is a tool-use loop on the configured model.
- A tool is a name, a JSON schema and a handler. The handler returns text or an image.
- The loop ends when the agent calls its terminal tool (submit, finish or answer) or reaches its turn limit.
- Transient provider errors (throttling, timeouts, 5xx) are retried with backoff inside the model client and journaled. They are never research steps.

### 7.2 Tools

The tool set is small and consolidated, following [33]:

| Tool | Does | Limits |
|---|---|---|
| inspect data | Schema, head, summary and missing counts of a stage input | Stage inputs only |
| run snippet | Runs scratch code in the node's scratch folder and returns its output | Same sandbox as nodes; recorded, never a result |
| view figure | Sends a figure to the model | Run directory only |
| read artifact | Reads results, analyses, change logs, framing, hypotheses, memory | Run directory only; no raw rows beyond inspect data |
| submit | Terminal: the script the harness runs as the node | One per Analyst session |
| literature search | Metadata and abstracts of prior work | Concepts only, never data values |

Tool design rules:
- errors say what went wrong and what to try next;
- long outputs are truncated with a hint on how to narrow them;
- paths are absolute;
- every tool writes only inside the calling node's folder [33].

### 7.3 Context engineering

Each session's context is built fresh from the run directory, never carried over from another session's conversation [32].
- **Just in time.** The context lists artifacts by name, and the agent reads what it needs through tools, instead of receiving everything up front.
- **Structured notes.** Working memory (§9) is a file of short entries that cite node ids. It persists across sessions [32], as in Kosmos's shared world model [5].
- **Condensed hand-offs.** The Judge's analysis is short, and it is what the next Analyst sees of its parent, not the parent's whole session.
- **Budgets per part.** Each context part has a size limit. Truncation keeps the tail of logs and the head of files. Long Analyst sessions are compacted, keeping decisions and open errors.
- **Untrusted content.** Brief text, dataset strings, script output and retrieved text are wrapped and marked as untrusted, and every system prompt states that they are data, never instructions.

### 7.4 Sandbox

Each script runs in a fresh subprocess with the node folder as working directory and a time limit. Credentials are stripped from its environment, and inputs arrive as absolute paths in environment variables. The first form has no container or network isolation, which is acceptable for one researcher running their own data locally. Container isolation comes before shared use, as in Kosmos's managed sandboxes [5].

### 7.5 Recording and run store

- **Journal.** Every model call (role, tokens, cost), tool call (arguments, truncated result), script execution (code hash, exit, duration), decision (§8) and phase event is appended to one journal. Recording is a side effect of the harness, never a duty of the agent.
- **Run store.** One folder per run, with files written once (§9). The run's status file holds a configuration snapshot without secrets.
- **Release by default.** Code, outputs, seeds and the journal stay in the run folder, so a run ships its own execution trace. Most AI scientists do not release traces [18].

### 7.6 Budgets and failures

Budgets:
- *Resource budgets* (money, turns per session, steps per stage) end work safely and are shown as progress.
- *Search budgets* (drafts, debug depth) are soft task structure.
- *Error budgets* exist only inside Verify.

| Failure class | Example | Handling |
|---|---|---|
| Technical | throttling, timeout, 5xx | Retry with backoff; journaled; not a research step |
| Research | script error, missing output, no submit | The node becomes `buggy` and informs the next step |
| Budget | money cap reached | Stop cleanly; the run status says `budget_exceeded` |
| Terminal | a stage with no working node | Stop cleanly; the run status names the stage |

No failure path edits a recorded artifact. Resuming after a crash restarts from the last completed node, using the run folder and journal as the progress record [34].

### 7.7 Progress

One terminal line per phase and per node, for example `[data] data-002 debug → ok score 7 · $0.41`. A quiet flag turns it off.

## 8. Decision layer

The Judge's verdict is a **typed answer**, not free text:

| Question | Asked by | Type |
|---|---|---|
| `node_buggy` | Judge | yes/no |
| `goal_met` | Judge | yes/no |
| `node_score` | Judge | 1–10 |
| `hypothesis_rank` | PI (agent form) | score per option |

Code reads these fields, and the prose goes to the node's analysis.

Because the answers are typed, **any answerer can fill them**: the LLM Judge, which is the default and the reference, or a decision model. TypeSafe Jev (System One) returns typed choices, yes/no probabilities and scores with a confidence [38]. Adopting a decision model changes no interface.

- **Modes per question:**
  - `off`: only the Judge answers;
  - `shadow`: both answer, and the Judge's answer is used;
  - `on`: the decision model's answer is used when its confidence clears a threshold, otherwise the Judge's.
- **Disagreements become evaluation data.** In `shadow`, each run journals both answers and the facts they saw. Evaluation checks a sample of disagreements by hand and computes agreement, calibration and cost per question. A question goes `on` only if the decision model matches or beats the Judge.
- **Limits:**
  - a decision picks among given options or scores given facts;
  - it never writes code or prose;
  - it never computes a number that code can compute;
  - it never overrides a code check or a label.
- **Fallback.** An unavailable provider or a malformed answer falls back to the Judge's answer, and the reason is journaled. Popper works fully without a decision model.

## 9. State and memory

A run is a folder. There is no database. Files are written once, and a change creates a new file or a new node, never an edit.

```text
runs/<run_id>/
  run.json                 configuration snapshot (no secrets), inputs, status, cost
  journal.jsonl            append-only record of calls, executions, decisions and events
  brief.md, data/          inputs (copied); held-back rows only when Verify is requested
  understand/              data profile, framing
  hypotheses.json          hypotheses with planned tests, source nodes, supplied_by
  tree/<stage>/<node_id>/  code, log, results, figures, node metadata, the Judge's analysis
  memory.md                working memory citing node ids
  critiques/               Critic assessments citing node ids
  report/                  paper source and PDF, claims file, review, build log
```

Three kinds of content:

| Kind | Examples | Changes by |
|---|---|---|
| **Source artifact** | data versions, code, results, figures, logs | Never edited; a new node or version |
| **Assessment** | Judge analyses, critiques, figure reviews, the paper review, decisions | A new attributed assessment beside the old one |
| **Working memory** | memory entries | New entries appended by the PI, each citing artifacts |

An assessment or memory entry cites the artifacts it rests on, so a wrong interpretation is corrected by a new assessment without touching the execution it interprets.

**Node kinds:** `draft`, `debug`, `improve`, `variant` and `adversarial`. Each child records a one-line reason, so a reader sees why it exists.

## 10. Publication

1. **Collect** the framing, data changes, exploration figures, hypotheses, best nodes, specification curves and stability labels.
2. **Aggregate figures** in one plotting script run over the best nodes' saved outputs, so figures share a style and trace to code [1].
3. **Write.** The Writer fills a fixed LaTeX template section by section: abstract, introduction, data, exploration, hypotheses, methods, results, robustness, limitations. It follows the observational reporting items of STROBE where they apply [28]. Numbers are written as references to named results, never as literals.
4. **Render.** Named results are filled in from the results files [6]. An unknown name renders as `??` and produces a warning.
5. **Check:**
   - build errors are fed back to the Writer for a few rounds [1];
   - the vision model checks each figure against its caption [1];
   - the number audit lists every number in the prose that did not come from a named result;
   - consistency checks recompute simple relations among reported values, such as means with sample sizes and tests with their statistics, in the spirit of GRIM and statcheck [29, 30];
   - the Critic gives a rubric review, and the Writer revises once. AI Scientist's reviewer uses a rubric with reflection and an ensemble [2].
6. **Claims file.** Beside the PDF, a small structured file lists each claim with the named results, nodes and label it rests on. A reader or a weaker model can check claims without parsing the PDF [20].
7. **Claim language.** Negative and inconclusive results are reported with the same standing as positive ones. An observational design is described as association. A `fragile` result is described as fragile.
8. **Appendix**, generated by code: data changes, a summary of the search tree, the code of reported nodes, researcher-steered choices and the labels.
9. **Disclosure.** The paper states that it was generated by an AI system.

The LaTeX source is compiled with the first engine found (`tectonic`, `latexmk`, then `pdflatex`). With no engine, the run still writes the source, and the PDF can be built later.

## 11. Verify (optional)

Verify is one package with two touch points on the rest of the system:
1. **Hold data back.** At run start, a fraction of rows is set aside, grouped by an id column when given. These rows never reach a node or a tool.
2. **Verify a result:**
   1. lock the data script and the analysis script that produced the result, and record a margin chosen before looking;
   2. run both once on the held-back rows;
   3. compute `confirmed`, `not_confirmed` or `inconclusive` in code. A failed run is `inconclusive` and is not re-run.

Repeated adaptive looks at a holdout erode its validity [25], and sequential falsification needs stated assumptions [7]. So Verify allows one look per result, and its contract is strict when used: locked before looking, run once, outcome computed by code. No other package knows about exposure or error budgets.

## 12. Knowledge

Literature search returns metadata and abstracts of prior work for the Theorist and Writer.
- Queries carry concepts, never data values.
- Prior work shapes directions and related work. It is never evidence for this run's results.
- Hypotheses record whether they replicate, extend or contradict prior findings. This describes search coverage, never a novelty claim. AI Scientist's novelty checks misjudged established ideas as new [3].
- Citations come from retrieved records only. A reference that was not retrieved is not cited.

## 13. Evaluation

`evals/` runs Popper on suites and compares configurations at equal model and budget.

| Suite | Contains | Measures |
|---|---|---|
| **Planted** | Synthetic data with known effects and planted data issues | Effect recovery (direction and magnitude), data-issue fix rate |
| **Null** | Synthetic data with no real effect | How often an exploratory result is written as a finding, and whether it is labelled `fragile` |
| **Reference** | Public datasets with known findings, and BLADE and DiscoveryBench tasks [15, 16] | Agreement with expert analyses and known findings |

- **Every run reports:** node failure rate, share of numbers traced, audit and consistency warnings, Critic rubric score, draft diversity, cost and wall time.
- **Comparisons:**
  - agentic nodes vs single-shot nodes;
  - one draft vs three, and diverse drafts vs free drafts;
  - vision feedback on vs off;
  - PI agent vs fixed playbook;
  - Critic on vs off;
  - multiverse robustness vs a single robustness check;
  - for each Judge question, the decision model vs the LLM Judge, on disagreements collected in shadow.
- **Decisions.** Each comparison ends in a record in `evals/decisions.md` (what changed, the result, the default kept). Evaluation never changes a run's results.
- **Contamination.** Suites built on public data also run on perturbed copies. A gap between the original and the perturbed copy is reported as memorization, not capability.

## 14. Positioning

What Popper reproduces from each system, what it changes, and the evidence behind the change. Every change is a claim to test (§13), not an assumed gain.

| System | Reproduced | Popper's change | Evidence for the change |
|---|---|---|---|
| **AI Scientist-v2** [1] | Staged best-first tree search, debug limits, figure review by a vision model, LaTeX write-up with reflection, automated review | Data phase first; nodes built by a tool-using agent; code checks before the Judge; numbers traced; multiverse robustness; computed labels; optional Verify | Coding failures, fabricated numbers and weak citations [3]; the verification gap [18] |
| **AIDE** [13] | Tree search over code with draft, debug and improve | Inferential goals and scientific checks in place of a leaderboard metric | Tabular science has no single score to optimize [15] |
| **Co-Scientist** [4] | Generate, critique and rank hypotheses; researcher steering | Hypotheses grounded in explored data and tested in the same run; typed ranking | Ideas drift toward the starting literature [19] |
| **Kosmos** [5] | A shared world model that shapes the next task; sandboxed code agents | Memory entries cite node ids; every attempt stays re-runnable | 79.4% of Kosmos statements were supported; traceability helps checking but does not validate interpretation [5] |
| **data-to-paper** [6] | Numbers traced from code into the paper | Tracing covers the whole run, plus a claims file [20] | Human co-piloting is needed as complexity grows [6] |
| **POPPER** [7] | Falsification tests of measurable implications | Adversarial checks in robustness; strict one-look Verify | Iterating until publishable is not validation [17] |
| **Many-analysts, multiverse and specification-curve work** [21–23] | Enumerating reasonable analyses | The robustness stage and the stability label | Analytic choice changes conclusions [21] |

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
15. Gu, K., et al. (2024). [BLADE: benchmarking language model agents for data-driven science](https://arxiv.org/abs/2408.09667). *EMNLP Findings*.
16. Majumder, B. P., et al. (2025). [DiscoveryBench: towards data-driven discovery with large language models](https://proceedings.iclr.cc/paper_files/paper/2025/file/0d70af566e69f1dfb687791ecf955e28-Paper-Conference.pdf). *ICLR*.

**Critiques of AI scientists**

17. Fa, D., & Culjak, M. (2026). [Sound agentic science requires adversarial experiments](https://arxiv.org/abs/2604.22080). arXiv.
18. Ding, T., et al. (2026). [Autonomous research agents: a survey of AI scientists and the verification gap](https://arxiv.org/abs/2608.05179). arXiv.
19. Tang, Y., & Yang, Y. (2026). [AI research agents narrow scientific exploration](https://arxiv.org/abs/2605.27905). arXiv.
20. Yu, G., & Wang, X. (2026). [Knows: agent-native structured research representations](https://arxiv.org/abs/2604.17309). arXiv.

**Research methodology**

21. Silberzahn, R., et al. (2018). [Many analysts, one data set: making transparent how variations in analytic choices affect results](https://journals.sagepub.com/doi/10.1177/2515245917747646). *Advances in Methods and Practices in Psychological Science*.
22. Steegen, S., Tuerlinckx, F., Gelman, A., & Vanpaemel, W. (2016). [Increasing transparency through a multiverse analysis](https://journals.sagepub.com/doi/10.1177/1745691616658637). *Perspectives on Psychological Science*.
23. Simonsohn, U., Simmons, J. P., & Nelson, L. D. (2020). [Specification curve analysis](https://www.nature.com/articles/s41562-020-0912-z). *Nature Human Behaviour*.
24. Gelman, A., & Loken, E. (2013). *The garden of forking paths.* Columbia University working paper.
25. Dwork, C., et al. (2015). [The reusable holdout: preserving validity in adaptive data analysis](https://www.science.org/doi/10.1126/science.aaa9375). *Science*.
26. Mayo, D. G. (2018). *Statistical Inference as Severe Testing.* Cambridge University Press.
27. VanderWeele, T. J., & Ding, P. (2017). Sensitivity analysis in observational research: introducing the E-value. *Annals of Internal Medicine*.
28. von Elm, E., et al. (2007). The Strengthening the Reporting of Observational Studies in Epidemiology (STROBE) statement. *The Lancet*.
29. Brown, N. J. L., & Heathers, J. A. J. (2017). The GRIM test: a simple technique detects numerous anomalies in the reporting of results in psychology. *Social Psychological and Personality Science*.
30. Nuijten, M. B., et al. (2016). The prevalence of statistical reporting errors in psychology (1985–2013). *Behavior Research Methods*.

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

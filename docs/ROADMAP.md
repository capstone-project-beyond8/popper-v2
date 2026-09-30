# Roadmap

Every milestone ends at a **demo gate**: one command that a person can run, producing output they can read. Each milestone also has a **size cap** on `src/` lines (counted by `wc -l` over `src/popper/**/*.py`, prompts excluded). Going over the cap stops work for a review; the cap is never raised quietly. Design context lives in [ARCHITECTURE.md](ARCHITECTURE.md).

| Milestone | Functions | Demo gate | Cap | Status |
|---|---|---|---|---|
| M0 Mini scientist, end to end | All five phases, minimal | `popper run examples/student_performance` → `paper.pdf` with framing, data changes, exploration figures, one hypothesis, a tested result and `\R{}` numbers | 1,400 | todo |
| M1 Full experiment stages and figure feedback | Data, Experiment | Experiment split into baseline → main → robustness; the vision model reads figures and its feedback shapes the next node; the paper has a robustness section | 2,000 | todo |
| M2 Science loop | Ideation ⇄ Exploration ⇄ Experiment | Several hypotheses; the researcher picks on the CLI; experiment results revise hypotheses; data problems reopen the data stage | 2,600 | todo |
| M3 Write-up and review | Communicate | PDF + `review.json` + `tree.html` (clickable experiment tree) | 3,000 | todo |
| M4 Evaluation | All | Table of reviewer scores, planted-effect recovery, cost and time on 3–5 datasets, across configurations | + `evals/` | todo |
| M5 Literature | Understand, Communicate | Hypotheses and paper cite real prior work (OpenAlex) | 3,500 | todo |
| M6 Verify (optional) | Verify | `popper verify <run> <result>` → a confirmed/not-confirmed outcome on the held-out rows | 4,000 | todo |
| M7 Evidence-led | — | Only items M4 shows are needed: parallel workers, container sandbox, resume, multiple datasets, web UI | — | — |

## M0 — Mini scientist, end to end

The goal is one complete pass, rough but real, through every function except Verify.

1. **Harness.**
   - `llm`: Bedrock Converse wrapper for text, JSON and image input, with token and cost accounting, plus a `FakeLLM` that replays scripted replies for tests.
   - `interpreter`: runs a script in a subprocess with a timeout, the node folder as working directory, and credentials stripped from the environment; captures stdout/stderr and collects `results.json` and figures.
   - `store`: creates the run directory and node folders.
   - `journal`: append-only JSONL.
   - `budget`: a USD cap checked before each model call.
   - `config`: loads `config/default.yaml` with CLI overrides.
2. **Discover engine.** The tree search of ARCHITECTURE §5: draft, debug and improve nodes run sequentially, the feedback model scores nodes, and the best node is selected. It is written once and reused by every stage.
3. **Phases.**
   1. *Ideation & framing*: a structural profile of the CSV, then `framing.json` from the brief and the profile. One reflection round.
   2. *Data*: the `data` stage writes `processed.parquet` and a table of changes.
   3. *Exploration & hypothesis*: the `explore` stage, then one model step that turns its observations into **one** hypothesis with planned experiments.
   4. *Experiment*: one combined `experiment` stage that tests the hypothesis.
   5. *Publication*: a fixed LaTeX template (sections following the phases), `\R{}` macros from the best nodes' `results.json`, figures from the explore and experiment nodes, an appendix with the reported nodes' code and the `exploratory` label, and a tectonic compile (falling back to `.tex` only).
4. **CLI.** `popper run <example_dir | --brief B --data D> [--config C]`, which prints the path to the run directory and the PDF.

**Out of M0:** splitting the experiment stage, VLM feedback, several hypotheses, researcher choice, loops back to earlier phases, reviewer, `tree.html`, holdout.

## Rules that apply to every milestone

- Update the Status column and ARCHITECTURE.md in the same change that finishes a milestone. ARCHITECTURE.md describes built behaviour. Plans live in `docs/specs/` and are deleted or archived when done.
- A mechanism added after M4 names the failure it fixes and its result on the evaluation set.

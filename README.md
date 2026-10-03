# Popper v2

Popper is developing toward a persistent AI Scientist backed by Scientific Runtime and Agent Harness. The current implementation works within a bounded tabular-data Run: it grounds researcher intent, retains multiple sourced quantitative candidates, challenges them from a fresh context, selects a ResearchMove, and freshly executes its committed specification. It records interpretations, surviving rivals, limitations and open questions before choosing another move. Cross-run Program continuity and candidate maturation remain target capabilities.

The `scientist` package owns scientific decisions and the current playbook. `science` owns scientific records, evidence and state; Harness/code search executes declared work, and the coordinator handles dispatch and resources. Scientific snapshots exclude live budgets; resume takes spend and cap raises from the journal.

Reports distinguish coverage, attributed fidelity, sensitivity and computed prospective support, and retain scientific feedback beside the evidence. Negative, incomplete and untested work remain visible. Challenge and interpretation are attributed reasoning; standing remains exploratory and reserved data is not used for validation.

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Plan: [docs/ROADMAP.md](docs/ROADMAP.md) · Contributing: [AGENTS.md](AGENTS.md)

## Setup

Requirements:
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Amazon Bedrock access
- Optional: a LaTeX engine for PDF output. [tectonic](https://tectonic-typesetting.github.io/) is recommended (`winget install tectonic`); MiKTeX or TeX Live with `latexmk` or `pdflatex` also work. Without one, runs still produce `paper.tex`.

```sh
uv sync
cp .env.example .env   # fill in AWS credentials and region
uv run popper --version
```

## Run

Start a bounded research episode from a research context and a CSV file:

```sh
uv run --env-file .env popper run examples/student_performance
```

Defaults live in `src/popper/default_config.yaml`. A directory's `config.yaml` overlays those defaults; `--config my.yaml` overlays it key-by-key. `POPPER_MODEL` takes precedence for all roles. Both student examples group the holdout split by `student_id`, keeping duplicate entities together. Default holdout fraction is 0.2 with seed 7; set fraction 0 to disable reservation (not eligible for later verification).

Each run writes a folder under `runs/`: immutable `run.json` with saved config, discovery `data/raw.csv`, reserved `data/holdout.sealed`, split counts/hashes, numbered state checkpoints, committed artifacts and append-only journal events. Submitted scripts/logs/results live under `tree/<stage-instance>/<node>/execution/`; scratch and diagnostic invocations have distinct execution IDs. Reports live under `report/attempt-<sequence>/`, with PDF builds in fresh `build-<sequence>/` directories. Follow the journal's artifact commits for candidates, challenges, tests, selections, scheduled attempts, interpretations, episode output and report.

Discovery limits can be overridden in `config.yaml`:

```yaml
discovery:
  hypotheses: 3     # 2 or 3 initial candidates
  max_moves: 4      # positive; interrupted scheduled attempts count
  max_revisits: 1   # nonnegative; each later move on a hypothesis counts
```

Repair retains the intended test; changed inference effort, seed or operational slice requires refinement. Pivot, reframe and acquisition requests are retained as deferred routes. When resources stop work, a partial or diagnostic LaTeX source still reports the committed state; the run remains `budget_exceeded`.

```sh
uv run popper resume runs/<run_id> --quiet
uv run popper pdf runs/<run_id>
uv run python -m examples.student_performance_null.make_data
uv run --env-file .env popper run examples/student_performance_null
```

Resume uses the saved config and all recorded costs; it never resets step or monetary budgets. Incomplete attempts remain preserved and consume limits; committed work is not replayed. New runs use format 5. Format-4 runs retain their original single-hypothesis policy, global names and legacy stability labels; older unsupported formats cannot resume, but their `report/paper.tex` can still be built. Raise a stopped run's cap explicitly with `popper resume runs/<run_id> --max-usd <cap>`. Provider cost incurred immediately before process death may not have reached the journal.

Generated Python uses a local access guard: mounted discovery files and Python/library resources may be read; only the current execution folder may be written. Holdout, sibling evidence and ordinary credential files are denied; credentials are removed from script environments. This guards accidental Python file access, not hostile native code, network access or multi-user use. Code-assessment sessions receive masked source/structural results and code-generated sample-count diagnostics, never result plots or estimates; original figures remain available to reporting. Scientific challenge uses a separate fresh, read-only session over exact committed records. Interpretations may read accepted named results; neither assessment can change empirical values or evidence standing.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

> Reports produced by Popper are generated autonomously and are labelled as such.

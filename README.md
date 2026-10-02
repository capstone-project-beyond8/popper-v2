# Popper v2

An AI scientist for quantitative tabular data. From a research context (`research.md`) and a CSV, Popper runs five phases: ideation & framing → data → exploration & hypothesis → experiment → publication. It retains two or three sourced hypotheses, proposes and selects an informative research move, executes baseline/main/predeclared sensitivity analyses, and updates committed research state. Reports distinguish coverage, attributed fidelity, sensitivity and computed prospective support. Negative, incomplete and untested work remain visible. Standing remains exploratory; reserved data is not used for verification.

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Plan: [docs/ROADMAP.md](docs/ROADMAP.md) · Contributing: [AGENTS.md](AGENTS.md)

![Popper architecture](docs/images/architecture.svg)

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

Run all phases on a research context and a CSV file:

```sh
uv run --env-file .env popper run examples/student_performance
```

Defaults live in `src/popper/harness/default_config.yaml`. A directory's `config.yaml` overlays those defaults; `--config my.yaml` overlays it key-by-key. `POPPER_MODEL` takes precedence for all roles. Both student examples group the holdout split by `student_id`, keeping duplicate entities together. Default holdout fraction is 0.2 with seed 7; set fraction 0 to disable reservation (not eligible for later verification).

Each run writes a folder under `runs/`: immutable `run.json` with saved config, discovery `data/raw.csv`, reserved `data/holdout.sealed`, split counts/hashes, numbered state checkpoints, committed artifacts and append-only journal events. Submitted scripts/logs/results live under `tree/<stage-instance>/<node>/execution/`; scratch and diagnostic invocations have distinct execution IDs. Reports live under `report/attempt-<sequence>/`, with PDF builds in fresh `build-<sequence>/` directories. Follow the journal's artifact commits for candidates, tests, selections, scheduled attempts, study output and report.

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

Generated Python uses a local access guard: mounted discovery files and Python/library resources may be read; only the current execution folder may be written. Holdout, sibling evidence and ordinary credential files are denied; credentials are removed from script environments. This guards accidental Python file access, not hostile native code, network access or multi-user use. Experiment Judges receive masked source/structural results and code-generated sample-count diagnostics, never result plots or estimates; original figures remain available to publication.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

> Reports produced by Popper are generated autonomously and are labelled as such.

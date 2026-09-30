# Popper v2

An AI scientist for quantitative tabular data. From a research brief and a CSV, Popper runs five phases: ideation & framing → data → exploration & hypothesis → experiment → publication. It prepares and explores discovery data, selects one primary hypothesis, runs baseline → main → bounded robustness analyses, and writes a LaTeX report with every successful experiment attempt. Stability (`stable`/`fragile`) is computed from executed estimates and a permutation diagnostic; standing always remains `exploratory`. Held-out data is reserved, not used for verification yet.

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

Run all phases on a brief and a CSV file:

```sh
uv run --env-file .env popper run examples/student_performance
```

Defaults live in `src/popper/harness/default_config.yaml`. A directory's `config.yaml` overlays those defaults; `--config my.yaml` overlays it key-by-key. `POPPER_MODEL` takes precedence for all roles. Both student examples group the holdout split by `student_id`, keeping duplicate entities together. Default holdout fraction is 0.2 with seed 7; set fraction 0 to disable reservation (not eligible for later verification).

Each run writes a folder under `runs/`: immutable `run.json` with saved config, discovery `data/raw.csv`, reserved `data/holdout.csv`, split counts/hashes, numbered state checkpoints, committed artifacts and append-only journal events. Submitted scripts/logs/results live under `tree/<stage>/<node>/execution/`; scratch runs have separate recorded folders. Reports live under `report/attempt-<sequence>/`, with PDF builds in fresh `build-<sequence>/` directories. Follow the journal's artifact commits for the selected framing, hypothesis, evidence and report.

```sh
uv run popper resume runs/<run_id> --quiet
uv run popper pdf runs/<run_id>
uv run python -m examples.student_performance_null.make_data
uv run --env-file .env popper run examples/student_performance_null
```

Resume uses the saved config and all recorded costs; it never resets step or monetary budgets. Incomplete attempts remain preserved and consume steps; committed work is not replayed. Old-format runs cannot resume, but their `report/paper.tex` can still be built. Provider cost incurred immediately before process death may not have reached the journal.

Generated Python uses a local access guard: mounted discovery files and Python/library resources may be read; only the current execution folder may be written. Holdout, sibling evidence and ordinary credential files are denied; credentials are removed from script environments. This guards accidental Python file access, not hostile native code, network access or multi-user use. Experiment Judges receive masked source/structural results and code-generated sample-count diagnostics, never result plots or estimates; original figures remain available to publication.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

> Reports produced by Popper are generated autonomously and are labelled as such.

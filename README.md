# Popper v2

An AI scientist for quantitative tabular data. From a research brief and a CSV, Popper runs five phases: ideation & framing → data → exploration & hypothesis → experiment → publication. It prepares and explores the data, forms hypotheses from what it sees, writes and debugs its own analysis scripts in a staged tree search, and writes the study up as a LaTeX report. All results are labelled `exploratory` unless the optional Verify step confirms them on held-out data.

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Plan: [docs/ROADMAP.md](docs/ROADMAP.md) · Contributing: [AGENTS.md](AGENTS.md)

## Setup

Requirements:
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Amazon Bedrock access
- [tectonic](https://tectonic-typesetting.github.io/) for PDF output (`scoop install tectonic` or `winget install tectonic`). Without tectonic, runs still produce `paper.tex`.

```sh
uv sync
cp .env.example .env   # fill in AWS credentials and region
uv run popper --version
```

## Run

The `run` command arrives with the first milestone:

```sh
uv run --env-file .env popper run examples/student_performance
```

Each run writes a folder under `runs/` containing the brief, the data, every generated script with its output and figures, a journal of model calls and executions, and `report/paper.pdf`.

## Develop

```sh
uv run pytest
uv run ruff check .
uv run mypy
```

> Reports produced by Popper are generated autonomously and are labelled as such.

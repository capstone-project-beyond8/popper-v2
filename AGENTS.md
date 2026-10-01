# Repository operating guide

- Code is the source of truth. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is the target design: components, contracts and invariants that specs and plans follow. [docs/ROADMAP.md](docs/ROADMAP.md) sets the product milestones, their acceptance criteria and rough size estimates.
- Commands, dependencies and tool settings are in [pyproject.toml](pyproject.toml). Default run configuration is in [src/popper/harness/default_config.yaml](src/popper/harness/default_config.yaml).

## Layout

| Path | Owns |
|---|---|
| `src/popper/harness/` | Model access, agent loop and tools, context assembly, script execution, run store, journal, budget, decision layer, config (defaults in `default_config.yaml`). No research logic |
| `src/popper/treesearch/` | Generic stage engine: nodes, draft/debug/improve steps, scoring, best-node selection |
| `src/popper/understand/` | Ideation & framing: data profile, framing |
| `src/popper/ground/` | Data phase: preparation stage goals and checks |
| `src/popper/discover/` | Exploration & hypothesis and experiment phases |
| `src/popper/communicate/` | Publication: LaTeX write-up, figure aggregation, review |
| `src/popper/coordinator/` | The PI: the playbook that runs the five phases in order |
| `src/popper/cli.py` | Entry point |
| `examples/` | Briefs and datasets for demos and evaluation |
| `evals/` | Evaluation suites and comparisons (production code never imports it) |

Function packages import only `harness` and `treesearch`, and never each other. Prompts live in `<package>/prompts/`.

## Rules

- Stay inside the current milestone. Do not build items that ROADMAP places in a later milestone.
- Keep code as small as the milestone outcome allows; the size estimates in ROADMAP are for planning, not limits.
- Keep the always-on rules of ARCHITECTURE §2.1: record every execution, keep run files write-once, have code compute labels, and take numbers from `results.json`.
- Never write credentials into run directories or pass them to generated scripts.
- Specs and plans under `docs/superpowers/` are temporary artifacts. The whole folder is gitignored; never commit anything from it.
- Code is the source of truth. Code, tests, and commits must never reference or mention planning artifacts or their symbols, including plans, specs, roadmap, milestones such as `M0`, slice numbers, catalog IDs, `§` references, or ledgers.
- Keep a single source of truth with clear semantics and a traceable flow. Do not introduce duplicate logic, cross-dependencies, parallel legacy paths, ambiguous schemas, or stale tests and documentation.
- After fully implementing every plan, run a simplify pass with a subagent before finishing the branch.

## Tests

Test what can silently break and is worth the upkeep. Nothing else.

- **Unit** (`tests/unit/`): pure logic with real edge cases, such as tree-search node selection, `results.json` → LaTeX macro rendering, and config loading.
- **Integration** (`tests/integration/`, marker `integration`): one end-to-end run with `FakeLLM` and the real interpreter, plus interpreter timeouts and failures.
- No tests for prompts, for trivial wrappers, or ones that only mirror the implementation. No provider calls in tests.
- Mark tests that run the full pipeline or import the scientific stack in a child script with `slow`. Extend the existing pipeline test or test at stage level with `FakeLLM`; do not add another full pipeline run.
- Scripts generated in tests import only what the assertion needs.
- Tests run in parallel: use `tmp_path`, share no global state or working directory, and avoid wall-clock assertions that fail on a loaded machine.

## Verification

```sh
uv sync
uv run ruff check .
uv run mypy
uv run pytest <changed test files>          # while working
uv run pytest -m "not slow"                 # before handing off a change
uv run pytest -n 8 --dist worksteal         # before merging, or after changing harness/, treesearch/ or coordinator/
```

Run ruff, mypy and the matching pytest tier before handing off. Report what ran and what failed. Run tests through the project environment (`uv run`), not `uv run --with`: the script sandbox only reads the project environment's libraries.

## Commits

Conventional commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`). Do not reference plan files or milestone numbers in code, tests, or commit messages.

## Worktrees

The same conventional prefixes for worktree names: `feat/`, `fix/`, `docs/`, `test/`, `chore/`, `refactor/`, followed by a short kebab-case description.

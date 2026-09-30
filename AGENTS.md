# Repository operating guide

- Code is the source of truth. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes built behaviour and the rules the code keeps. [docs/ROADMAP.md](docs/ROADMAP.md) orders the work and holds the size caps.
- Commands, dependencies and tool settings are in [pyproject.toml](pyproject.toml). Default run configuration is in [src/popper/harness/default_config.yaml](src/popper/harness/default_config.yaml).

## Layout

| Path | Owns |
|---|---|
| `src/popper/harness/` | Model access, script execution, run store, journal, budget, config (defaults in `default_config.yaml`). No research logic |
| `src/popper/treesearch/` | Generic stage engine: nodes, draft/debug/improve steps, scoring, best-node selection |
| `src/popper/understand/` | Ideation & framing: data profile, framing |
| `src/popper/ground/` | Data phase: preparation stage goals and checks |
| `src/popper/discover/` | Exploration & hypothesis and experiment phases |
| `src/popper/communicate/` | Publication: LaTeX write-up, figure aggregation, review |
| `src/popper/coordinator/` | The playbook that runs the five phases in order |
| `src/popper/cli.py` | Entry point |
| `examples/` | Briefs and datasets for demos and evaluation |

Function packages import only `harness` and `treesearch`, and never each other. Prompts live in `<package>/prompts/`.

## Rules

- Stay inside the current milestone. Do not build deferred items (ARCHITECTURE §9) ahead of their milestone.
- Watch the size cap. If a change would push `src/` past the milestone cap, stop and raise it.
- Keep the always-on rules of ARCHITECTURE §7: record every execution, keep run files write-once, have code compute labels, and take numbers from `results.json`.
- Never write credentials into run directories or pass them to generated scripts.

## Tests

Test what can silently break and is worth the upkeep. Nothing else.

- **Unit** (`tests/unit/`): pure logic with real edge cases, such as tree-search node selection, `results.json` → LaTeX macro rendering, and config loading.
- **Integration** (`tests/integration/`, marker `integration`): one end-to-end run with `FakeLLM` and the real interpreter, plus interpreter timeouts and failures.
- No tests for prompts, for trivial wrappers, or ones that only mirror the implementation. No provider calls in tests.

## Verification

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

Run all four before handing off a change. Report what ran and what failed.

## Commits

Conventional commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`). Do not reference plan files or milestone numbers in code or tests.

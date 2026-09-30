# Mini Scientist (M0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `popper run examples/student_performance` runs all five phases (ideation & framing → data → exploration & hypothesis → experiment → publication) and produces `report/paper.tex` (and `paper.pdf` when tectonic is installed) whose numbers come from `results.json`.

**Architecture:** A harness (Bedrock model access, subprocess script runner, write-once run store, journal, budget) sits under a generic tree-search engine (`treesearch/`). Each phase package builds stage specs or makes model calls through the harness. The coordinator runs the phases in order and the CLI calls the coordinator.

**Tech Stack:** Python 3.13, uv, pydantic 2, PyYAML, Jinja2, boto3 (Bedrock Converse), pandas/pyarrow, matplotlib (Agg), pytest, ruff, mypy strict.

**Spec:** [docs/ARCHITECTURE.md](../ARCHITECTURE.md) (§2 phases, §4 run directory, §5 tree search, §6 communicate, §7 always-on rules) and [docs/ROADMAP.md](../ROADMAP.md) (M0 section).

## Global Constraints

- The `src/popper/**/*.py` total stays ≤ 1,400 lines (`wc -l`); prompts and templates are not counted.
- Import rule: function packages (`understand`, `ground`, `discover`, `communicate`) import only `popper.harness` and `popper.treesearch`, never each other. `treesearch` imports only `harness`, and `harness` imports nothing from Popper.
- Run files are write-once. `RunStore.write_*` raises `FileExistsError` when the target exists.
- Generated scripts never receive credentials. The environment passed to a subprocess drops every `AWS_*` variable and every variable whose name contains `KEY`, `SECRET` or `TOKEN`.
- Tests make no provider calls. The only model in tests is `FakeLLM`.
- Code and tests do not mention milestones, plan files or section numbers.
- Every task ends with `uv run pytest && uv run ruff check . && uv run mypy` passing.
- Commit messages use conventional prefixes and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Model reply without a python code block.** The node becomes `buggy` with analysis `"no code block in reply"`, and the stage continues. (Test: Task 4, `test_stage_recovers_from_bad_replies`.)
2. **Script exits 0 but writes an invalid or wrongly shaped `results.json`.** The node becomes `buggy` from the code check, with no feedback-model call. (Test: Task 4, same test.)
3. **Every node in a stage is buggy.** `run_stage` raises `StageFailed(stage)`, the run writes `run.json` with `status: "failed"` and `failed_stage`, and the CLI exits 1 with that message. (Tests: Task 4 `test_stage_fails_when_no_node_works`, Task 7 CLI check.)
4. **Budget reached mid-run.** The next model call raises `BudgetExceeded` before calling the provider, `run.json` gets `status: "budget_exceeded"`, and the CLI exits 1. (Test: Task 2 `test_budget_blocks_calls`.)
5. **Model-written LaTeX fails to compile, or tectonic is missing.** `paper.tex` is still written, `compile_pdf` returns `None`, and the CLI prints the `.tex` path and a warning while exiting 0. (Test: Task 6 `test_compile_without_tectonic`.)

---

### Task 1: Configuration

**Files:**
- Move: `config/default.yaml` → `src/popper/harness/default_config.yaml` (then delete the `config/` directory)
- Create: `src/popper/harness/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `Role = Literal["ideation", "code", "feedback", "vision", "writeup"]`
  - `class Config(BaseModel)`, with `extra="forbid"` on all models:
    - `models: dict[Role, str]`
    - `search: SearchConfig` (`num_drafts: int`, `debug_prob: float`, `max_debug_depth: int`, `steps_per_stage: int`)
    - `execution: ExecutionConfig` (`timeout_seconds: int`, `max_output_chars: int`)
    - `budget: BudgetConfig` (`max_usd: float`, `usd_per_mtok_input: float`, `usd_per_mtok_output: float`)
  - `load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config`

Additions to the YAML (the rest stays as committed):
- `models.ideation`, the same placeholder ID as the other roles;
- `budget.usd_per_mtok_input: 3.0` and `budget.usd_per_mtok_output: 15.0`;
- the first comment changed to `# Default run configuration, loaded by popper.harness.config.`

- [ ] **Step 1: Write the failing tests**

```python
def test_defaults_load():
    cfg = load_config(env={})
    assert cfg.search.num_drafts == 3 and cfg.execution.timeout_seconds == 300
    assert set(cfg.models) == {"ideation", "code", "feedback", "vision", "writeup"}

def test_user_file_overrides_key_by_key(tmp_path):
    f = tmp_path / "c.yaml"; f.write_text("search:\n  steps_per_stage: 2\n")
    cfg = load_config(f, env={})
    assert cfg.search.steps_per_stage == 2 and cfg.search.num_drafts == 3

def test_popper_model_env_overrides_every_role():
    cfg = load_config(env={"POPPER_MODEL": "m-x"})
    assert set(cfg.models.values()) == {"m-x"}

def test_unknown_key_rejected(tmp_path):
    f = tmp_path / "c.yaml"; f.write_text("serch: {}\n")
    with pytest.raises(ValidationError):
        load_config(f, env={})
```

- [ ] **Step 2: Run `uv run pytest tests/unit/test_config.py`.** Expected: FAIL (import error).
- [ ] **Step 3: Implement.** Read the default with `importlib.resources.files("popper.harness") / "default_config.yaml"`, deep-merge the user dict (nested dicts merge; other values replace), apply `POPPER_MODEL`, then call `Config.model_validate`. `env=None` means `os.environ`.
- [ ] **Step 4: Run the full check.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: load run configuration with overrides`.

### Task 2: Harness (model access, run store, journal, budget)

**Files:**
- Create: `src/popper/harness/llm.py`, `src/popper/harness/store.py`, `src/popper/harness/session.py`
- Test: `tests/unit/test_session.py`

**Interfaces:**
- Consumes: `Config`, `Role` (Task 1).
- Produces:
  - `llm.py`:
    - `@dataclass(frozen=True) class LLMRequest(model: str, tag: str, system: str, prompt: str, images: tuple[Path, ...] = ())`
    - `@dataclass(frozen=True) class Completion(text: str, input_tokens: int, output_tokens: int)`
    - `class LLM(Protocol): def complete(self, req: LLMRequest, max_tokens: int = 8000) -> Completion`
    - `class BedrockLLM(LLM)`, built from `__init__(self, region: str)`. It uses boto3 `bedrock-runtime` `converse` and sends images as PNG `image` blocks.
    - `class FakeLLM(LLM)`, built from `__init__(self, responder: Callable[[LLMRequest], str])`. It records `self.requests: list[LLMRequest]` and returns zero tokens.
  - `store.py`, `class RunStore` (all paths absolute):
    - `root: Path`
    - `@classmethod create(cls, runs_dir: Path, brief: Path, data: Path) -> RunStore`: makes `<runs_dir>/<YYYYmmdd-HHMMSS>-<4 hex>/`, copies the brief to `brief.md` and the data to `data/raw.csv`
    - `path(self, *parts: str) -> Path`
    - `write_text(self, rel: str, text: str) -> Path` and `write_json(self, rel: str, obj: object) -> Path`, both write-once and creating parent directories
    - `read_json(self, rel: str) -> Any`
  - `session.py`:
    - `class BudgetExceeded(RuntimeError)`
    - `class Journal`, built from `__init__(self, path: Path)`, with `write(self, event: str, **fields: object) -> None`. It appends one JSON line with `ts`, `event` and the fields. It is the only file opened in append mode.
    - `class Harness`, built from `__init__(self, config: Config, llm: LLM, store: RunStore)`. Public attributes: `config`, `llm`, `store`, `journal` (at `store.path("journal.jsonl")`) and `spent_usd: float`. Methods:
      - `ask(self, role: Role, *, tag: str, system: str, prompt: str, images: Sequence[Path] = ()) -> str`
      - `ask_json(self, role: Role, *, tag: str, system: str, prompt: str) -> dict[str, Any]`

`ask` rules:
1. If `spent_usd >= budget.max_usd`, raise `BudgetExceeded` before calling the provider.
2. Otherwise call the model and add the cost: `in_tok/1e6*usd_per_mtok_input + out_tok/1e6*usd_per_mtok_output`.
3. Write the journal event `model_call` with `role`, `tag`, `model`, `input_tokens`, `output_tokens` and `usd`.

`ask_json` parses the first ```json fenced block, or the whole text when there is no fence. On a parse failure or a non-dict result, it re-asks once with the error appended to the prompt. A second failure raises `ValueError`.

- [ ] **Step 1: Write the failing tests.** A local helper `make_harness(tmp_path, reply=None, responder=None, max_usd=5.0)` builds a `Harness` over `tmp_path`, using `RunStore.create` with small brief and data files and a `FakeLLM` that returns `reply` or calls `responder`.

```python
def test_budget_blocks_calls(tmp_path):
    h = make_harness(tmp_path, reply="x", max_usd=0.0)
    with pytest.raises(BudgetExceeded):
        h.ask("code", tag="t", system="s", prompt="p")
    assert h.llm.requests == []

def test_ask_json_retries_once_then_parses(tmp_path):
    replies = iter(["not json", '```json\n{"a": 1}\n```'])
    h = make_harness(tmp_path, responder=lambda r: next(replies))
    assert h.ask_json("feedback", tag="t", system="s", prompt="p") == {"a": 1}
    assert len(h.llm.requests) == 2

def test_each_call_is_journaled(tmp_path):
    h = make_harness(tmp_path, reply="ok")
    h.ask("code", tag="code:data", system="s", prompt="p")
    lines = (h.store.root / "journal.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["tag"] == "code:data"

def test_store_is_write_once(tmp_path):
    h = make_harness(tmp_path, reply="x")
    h.store.write_text("a.txt", "1")
    with pytest.raises(FileExistsError):
        h.store.write_text("a.txt", "2")
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement the three modules.** `BedrockLLM` has no unit test. Keep it thin: build a `messages` list with one user turn made of text plus image blocks, pass `system` as a system block and `inferenceConfig={"maxTokens": max_tokens}`, and read `output.message.content[0].text` and `usage`.
- [ ] **Step 4: Run the full check.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: add harness for model calls, run store and journal`.

### Task 3: Script interpreter

**Files:**
- Create: `src/popper/harness/interpreter.py`
- Test: `tests/integration/test_interpreter.py` (marker `integration`)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ExecResult(exit_code: int | None, timed_out: bool, stdout: str, stderr: str, seconds: float)`
  - `run_script(code: str, workdir: Path, *, timeout: float, inputs: Mapping[str, Path], max_output_chars: int) -> ExecResult`

Behaviour:
- Write `workdir/code.py` and run `[sys.executable, "code.py"]` with `cwd=workdir`.
- Build the environment from `os.environ`, minus the credential variables of Global Constraints, plus `MPLBACKEND=Agg` and `POPPER_INPUT_<NAME.upper()>=<abs path>` for each input.
- Write `stdout.txt` and `stderr.txt` into `workdir` (full text).
- The returned `stdout`/`stderr` keep only the last `max_output_chars` characters.
- On timeout, kill the process, then return `exit_code=None` and `timed_out=True`.

- [ ] **Step 1: Write the failing tests**

```python
def test_runs_and_captures(tmp_path):
    r = run_script("print('hi')", tmp_path, timeout=30, inputs={}, max_output_chars=100)
    assert r.exit_code == 0 and r.stdout.strip() == "hi" and (tmp_path / "stdout.txt").exists()

def test_error_exit_and_stderr(tmp_path):
    r = run_script("raise ValueError('boom')", tmp_path, timeout=30, inputs={}, max_output_chars=2000)
    assert r.exit_code != 0 and "boom" in r.stderr

def test_timeout(tmp_path):
    r = run_script("import time; time.sleep(10)", tmp_path, timeout=1, inputs={}, max_output_chars=100)
    assert r.timed_out and r.exit_code is None

def test_credentials_stripped_and_inputs_passed(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s"); monkeypatch.setenv("MY_API_TOKEN", "t")
    code = "import os; print(sorted(k for k in os.environ if 'SECRET' in k or 'TOKEN' in k or k.startswith('AWS_'))); print(os.environ['POPPER_INPUT_DATA'])"
    r = run_script(code, tmp_path, timeout=30, inputs={"data": tmp_path / "d.csv"}, max_output_chars=2000)
    assert r.stdout.splitlines()[0] == "[]" and r.stdout.splitlines()[1].endswith("d.csv")
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement `run_script`** with `subprocess.run(..., capture_output=True, text=True, timeout=timeout)`, catching `TimeoutExpired`.
- [ ] **Step 4: Run the full check.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: run generated scripts in a clean subprocess`.

### Task 4: Tree-search engine

**Files:**
- Create: `src/popper/treesearch/__init__.py` (docstring: `"""Generic stage engine: draft, debug and improve analysis scripts and keep the best."""`), `src/popper/treesearch/engine.py`, `src/popper/treesearch/prompts/code.md`, `src/popper/treesearch/prompts/feedback.md`
- Test: `tests/unit/test_selection.py`, `tests/integration/test_stage.py`

**Interfaces:**
- Consumes: `Harness`, `run_script`, `SearchConfig`.
- Produces (in `engine.py`, re-exported from `treesearch/__init__.py`):
  - `NodeKind = Literal["draft", "debug", "improve"]`
  - `@dataclass class Node`, with fields:
    - `id: str`, `stage: str`, `parent: str | None`, `kind: NodeKind`
    - `debug_depth: int`, `code: str`
    - `status: Literal["ok", "buggy"]`, `score: float | None`, `goal_met: bool`
    - `analysis: str`, `results: dict[str, dict[str, Any]]`, `figures: list[Path]`, `dir: Path`
  - `@dataclass(frozen=True) class StageSpec`, with fields:
    - `name: str`, `goal: str`, `context: str`
    - `inputs: dict[str, Path]`
    - `required_outputs: tuple[str, ...]` (file names relative to the node dir; `results.json` is always required)
    - `seed_code: str | None = None`
  - `class StageFailed(RuntimeError)` with attribute `stage: str`
  - `choose_action(nodes: Sequence[Node], search: SearchConfig, rng: random.Random) -> tuple[NodeKind, Node | None]`
  - `select_best(nodes: Sequence[Node]) -> Node | None`
  - `validate_results(obj: object) -> str | None`: returns an error message, or `None` when valid
  - `run_stage(h: Harness, spec: StageSpec, rng: random.Random | None = None) -> tuple[Node, list[Node]]`: returns `(best, all_nodes)`

`choose_action` algorithm (ARCHITECTURE §5):
```text
roots = [n for n in nodes if n.parent is None]
if len(roots) < num_drafts: return ("draft", None)
leaves = buggy nodes with debug_depth < max_debug_depth and no child in nodes
if leaves and rng.random() < debug_prob: return ("debug", rng.choice(leaves))
best = select_best(nodes)
if best: return ("improve", best)
if leaves: return ("debug", rng.choice(leaves))
return ("draft", None)
```

`run_stage` loop, for up to `steps_per_stage` steps:
1. Choose an action.
2. Build the code prompt from `prompts/code.md`. It contains: goal, context, input env var names, required outputs, the `results.json` shape (ARCHITECTURE §5), "save figures as PNG under `figures/`", and "print a short summary". It adds `seed_code` for a draft when present, the parent code plus the stderr tail for debug, and the parent code plus analysis for improve.
3. Call `ask("code", tag=f"code:{spec.name}")`.
4. Extract the first ```python block. If there is none, the node is buggy with analysis `"no code block in reply"` and nothing is run.
5. Run the script in `store.path("tree", spec.name, node_id)` with `node_id = f"{spec.name}-{n:03d}"`.
6. Run the code check, in order: timed out, exit≠0, a missing required output, then `validate_results(json)`. Any failure makes the node buggy with the reason as its analysis.
7. If the code check passes, call `ask_json("feedback", tag=f"feedback:{spec.name}")` with the goal, code, stdout tail and results. The reply keys are `is_buggy`, `analysis`, `score` (1–10) and `goal_met`.
8. Write `meta.json` (every field except `code`, `results` and `dir`) and `analysis.md`, and journal `node` with its id, kind, status and score.
9. Stop early when the new node is `ok` and `goal_met`.

At the end, `select_best(all_nodes)`, or `StageFailed(spec.name)` when it returns `None`. A debug node's `debug_depth` is its parent's plus 1; other kinds get 0.

- [ ] **Step 1: Write the failing unit tests** (`test_selection.py`, with nodes built by a small helper)

```python
def test_drafts_first():
    assert choose_action([], SEARCH, random.Random(0)) == ("draft", None)

def test_improves_best_when_no_bugs():
    a, b = ok("a", 5), ok("b", 8)
    assert choose_action([a, b, ok("c", 1)], SEARCH, random.Random(0)) == ("improve", b)

def test_debug_respects_depth_limit():
    deep = buggy("d", depth=SEARCH.max_debug_depth)
    nodes = [ok("a", 5), ok("b", 6), deep]
    assert all(choose_action(nodes, SEARCH, random.Random(s))[0] == "improve" for s in range(20))

def test_select_best_ties_go_to_earlier():
    assert select_best([ok("a", 7), ok("b", 7), buggy("c")]).id == "a"

def test_validate_results_shape():
    assert validate_results({"r": {"value": 0.4, "ci": [0.1, 0.7]}}) is None
    assert validate_results({"Bad Name": {"value": 1}}) is not None
    assert validate_results({"r": {"ci": [0, 1]}}) is not None
    assert validate_results([1, 2]) is not None
```
(`SEARCH = SearchConfig(num_drafts=3, debug_prob=0.5, max_debug_depth=3, steps_per_stage=8)`.)

- [ ] **Step 2: Write the failing integration tests** (`test_stage.py`, marker `integration`). Build a `Harness` with `FakeLLM` and a responder keyed on `req.tag`, with `num_drafts=1`, `steps_per_stage=4`, `debug_prob=1.0`.

```python
def test_stage_recovers_from_bad_replies(tmp_path):
    code_replies = iter([
        "no code here",                                                   # draft -> buggy, nothing run
        "```python\nimport json; json.dump([1], open('results.json','w'))\n```",   # debug -> invalid results
        "```python\nimport json; json.dump({'m': {'value': 2}}, open('results.json','w'))\n```",
    ])
    # feedback replies: {"is_buggy": false, "analysis": "fine", "score": 7, "goal_met": true}
    best, nodes = run_stage(h, spec, random.Random(0))
    assert [n.status for n in nodes] == ["buggy", "buggy", "ok"]
    assert best.results == {"m": {"value": 2}} and best.debug_depth == 2
    assert [r.tag for r in h.llm.requests].count("feedback:s") == 1   # only the working node was judged
    assert (best.dir / "meta.json").exists()

def test_stage_fails_when_no_node_works(tmp_path):
    # every code reply: "```python\nraise SystemExit(1)\n```"
    with pytest.raises(StageFailed):
        run_stage(h, spec, random.Random(0))
```

- [ ] **Step 3: Run the tests.** Expected: FAIL.
- [ ] **Step 4: Implement `engine.py` and the two prompts.** Load prompts with `importlib.resources`. `feedback.md` asks for exactly the four JSON keys, and says a score of 10 means the stage goal is fully met with sound, clearly reported analysis.
- [ ] **Step 5: Run the full check.** Expected: PASS.
- [ ] **Step 6: Commit** `feat: add tree-search stage engine`.

### Task 5: Phases 1–4 (framing, data, exploration & hypothesis, experiment)

**Files:**
- Create: `src/popper/understand/framing.py` + `prompts/framing.md`, `src/popper/ground/data_stage.py`, `src/popper/discover/explore.py` + `prompts/hypothesis.md`, `src/popper/discover/experiment.py`
- No new tests: the end-to-end test of Task 7 covers these modules (AGENTS.md test policy).

**Interfaces:**
- Consumes: `Harness`, `StageSpec`, `Node`.
- Produces:
  - `understand/framing.py`:
    - `profile_csv(path: Path, max_examples: int = 5) -> dict[str, Any]`, in pure pandas: `n_rows`, `n_duplicate_rows`, and `columns: {name: {dtype, n_missing, n_unique, examples: list[str]}}`.
    - `frame(h: Harness, brief: str, profile: dict[str, Any]) -> dict[str, Any]`: calls `ask_json("ideation", tag="framing")`, then a second `ask_json("ideation", tag="framing:reflect")` that critiques and returns the improved JSON. Keys: `title`, `problem`, `questions: list[str]`, `key_variables: list[str]`, `directions: list[str]`, `data_concerns: list[str]`.
  - `ground/data_stage.py`:
    - `data_stage(framing: dict[str, Any], profile: dict[str, Any], raw: Path) -> StageSpec`: `name="data"`, `inputs={"data": raw}`, `required_outputs=("results.json", "processed.parquet", "changes.json")`. The goal text covers: fix types, missing codes, duplicates, impossible values and inconsistent categories; derive the variables the questions need; and write `changes.json` as a list of `{step, rows_affected, reason}`. `results.json` must include `rows_before` and `rows_after`.
  - `discover/explore.py`:
    - `explore_stage(framing: dict[str, Any], processed: Path) -> StageSpec`: `name="explore"`, `inputs={"data": processed}`. The goal: distributions, relations and group differences relevant to the questions, at least two figures, and observations as `results.json` entries.
    - `form_hypothesis(h: Harness, framing: dict[str, Any], explore: Node) -> dict[str, Any]`: calls `ask_json("ideation", tag="hypothesis")`. Keys: `statement`, `rationale`, `variables: list[str]`, `planned_experiments: list[str]`, plus `source_node: explore.id`, which is set by code and not taken from the model.
  - `discover/experiment.py`:
    - `experiment_stage(framing: dict[str, Any], hypothesis: dict[str, Any], processed: Path) -> StageSpec`: `name="experiment"`, `inputs={"data": processed}`. The goal: test the hypothesis with the planned experiments, report estimates with intervals and `n`, and draw at least one figure.

- [ ] **Step 1: Implement the four modules and their prompts.** Each stage's `context` holds a JSON dump of the framing (plus the hypothesis for experiment). The framing prompt includes the profile but never raw rows beyond the profile's examples.
- [ ] **Step 2: Run the full check.** Expected: PASS (mypy strict on the new code).
- [ ] **Step 3: Commit** `feat: add framing, data, exploration and experiment phases`.

### Task 6: Publication

**Files:**
- Create: `src/popper/communicate/numbers.py`, `src/popper/communicate/paper.py`, `src/popper/communicate/templates/paper.tex.j2`, `src/popper/communicate/prompts/writeup.md`
- Test: `tests/unit/test_numbers.py`, `tests/unit/test_compile.py`

**Interfaces:**
- Consumes: `Harness`, `Node`.
- Produces:
  - `numbers.py`:
    - `collect_values(nodes: Sequence[Node]) -> dict[str, dict[str, Any]]`, keyed `f"{node.stage}.{name}"`.
    - `format_value(entry: Mapping[str, Any]) -> str`: numbers use `f"{v:.3g}"`, integers stay whole, and a `ci` is appended as ` [lo, hi]` in the same format. Strings are LaTeX-escaped (`\ & % $ # _ { } ~ ^`).
    - `fill_numbers(tex: str, values: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]`: replaces `\R{key}` (key regex `[a-z0-9_.]+`). An unknown key becomes `\textbf{??}` and is added to the returned list of missing keys.
  - `paper.py`:
    - `@dataclass(frozen=True) class PaperInputs`, with fields:
      - `framing: dict[str, Any]`, `hypothesis: dict[str, Any]`
      - `changes: list[dict[str, Any]]`
      - `data_node: Node`, `explore_node: Node`, `experiment_node: Node`
    - `write_paper(h: Harness, inputs: PaperInputs) -> Path`: writes `report/paper.tex` and returns its path.
    - `compile_pdf(tex: Path) -> Path | None`

`write_paper` steps:
1. `values = collect_values([data, explore, experiment])`.
2. Copy the explore and experiment figures to `report/figures/<stage>-<name>.png`.
3. Call `ask_json("writeup", tag="writeup")` with the framing, hypothesis, changes, analyses, available value keys (with values) and figure file names. The reply keys are `title`, `abstract`, `introduction`, `data`, `exploration`, `hypothesis`, `methods`, `results`, `limitations` (LaTeX bodies that use `\R{key}` and `Figure~\ref{fig:<file stem>}`), and `figures: [{file, caption}]`. Figures with unknown file names are dropped, with a journal warning.
4. Render the template with Jinja2 using LaTeX-safe delimiters (`((* *))` blocks, `((( )))` variables).
5. Run `fill_numbers` on the rendered text and journal `missing_numbers` when the list is non-empty.
6. Write `report/paper.tex`.

The template holds:
- `article`, `graphicx`, `booktabs`, `hyperref`, `listings`;
- the model sections in order;
- one figure environment per chosen figure;
- an appendix, rendered by code, with a changes table from `changes.json` and listings of the data and experiment nodes' code;
- the fixed line `\noindent\textbf{Label:} exploratory --- autonomously generated by Popper. Not confirmed on held-out data.` under the abstract. The model cannot change this line.

`compile_pdf` returns `None` when `shutil.which("tectonic")` is `None`. Otherwise it runs `tectonic <tex>` in the tex's directory with a 300 s timeout, and returns `report/paper.pdf` on exit 0 or `None` otherwise.

- [ ] **Step 1: Write the failing tests**

```python
def test_fill_numbers_formats_and_flags_missing():
    values = {"experiment.slope": {"value": 0.123456, "ci": [0.1, 0.15]}, "data.rows_after": {"value": 600}}
    tex, missing = fill_numbers(r"b=\R{experiment.slope}, n=\R{data.rows_after}, x=\R{experiment.nope}", values)
    assert tex == r"b=0.123 [0.1, 0.15], n=600, x=\textbf{??}"
    assert missing == ["experiment.nope"]

def test_string_values_are_escaped():
    assert format_value({"value": "50% & up"}) == r"50\% \& up"

def test_compile_without_tectonic(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    tex = tmp_path / "paper.tex"; tex.write_text("x")
    assert compile_pdf(tex) is None
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement `numbers.py`, `paper.py`, the template and `writeup.md`.** The prompt forbids typing numbers directly: every data-derived number must be a `\R{key}` from the provided list.
- [ ] **Step 4: Run the full check.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: write the LaTeX paper from recorded results`.

### Task 7: Coordinator, CLI and end-to-end test

**Files:**
- Create: `src/popper/coordinator/run.py`
- Modify: `src/popper/cli.py`, `README.md` (config path, `POPPER_MODEL`), `.env.example` (add a commented `# POPPER_MODEL=` line with the explanation: Bedrock model or inference-profile ID used for every role)
- Test: `tests/integration/test_end_to_end.py`, and modify `tests/integration/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass(frozen=True) class RunOutcome(run_dir: Path, status: str, tex: Path | None, pdf: Path | None, failed_stage: str | None)`
  - `run(brief: Path, data: Path, *, config: Config, llm: LLM, runs_dir: Path, seed: int = 0) -> RunOutcome`
  - CLI: `popper run [EXAMPLE_DIR] [--brief B --data D] [--config C] [--runs-dir runs]`. `EXAMPLE_DIR` means `EXAMPLE_DIR/brief.md` and `EXAMPLE_DIR/data.csv`. The CLI builds `BedrockLLM(region=os.environ.get("AWS_REGION", "us-east-1"))`.

`run` sequence (each phase journaled as `phase_start`/`phase_end`):
1. `RunStore.create`.
2. `profile_csv(raw)` → `understand/profile.json`, then `frame` → `understand/framing.json`.
3. `run_stage(data_stage(...))`: copy the best node's `processed.parquet` to `data/processed.parquet`, and read its `changes.json`.
4. `run_stage(explore_stage(...))`, then `form_hypothesis` → `hypotheses.json` as a one-element list.
5. `run_stage(experiment_stage(...))`.
6. `write_paper`, then `compile_pdf`.
7. Always write `run.json`, in a `finally` block: `status` (`"completed"` | `"failed"` | `"budget_exceeded"`), `failed_stage`, `spent_usd`, `config` (`config.model_dump()`), `inputs`, `tex`, `pdf`.

`StageFailed` and `BudgetExceeded` are caught and turned into the status. Any other exception is recorded as `"failed"` and re-raised.

CLI output and exit codes:
- On success, print `run: <dir>` and then `paper: <pdf>`, or `paper (tex only): <tex>` with a warning line when there is no PDF. Exit 0.
- On failure, print `run failed at stage <x>: <dir>` or `run stopped: budget reached: <dir>`. Exit 1.

- [ ] **Step 1: Write the failing end-to-end test** (marker `integration`). Use `examples/student_performance`, `FakeLLM` routed by tag, and a config override: `num_drafts=1`, `steps_per_stage=2`. The data-stage code must really clean the planted issues enough for the later scripts: drop duplicates, coerce `exam_score` with `errors="coerce"`, drop rows with NaN or out-of-range values, and lowercase/map income. The explore code saves one figure. The experiment code fits `numpy.polyfit(study_hours_week, exam_score, 1)` and writes `{"slope": {"value": s, "n": n}}`. The writeup reply uses `\R{experiment.slope}` and figure `explore-<name>.png`.

```python
def test_full_run_writes_traceable_paper(tmp_path):
    out = run(EX / "brief.md", EX / "data.csv", config=cfg, llm=fake, runs_dir=tmp_path)
    assert out.status == "completed" and out.tex is not None
    tex = out.tex.read_text()
    slope = json.loads(next((out.run_dir / "tree" / "experiment").glob("*/results.json")).read_text())["slope"]["value"]
    assert f"{slope:.3g}" in tex and r"\textbf{??}" not in tex
    assert "exploratory --- autonomously generated" in tex
    assert (out.run_dir / "data" / "processed.parquet").exists()
    assert json.loads((out.run_dir / "hypotheses.json").read_text())[0]["source_node"].startswith("explore-")
    assert json.loads((out.run_dir / "run.json").read_text())["status"] == "completed"
    assert "AWS" not in (out.run_dir / "run.json").read_text()
```

- [ ] **Step 2: Add a CLI failure test** to `test_cli.py`. Call `main(["run", "--brief", b, "--data", d, "--runs-dir", tmp])` with the coordinator's `run` monkeypatched to return a `RunOutcome` with `status="failed"` and `failed_stage="data"`, and assert that the return value is `1` and that the printed message contains `stage data`.
- [ ] **Step 3: Run the tests.** Expected: FAIL.
- [ ] **Step 4: Implement `coordinator/run.py` and the CLI subcommand.** Update the README config section.
- [ ] **Step 5: Run the full check and `wc -l` over `src/popper/**/*.py`.** Expected: PASS and ≤ 1,400.
- [ ] **Step 6: Commit** `feat: run the five phases end to end from the CLI`.

### Task 8: Demo gate with a real model (manual, researcher-run)

- [ ] **Step 1:** Set `.env` (AWS credentials, `AWS_REGION`, `POPPER_MODEL=<enabled Bedrock model or inference-profile ID>`) and install tectonic.
- [ ] **Step 2:** Run `uv run --env-file .env popper run examples/student_performance`. Expected: `run: runs/<id>` and `paper: .../paper.pdf`. Cost is in `run.json` and should be under the $5 cap.
- [ ] **Step 3: Inspect the output.**
  - The paper reports the data changes: duplicates, `absent`, impossible values, income labels.
  - It has at least one exploration figure.
  - It states a hypothesis with a tested estimate for study hours.
  - It has no `??`.
  - It carries the exploratory label.

  Record any failures as issues for the next milestone. Do not patch prompts inside this milestone without a new run.
- [ ] **Step 4:** Mark M0 `done` in `docs/ROADMAP.md`, and commit with `docs: mark mini scientist milestone done` together with a note of the demo run id and cost in the commit body.

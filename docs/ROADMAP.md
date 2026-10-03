# Popper Development Roadmap

This roadmap assumes the architecture ownership realignment has already been completed. The goal is to validate the core Scientist behavior first, then expand only when the previous milestone proves the next one is justified.

## Establish Scientist Control

**Goal:** Make the Scientist the single owner of scientific decisions.

The Scientist receives a compact, sourced scientific state and is responsible for proposing the next `ResearchMove` and interpreting outcomes. Other components may validate, execute, dispatch, or enforce resources, but they must not decide scientific direction.

**Scope**
- Minimal `ScientificStateView` derived from committed records.
- `Scientist.propose(state) -> ResearchMove`.
- `Scientist.interpret(state, outcome) -> Interpretation`.
- Existing capabilities remain reusable and independently callable.
- Remove any remaining hidden scientific selection from Coordinator, Harness, Judge, or execution strategies.

**Exit criteria**
- One scientific decision can travel end-to-end with the Scientist as the only scientific decision owner.
- No other component silently ranks hypotheses, changes scientific intent, or interprets evidence on behalf of the Scientist.

---

## Close the Scientific Loop

**Goal:** Turn Scientist control into a working feedback loop inside one Run.

The system repeatedly lets the Scientist inspect state, choose a move, execute the selected capability, interpret the outcome, update state, and decide again.

**Core loop**

```text
Scientific State
      ↓
Scientist decides
      ↓
ResearchMove
      ↓
Authorize / dispatch
      ↓
Capability or Experiment
      ↓
Outcome / Evidence
      ↓
Scientist interprets
      ↓
Updated Scientific State
      ↺
```

**Scope**
- Single Run only.
- Bounded budget and explicit stop conditions.
- Scientist can revisit capabilities instead of following a fixed phase order.
- Negative or inconclusive evidence is treated as scientific feedback, not automatically as an implementation failure.

**Exit criteria**
- The loop can choose, act, interpret, revisit, change direction, and stop.
- `Understand / Ground / Challenge / Experiment / Communication` operate as capabilities, not a mandatory workflow.

---

## Prove One Useful E2E Research Episode

**Goal:** Demonstrate that the loop produces an understandable scientific episode, not merely a reordered pipeline.

Run one real dataset and one clear research question through the new loop. The demo should make the Scientist's decisions, evidence, interpretations, and changes in direction visible.

**Required demo behavior**
- Research question and intent are explicit.
- Framing and grounding occur only when justified by the Scientist.
- At least one hypothesis/rival or competing explanation is considered.
- At least one real experiment produces committed evidence.
- Evidence changes the Scientist's understanding or next move.
- The episode ends with a clear statement of what was learned, what remains uncertain, and the justified next move.

**Important:** The pilot should contain at least one meaningful loop-back, such as an unexpected/null result changing the next experiment, or a grounding issue causing the Scientist to revisit framing.

**Exit criteria**
- A reviewer can clearly see: what the Scientist believed, what evidence appeared, what changed, and why the next decision followed.
- Full evidence provenance and existing integrity guarantees remain intact.

---

## Minimal Persistent Scientist Proof

**Goal:** Prove that scientific understanding can continue across Runs without building the full persistence architecture yet.

Keep this milestone deliberately small. The purpose is only to establish that a later Run can continue from prior scientific work instead of starting over.

**Minimal scope**
- Persistent `Program` identity.
- Run 1 commits:
  - accepted evidence references,
  - interpretations,
  - open questions,
  - current research direction,
  - pending/justified next move.
- Run 2 reconstructs a compact Scientist-facing state from those committed records.
- Run 2 can cite and reuse prior evidence without treating it as a new execution.
- Prior exposure and invalidation status are preserved where already supported by current contracts.

**Explicitly defer**
- Research Graph.
- General cross-run planner.
- Full candidate lifecycle across many Studies.
- General transitive stale-state engine.
- Complex Program-wide exposure machinery beyond what is required for the pilot.
- Persistent manuscript lifecycle.
- Procedural memory/lesson store.

**Proof case**

```text
Run 1
  → evidence
  → interpretation
  → unresolved question / next move
  → stop

Program state persists

Run 2
  → resumes from prior understanding
  → does not repeat resolved work
  → uses prior evidence with original standing
  → continues the inquiry
```

**Exit criteria**
- A second Run demonstrably continues the same scientific inquiry.
- Prior evidence is reused with correct identity/provenance rather than copied or reinterpreted as fresh evidence.
- The implementation is still simple enough that the next persistence requirements can be learned from real use.

---

## Expand from Observed Scientific Gaps

**Goal:** Move toward the full architecture only where real E2E behavior demonstrates a missing capability.

Do not define a fixed feature sequence. Use failures and limitations observed in M3-M5 to choose the next capability.

**Examples**
- Missing or unverifiable prior work repeatedly limits reasoning → add Literature capability.
- Current evidence cannot discriminate important rivals → add New Data / Replication capability.
- Claims require stronger independent evidence → add Locked Validation.
- Writing repeatedly exposes unsupported claims or contradictions → add persistent Manuscript / Review.
- State becomes difficult to query from committed records → consider a Research Graph/index.
- Sequential execution becomes a measured bottleneck → consider parallel branches or specialized agents.

**Rule for every expansion**

```text
Observed capability gap
        ↓
Smallest mechanism that addresses it
        ↓
E2E / evaluation
        ↓
Keep, revise, or remove
```

**Exit criteria**
- New architecture is added only when it solves a demonstrated scientific limitation.
- Replaceable strategies remain replaceable; they do not become core merely because they were implemented.

---
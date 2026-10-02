"""Scientific declarations and immutable lifecycle records."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, JsonValue, StringConstraints, ValidationInfo, model_validator

from popper.harness.records import ArtifactRef, MeasurementRef, Record
from popper.harness.session import Harness

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Standing = Literal["supported", "not_supported", "inconclusive", "unavailable", "post_hoc"]
Fidelity = Literal["consistent", "defect", "unresolved"]
Action = Literal[
    "test",
    "technical_repair",
    "measurement_repair",
    "refine",
    "stop",
    "pivot",
    "reframe",
    "acquisition",
]


class MethodSpec(Record):
    family: Text
    description: Text
    algorithm: Text | None = None
    implementation_ref: ArtifactRef | None = None
    inputs: list[Text] = Field(min_length=1)
    outputs: list[Text] = Field(min_length=1)
    effect_scale: Text
    assumptions: list[Text] = Field(default_factory=list)
    diagnostics: list[Text] = Field(default_factory=list)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def custom_algorithm(self) -> Self:
        if self.family == "custom" and not self.algorithm:
            raise ValueError("custom methods require an explicit algorithm")
        return self


class SupportRule(Record):
    kind: Literal["directional_ci", "equivalence_ci", "descriptive"]
    result_key: Text
    interval_level: float = Field(gt=0, lt=1, allow_inf_nan=False)
    null: Finite | None = None
    direction: Literal["positive", "negative"] | None = None
    lower: Finite | None = None
    upper: Finite | None = None
    description: Text | None = None

    @model_validator(mode="after")
    def valid_rule(self) -> Self:
        if self.kind == "directional_ci" and (self.null is None or self.direction is None):
            raise ValueError("directional rule requires null and direction")
        if self.kind == "equivalence_ci" and (
            self.lower is None or self.upper is None or self.lower >= self.upper
        ):
            raise ValueError("equivalence rule requires ordered finite bounds")
        if self.kind == "descriptive" and self.description is None:
            raise ValueError("descriptive rule requires description")
        return self


class PrimaryEstimand(Record):
    outcome: Text
    exposure: Text
    contrast: Text
    comparison: Literal["difference", "ratio"]
    population: Text
    unit: Text


class CandidateProposal(Record):
    statement: Text
    rationale: Text
    primary_estimand: PrimaryEstimand
    expected_direction: Literal["positive", "negative"]
    refuting_result: Text
    planned_test: Text
    methods: list[MethodSpec] = Field(min_length=1)
    assumptions: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def checked_roles(self, info: ValidationInfo) -> Self:
        primary = self.primary_estimand
        columns = (info.context or {}).get("columns")
        if primary.outcome == primary.exposure or (
            columns is not None
            and any(c not in columns for c in (primary.outcome, primary.exposure))
        ):
            raise ValueError("distinct outcome and exposure must identify processed columns")
        return self


class Candidate(CandidateProposal):
    id: Text
    origins: list[ArtifactRef] = Field(min_length=1)
    exposure: list[ArtifactRef] = Field(min_length=1)
    warnings: list[Text] = Field(default_factory=list)


class TestProposal(Record):
    primary_estimand: PrimaryEstimand
    selection: dict[str, JsonValue]
    preparation: ArtifactRef
    methods: list[MethodSpec] = Field(min_length=1)
    inference: dict[str, JsonValue]
    adjustment: list[Text] = Field(default_factory=list)
    requested_coverage: dict[str, JsonValue]
    outputs: list[Text] = Field(min_length=1)
    support_rule: SupportRule | None = None
    sources: list[ArtifactRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_outputs(self) -> Self:
        if "estimand.json" not in self.outputs or not any(
            k != "estimand.json" for k in self.outputs
        ):
            raise ValueError("test requires estimand manifest and named measurements")
        if self.support_rule and self.support_rule.result_key not in self.outputs:
            raise ValueError("support rule must name a declared output")
        return self


class TestSpec(TestProposal):
    version: Literal[1] = 1
    id: Text
    hypothesis_id: Text
    parent_test: ArtifactRef | None = None


def classify_change(before: TestSpec, after: TestSpec) -> Literal["same_test", "refine", "pivot"]:
    if before.primary_estimand != after.primary_estimand:
        return "pivot"
    excluded = {"id", "version", "hypothesis_id", "parent_test", "sources"}
    return (
        "same_test"
        if before.model_dump(exclude=excluded) == after.model_dump(exclude=excluded)
        else "refine"
    )


class CheckObservation(Record):
    category: Literal["technical", "measurement", "integrity"]
    requirement: Text
    passed: bool
    sources: list[ArtifactRef]
    reason: Text


class FidelityAssessment(Record):
    status: Fidelity
    author: Text
    reason: Text
    requirements: list[Text] = Field(min_length=1)
    sources: list[ArtifactRef] = Field(min_length=1)


class Diagnosis(Record):
    version: Literal[1] = 1
    category: Literal["technical", "measurement", "scientific", "integrity", "resource"]
    observation_refs: list[ArtifactRef] = Field(min_length=1)
    author: Text
    reason: Text
    affected_refs: list[ArtifactRef] = Field(default_factory=list)
    affected_roles: list[Text] = Field(default_factory=list)


class Question(Record):
    version: Literal[1] = 1
    hypothesis_id: Text
    text: Text
    author: Text
    sources: list[ArtifactRef] = Field(min_length=1)
    resolved: bool = False


class Disposition(Record):
    version: Literal[1] = 1
    kind: Literal["deferred", "stopped", "rejected"]
    reason: Text
    sources: list[ArtifactRef] = Field(default_factory=list)
    hypothesis_id: str | None = None
    resource: bool = False


class MoveProposal(Record):
    action: Action
    objective: Text
    trigger_refs: list[ArtifactRef] = Field(min_length=1)
    hypothesis_id: str | None = None
    test: ArtifactRef | None = None
    test_proposal: TestProposal | None = None
    discriminating_outcomes: list[Text] = Field(default_factory=list)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    execution_effort: int = Field(default=1, ge=0)
    assumptions: list[Text] = Field(default_factory=list)
    exposure: list[ArtifactRef] = Field(default_factory=list)
    stopping_condition: Text
    diagnosis: ArtifactRef | None = None
    changed_fields: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def executable_fields(self) -> Self:
        if self.action not in {"stop", "pivot", "reframe", "acquisition"}:
            if (
                not self.hypothesis_id
                or not self.discriminating_outcomes
                or (self.test is None and self.test_proposal is None)
            ):
                raise ValueError(
                    "executable move requires hypothesis, test and discriminating outcomes"
                )
        return self


class ResearchMove(MoveProposal):
    version: Literal[1] = 1
    id: Text
    snapshot: ArtifactRef


class MoveSelection(Record):
    version: Literal[1] = 1
    proposal_id: Text
    snapshot: ArtifactRef
    proposals: ArtifactRef
    author: Text
    rationale: Text


class Attempt(Record):
    version: Literal[1] = 1
    id: Text
    move: ArtifactRef
    move_id: Text
    hypothesis_id: Text
    test: ArtifactRef
    parent: ArtifactRef | None
    diagnosis: ArtifactRef | None
    changed_fields: list[Text]
    stage_instances: dict[str, str]
    reuse: dict[str, ArtifactRef] = Field(default_factory=dict)
    move_count: int
    revisit_count: int
    exposure: list[ArtifactRef]


class AcceptedMeasurement(Record):
    ref: MeasurementRef
    role: Text
    interval_level: float | None
    fidelity: FidelityAssessment
    support: Standing
    rule_precedes_execution: bool


class AttemptResult(Record):
    version: Literal[1] = 1
    attempt: ArtifactRef
    hypothesis_id: Text
    test: ArtifactRef
    measurements: list[AcceptedMeasurement]
    stages: dict[str, ArtifactRef]
    variant_tests: list[ArtifactRef] = Field(default_factory=list)
    checks: list[CheckObservation] = Field(default_factory=list)
    diagnoses: list[ArtifactRef] = Field(default_factory=list)
    coverage: dict[str, JsonValue]
    sensitivity: dict[str, JsonValue]
    status: Literal["complete", "partial", "failed"]


class Invalidation(Record):
    version: Literal[1] = 1
    measurements: list[MeasurementRef] = Field(min_length=1)
    diagnosis: ArtifactRef
    superseded_by: ArtifactRef | None = None


def commit_record(
    h: Harness, kind: str, record: Record | dict[str, Any], *, key: str | None = None
) -> ArtifactRef:
    name = f"science:{kind}" + (f":{key}" if key else "")
    if key and h.run.committed(name):
        return h.run.artifact_ref(name)
    folder = h.run.new_attempt(f"discover/{kind}")
    rel = folder.relative_to(h.run.root).as_posix()
    data = record.model_dump(mode="json") if isinstance(record, Record) else record
    path = h.run.write_json(f"{rel}/{kind}.json", data)
    h.run.commit_artifact(name, path)
    return h.run.artifact_ref(name)

"""Scientific views over committed records."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from popper.harness.storage.records import ArtifactRef, IntegrityError, resolve_artifact
from popper.harness.storage.recovery import read_events
from popper.harness.storage.store import file_hash
from popper.scientific.runtime.data.research import ResearchContext
from popper.scientific.runtime.store import ScienceStore


@dataclass(frozen=True)
class ReviewedFrame:
    source: ArtifactRef
    research: ResearchContext
    framing: dict[str, Any]


@dataclass(frozen=True)
class FoundationView:
    source: ArtifactRef
    preparation: Path
    facts: dict[str, Any]


@dataclass(frozen=True)
class ExplorationView:
    source: ArtifactRef
    id: str
    results: dict[str, Any]
    analysis: str
    figures: list[str]


def latest(science: ScienceStore, *names: str) -> str | None:
    return next((name for name, _ in reversed(science.commits()) if name in names), None)


def reviewed_frame(science: ScienceStore, source: ArtifactRef | None = None) -> ReviewedFrame:
    ref = source or science.run.artifact_ref("frame_reviewed")
    path = resolve_artifact(science.run, ref)
    research = ResearchContext.model_validate_json((path.parent / "research.json").read_bytes())
    return ReviewedFrame(ref, research, science.read(ref))


def foundation_view(science: ScienceStore, source: ArtifactRef | None = None) -> FoundationView:
    ref = source or science.run.artifact_ref("foundation")
    path = resolve_artifact(science.run, ref)
    record = science.read(ref)
    facts = {
        name: json.loads((path.parent / f"{name}.json").read_text("utf-8"))
        for name in ("operationalization", "concerns", "readiness")
    }
    facts["attempt"] = path.parent.name
    return FoundationView(ref, science.run.path(record["preparation"]), facts)


def node_ref(science: ScienceStore, path: Path) -> ArtifactRef:
    relative = path.relative_to(science.run.root).as_posix()
    event = next(
        e
        for e in reversed(read_events(science.run.root))
        if e["event"] == "node_commit" and e["path"] == relative
    )
    ref = ArtifactRef(
        path=relative, sha256=event["sha256"], producer="node", record_id=event["record_id"]
    )
    resolve_artifact(science.run, ref)
    return ref


def node_results(science: ScienceStore, ref: ArtifactRef) -> dict[str, Any]:
    metadata = science.read(ref)
    path = (Path(ref.path).parent / "execution" / "results.json").as_posix()
    expected = metadata.get("outputs", {}).get(path)
    if expected is None:
        raise IntegrityError("node has no committed results")
    result = ArtifactRef(
        path=path,
        sha256=expected,
        producer=ref.producer,
        record_id=ref.record_id,
        backing=ref,
    )
    return science.read(result)


def record_exploration(science: ScienceStore, ref: ArtifactRef, *, admission: ArtifactRef | None = None) -> ArtifactRef:
    if science.run.committed("exploration"):
        return science.run.artifact_ref("exploration")
    folder = resolve_artifact(science.run, ref).parent
    path = science.run.write_json(
        "inputs/exploration.json",
        {
            "files": {
                p.relative_to(science.run.root).as_posix(): file_hash(p)
                for p in folder.rglob("*")
                if p.is_file()
                and (
                    p.is_relative_to(folder / "execution")
                    or p in {folder / "meta.json", folder / "analysis.md"}
                )
            },
            "node": science.read(ref)["id"],
            **({"admission": admission.model_dump(mode="json")} if admission else {}),
        },
    )
    science.run.commit_artifact("exploration", path)
    if admission:
        from popper.scientific.runtime.lifecycle.transitions import bind_stage_output
        bind_stage_output(science, admission, [science.run.artifact_ref("exploration")])
    return science.run.artifact_ref("exploration")


def exploration_view(science: ScienceStore, source: ArtifactRef | None = None) -> ExplorationView:
    source = source or science.run.artifact_ref("exploration")
    manifest = science.read(source)
    path = next(p for p in manifest["files"] if p.endswith("/meta.json"))
    ref = node_ref(science, science.run.path(path))
    metadata = science.read(ref)
    return ExplorationView(
        source,
        metadata["id"],
        node_results(science, ref),
        metadata["analysis"],
        metadata["figures"],
    )


def validate_intent_inputs(science: ScienceStore, intent: ArtifactRef) -> None:
    """Reject changed upstream inputs independently of the scientific frontier."""
    captured = science.read(intent)
    try:
        refs = {name: ArtifactRef.model_validate(captured[name]) for name in (
            "frame", "foundation", "preparation", "exploration"
        )}
        for name, ref in refs.items():
            resolve_artifact(science.run, ref)
            current = science.run.artifact_ref("frame_reviewed" if name == "frame" else name)
            if ref != current:
                raise IntegrityError(f"intent {name} differs from current committed input")
        manifest = science.read(refs["preparation"])
        if ArtifactRef.model_validate(manifest["foundation"]) != refs["foundation"]:
            raise IntegrityError("intent preparation cites a different foundation")
        foundation = science.read(refs["foundation"])
        preparation = science.run.path(foundation["preparation"])
        mount = manifest["mounts"]["data"]
        if science.run.path(mount["path"]) != preparation / "processed.parquet":
            raise IntegrityError("intent preparation data mount differs from its foundation")
        if manifest["files"].get(mount["path"]) != mount["sha256"]:
            raise IntegrityError("intent preparation data mount is not hash-backed")
        for path, digest in manifest["files"].items():
            resolve_artifact(science.run, ArtifactRef(
                path=path, sha256=digest, producer=refs["preparation"].producer,
                record_id=refs["preparation"].record_id, backing=refs["preparation"],
            ))
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError(f"invalid committed intent inputs: {exc}") from exc

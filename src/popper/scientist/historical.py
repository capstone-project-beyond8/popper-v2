"""Scientific selection of historical alternative analyses."""

import json
from pathlib import Path
from typing import Any

from popper.harness.records import ArtifactRef
from popper.harness.session import Harness
from popper.science.historical import RobustnessPlan, schedule_context
from popper.science.settings import load_options
from popper.science.store import ScienceStore


def plan_robustness(
    h: Harness, hypothesis: dict[str, Any], main: ArtifactRef, preparation: Path
) -> Path:
    science = ScienceStore(h.run)
    committed = h.run.committed("robustness_plan")
    if committed:
        return committed
    context = schedule_context(h.config.search, load_options(h.run).robustness)
    proposal = h.ask_model(
        "theorist",
        schema=RobustnessPlan,
        tag="robustness_plan",
        system="You are a careful research scientist. Reply with JSON only.",
        prompt=(
            f"Plan a bounded multiverse for this hypothesis:\n{json.dumps(hypothesis)}\n"
            f"Recorded data changes:\n{(preparation / 'changes.json').read_text('utf-8')}\n"
            f"Use at most {context['steps']} attempts, at least {load_options(h.run).robustness.min_variants} ordinary variants "
            "and one adversarial permutation of the exposure; one stage step is reserved for repair. "
            "Cover cleaning, model, subgroup and resampling, "
            "or record an inapplicable reason. Code keeps the declared outcome, exposure, "
            "contrast and units; subgroup variants give population (the restricted population), other variants omit it. "
            "Do not select choices to obtain significance. "
            "Every ordinary choice must change an actual decision in the main analysis, not repeat it. "
            "For cleaning, name the existing rule being changed and the alternative; applying all "
            "existing cleaning steps unchanged is not a variant. If no defensible alternative exists, "
            "record an inapplicable reason. State whether a log transformation targets the exposure "
            "or the outcome. Keep each script feasible within "
            f"{h.config.execution.timeout_seconds} seconds. Avoid nested bootstrap x imputation "
            "workloads with tens of thousands of fits; choose a justified affordable design or mark "
            "it inapplicable. Do not remove missingness uncertainty just to save time. "
            "Return {attempts: [{id, kind: variant|adversarial, dimension: cleaning|model|subgroup|resampling|adversarial, "
            "choice, methods: [operations this variant uses, from the allowed method values; empty if none], "
            "population (subgroup variants only), "
            "result_key: primary_estimate|placebo_estimate, seed: 7}], inapplicable: {dimension: reason}}. "
            "Adversarial choice must be exactly permutation. Do not include estimates or a label."
        ),
        validation_context=context,
    )
    destination = h.run.new_attempt("discover/robustness").relative_to(h.run.root).as_posix()
    path = h.run.write_json(
        f"{destination}/robustness_plan.json",
        {
            "format_version": 2,
            "main_node": science.read(main)["id"],
            "schedule": proposal.model_dump(mode="json"),
        },
    )
    h.run.commit_artifact("robustness_plan", path)
    return path

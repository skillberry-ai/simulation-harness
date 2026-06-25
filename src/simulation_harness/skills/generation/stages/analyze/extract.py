"""Stage 1a: component schemas → data model (entities + store_metadata)."""

from __future__ import annotations

import json
from dataclasses import dataclass

try:
    from importlib.resources import files
except ImportError:  # pragma: no cover
    from importlib_resources import files  # type: ignore[import-not-found]

from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.llm import call_json
from simulation_harness.skills.generation.repair import with_repair


def _load_prompt() -> str:
    assets = files("simulation_harness.skills.assets")
    return (assets / "generation" / "extract.md").read_text()


@dataclass
class DataModel:
    api_name: str
    entities: list[Entity]
    store_metadata: StoreMetadata


class _Invalid:
    """Sentinel carrying shape errors so repair can re-prompt (never validates clean)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors


def validate_data_model(dm: DataModel) -> list[str]:
    errors: list[str] = []
    declared = set(dm.store_metadata.collections)
    for e in dm.entities:
        if e.collection not in declared:
            errors.append(
                f"entity '{e.name}' collection '{e.collection}' missing from "
                f"store_metadata.collections"
            )
    for coll in dm.store_metadata.pk_map:
        if coll not in declared:
            errors.append(
                f"pk_map collection '{coll}' is not in store_metadata.collections"
            )
    return errors


async def extract_data_model(
    components: dict, slug: str, llm, *, retries: int
) -> DataModel:
    prompt = _load_prompt()
    base_user = (
        f"# Component schemas\n```json\n{json.dumps(components, indent=2)}\n```\n"
    )

    async def produce(feedback):
        user = base_user + (
            "\n# feedback\n" + "\n".join(feedback) + "\n" if feedback else ""
        )
        payload = await call_json(llm, prompt, user)
        try:
            if not isinstance(payload, dict):
                return _Invalid(["extract payload must be a JSON object"])
            return DataModel(
                api_name=payload.get("api_name", slug),
                entities=[Entity(**e) for e in payload.get("entities", [])],
                store_metadata=StoreMetadata(**payload["store_metadata"]),
            )
        except Exception as e:  # malformed shape (missing store_metadata, bad field, …)
            return _Invalid([f"data-model shape error: {e}"])

    def validate(artifact):
        if isinstance(artifact, _Invalid):
            return artifact.errors
        return validate_data_model(artifact)

    return await with_repair(produce, validate, stage="extract", retries=retries)

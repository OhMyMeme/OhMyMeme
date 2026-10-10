"""Generate deterministic JSON Schema and shared TypeScript bridge DTOs."""

import json
import subprocess
import tempfile
from argparse import ArgumentParser
from pathlib import Path

from ohmymeme.core.schemas.bridge import BRIDGE_SCHEMA_MODELS

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "bridge" / "bridge.schema.json"
DTO_PATHS = (
    ROOT / "src/ohmymeme/presentation/frontend/main/shared/generated/bridge.ts",
)


def _schema() -> dict:
    definitions = {}
    for model in BRIDGE_SCHEMA_MODELS:
        payload = model.model_json_schema(ref_template="#/$defs/{model}")
        definitions[model.__name__] = {
            key: value for key, value in payload.items() if key != "$defs"
        }
        definitions.update(payload.get("$defs", {}))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ohmymeme.local/schemas/bridge.schema.json",
        "title": "OhMyMemeBridgePayload",
        "type": "object",
        "additionalProperties": {"$ref": "#/$defs/JsonValue"},
        "$defs": definitions,
    }


def _schema_bytes() -> bytes:
    return json.dumps(
        _schema(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _render_dto(schema_path: Path, main_path: Path) -> bytes:
    subprocess.run(
        [
            "npm",
            "exec",
            "json2ts",
            "--",
            "-i",
            str(schema_path),
            "-o",
            str(main_path),
            "--unknownAny",
            "--unreachableDefinitions",
        ],
        cwd=ROOT,
        check=True,
    )
    dto_bytes = main_path.read_bytes().replace(b"\r\n", b"\n")
    main_path.write_bytes(dto_bytes)
    return dto_bytes


def _write_outputs() -> None:
    schema_bytes = _schema_bytes()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_bytes(schema_bytes)
    main_path = DTO_PATHS[0]
    main_path.parent.mkdir(parents=True, exist_ok=True)
    dto_bytes = _render_dto(SCHEMA_PATH, main_path)
    for destination in DTO_PATHS[1:]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(dto_bytes)


def _check_outputs() -> bool:
    expected_schema = _schema_bytes()
    with tempfile.TemporaryDirectory(prefix="ohmymeme-bridge-schema-") as directory:
        root = Path(directory)
        schema_path = root / "bridge.schema.json"
        dto_path = root / "bridge.ts"
        schema_path.write_bytes(expected_schema)
        dto_bytes = _render_dto(schema_path, dto_path)
    return SCHEMA_PATH.read_bytes() == expected_schema and all(
        path.read_bytes() == dto_bytes for path in DTO_PATHS
    )


def main() -> None:
    """Write all bridge schema and DTO outputs."""
    parser = ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if not _check_outputs():
            raise SystemExit("generated bridge schema or DTO drift")
        return
    _write_outputs()


if __name__ == "__main__":
    main()

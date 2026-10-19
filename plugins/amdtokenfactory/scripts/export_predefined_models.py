"""Generate stock-Dify model YAMLs from an anonymous public catalog snapshot."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml
from dify_plugin.entities.model import AIModelEntity

sys.path.insert(0, str(Path(__file__).resolve().parent))
from excluded_models import EXCLUDED_MODELS  # noqa: E402
from model_catalog import fetch_public_catalog, parse_public_catalog  # noqa: E402

GENERATED_HEADER = "# Generated from the public AMD Token Factory catalog; do not edit by hand.\n"


def render_models(models: list[dict]) -> dict[str, str]:
    models = [model for model in models if model.get("model") not in EXCLUDED_MODELS]
    if not models:
        raise ValueError("Public catalog contains no eligible chat models")
    files = {}
    identities = set()
    for model in models:
        entity = AIModelEntity.model_validate(model)
        if entity.model_type.value != "llm" or entity.model in identities:
            raise ValueError("Invalid or duplicate predefined model identity")
        identities.add(entity.model)
        # A digest filename avoids traversal, punctuation collisions and platform
        # restrictions. The actual service ID is preserved inside the YAML.
        filename = "catalog-" + hashlib.sha256(entity.model.encode()).hexdigest()[:16] + ".yaml"
        if filename in files:
            raise ValueError("Predefined model filename collision")
        files[filename] = GENERATED_HEADER + yaml.safe_dump(
            model, allow_unicode=True, sort_keys=False
        )
    return files


def export_models(output: Path, models: list[dict], *, check: bool = False) -> None:
    files = render_models(models)
    if output.is_symlink():
        raise ValueError("Refusing a symlink output directory")
    existing = set(output.glob("catalog-*.yaml"))
    if any(path.is_symlink() or not path.is_file() for path in existing):
        raise ValueError("Refusing a non-regular generated model file")
    if any(not path.read_text(encoding="utf-8").startswith(GENERATED_HEADER) for path in existing):
        raise ValueError("Refusing to replace an unrecognized model file")
    if check:
        actual = {path.name: path.read_text(encoding="utf-8") for path in existing}
        if actual != files:
            raise ValueError("Predefined model snapshot differs; regenerate before packaging")
        return
    output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = output / name
        if target.is_symlink():
            raise ValueError("Refusing a symlink model file")
        target.write_text(content, encoding="utf-8")
    for path in existing:
        if path.name not in files:
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Previously captured anonymous catalog JSON")
    parser.add_argument("--output", type=Path, default=Path("models/llm"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    models = (
        parse_public_catalog(json.loads(args.input.read_text(encoding="utf-8")))
        if args.input else fetch_public_catalog()
    )
    export_models(args.output, models, check=args.check)
    count = len(render_models(models))
    print(f"PASS: {count} predefined chat models; no API Key or model invocation")


if __name__ == "__main__":
    main()
import hashlib
from pathlib import Path
from unittest.mock import Mock

import yaml
from dify_plugin.core.model_factory import ModelFactory
from dify_plugin.entities.model import AIModelEntity, ModelFeature, ModelType
from dify_plugin.entities.model.provider import ModelProviderConfiguration
from model_catalog import parse_catalog
from test_catalog import remote_model

from models.llm.llm import AMDTokenFactoryLargeLanguageModel
from provider.amdtokenfactory import AMDTokenFactoryModelProvider
from scripts.export_predefined_models import (
    EXCLUDED_MODELS,
    export_models,
    render_models,
)

ROOT = Path(__file__).resolve().parents[1]


def test_stock_sdk_loads_packaged_predefined_models_without_network(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("requests.get", Mock(side_effect=AssertionError("no network")))
    monkeypatch.setattr("requests.post", Mock(side_effect=AssertionError("no network")))
    schema = ModelProviderConfiguration.model_validate(yaml.safe_load(
        (ROOT / "provider/amdtokenfactory.yaml").read_text(encoding="utf-8")
    ))
    assert schema.models
    factory = ModelFactory(schema, {ModelType.LLM: AMDTokenFactoryLargeLanguageModel})
    provider = AMDTokenFactoryModelProvider(schema, factory)
    listed = provider.models(ModelType.LLM)
    assert len(listed) == 7
    assert "Qwen3.8-27B" in {m.model for m in listed}
    vision = {m.model for m in listed if ModelFeature.VISION in (m.features or [])}
    assert vision == {
        "DeepSeek-V4.1-Flash", "MiMo-V2.6-Flash", "Qwen3.8-Flash-Next",
        "Qwen3.8-27B", "Gemma-4-31B-IT",
    }
    assert not EXCLUDED_MODELS.intersection(m.model for m in listed)
    assert {m.model for m in listed} == {m.model for m in schema.models}
    assert len(listed) == len(list((ROOT / "models/llm").glob("catalog-*.yaml")))
    llm = provider.get_model_instance(ModelType.LLM)
    for entry in listed:
        assert llm.get_model_schema(entry.model, {}) == entry


def test_generator_preserves_ids_and_metadata_without_unsafe_filenames(tmp_path):
    models = parse_catalog({"data": [remote_model("vendor/model:one", vision=True)]})
    files = render_models(models)
    expected = "catalog-" + hashlib.sha256(b"vendor/model:one").hexdigest()[:16] + ".yaml"
    assert set(files) == {expected}
    data = yaml.safe_load(files[expected])
    assert data == models[0]
    assert AIModelEntity.model_validate(data).model == "vendor/model:one"
    export_models(tmp_path, models)
    export_models(tmp_path, models, check=True)
    export_models(tmp_path, parse_catalog({"data": [remote_model("new-model")]}))
    assert len(list(tmp_path.glob("*.yaml"))) == 1
    assert "new-model" in next(tmp_path.glob("*.yaml")).read_text(encoding="utf-8")

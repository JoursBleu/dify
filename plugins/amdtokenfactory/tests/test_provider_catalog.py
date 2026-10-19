"""The packaged provider lists only its predefined YAMLs and never fetches a catalog."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml
from dify_plugin.core.model_factory import ModelFactory
from dify_plugin.entities.model import ModelType
from dify_plugin.entities.model.provider import ModelProviderConfiguration

from models.llm.llm import AMDTokenFactoryLargeLanguageModel
from provider.amdtokenfactory import AMDTokenFactoryModelProvider

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.chdir(ROOT)
    schema = ModelProviderConfiguration.model_validate(yaml.safe_load(
        (ROOT / "provider/amdtokenfactory.yaml").read_text(encoding="utf-8")
    ))
    factory = ModelFactory(schema, {ModelType.LLM: AMDTokenFactoryLargeLanguageModel})
    return AMDTokenFactoryModelProvider(schema, factory)


def test_unpackaged_model_id_has_no_runtime_schema(provider, monkeypatch):
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("no POST")))
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("no GET")))
    llm = provider.get_model_instance(ModelType.LLM)
    credentials = {"api_key": "rc-offline-fixture"}
    assert llm.get_customizable_model_schema("not-packaged", credentials) is None
    assert llm.get_model_schema("not-packaged", credentials) is None


def test_package_runtime_does_not_import_the_public_catalog_client():
    for path in [*ROOT.glob("provider/*.py"), *ROOT.glob("models/**/*.py"), ROOT / "main.py"]:
        text = path.read_text(encoding="utf-8")
        assert "model_catalog" not in text and "tokenfactory/bootstrap" not in text, path
    assert not (ROOT / "models/_catalog.py").exists()

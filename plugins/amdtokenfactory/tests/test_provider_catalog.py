"""Provider override tests on released SDK; native RPC acceptance is separate."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml
from dify_plugin.entities.model import AIModelEntity, ModelType
from dify_plugin.entities.model.provider import ProviderEntity
from dify_plugin.errors.model import (
    InvokeAuthorizationError,
    InvokeConnectionError,
    InvokeError,
    InvokeRateLimitError,
    InvokeServerUnavailableError,
)
from test_catalog import remote_model, response

from model_catalog import MODELS_URL, clear_catalog_cache
from provider.amdtokenfactory import AMDTokenFactoryModelProvider


@pytest.fixture
def provider():
    root = Path(__file__).resolve().parents[1]
    schema = ProviderEntity.model_validate(yaml.safe_load(
        (root / "provider/amdtokenfactory.yaml").read_text()
    ))
    return AMDTokenFactoryModelProvider(schema, Mock())


@pytest.fixture(autouse=True)
def empty_cache():
    clear_catalog_cache()
    yield
    clear_catalog_cache()


def test_fetch_models_returns_every_new_chat_id_and_remote_metadata(provider, monkeypatch):
    rows = [remote_model(f"api-new-chat-{index}") for index in range(80)]
    rows.append(remote_model("api-new-vision", vision=True, name="Remote Vision",
                             max_output_tokens=12345))
    excluded = [
        remote_model("offline", status="offline"), remote_model("disabled", enabled=False),
        remote_model("deprecated", deprecated=True), remote_model("preview", status="preview"),
        remote_model("embedding", architecture={"input_modalities": ["text"],
                                                "output_modalities": ["embedding"]}),
        remote_model("ocr", providers=[{"ocr": True}]),
        remote_model("image-only", architecture={"input_modalities": ["image"],
                                                 "output_modalities": ["text"]}),
    ]
    reply = response({"data": rows + excluded})
    get = Mock(return_value=reply)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("no chat calls")))
    monkeypatch.setattr("provider.amdtokenfactory.validate_api_key",
                        Mock(side_effect=AssertionError("listing must not validate via chat")))
    models = provider.fetch_models(ModelType.LLM, {"api_key": "rc-fixture"})
    assert all(isinstance(model, AIModelEntity) for model in models)
    assert [model.model for model in models] == [row["id"] for row in rows]
    vision = models[-1]
    assert vision.label.en_us == vision.label.zh_hans == "Remote Vision"
    assert vision.model_type == ModelType.LLM
    assert {feature.value for feature in vision.features} == {
        "vision", "agent-thought", "tool-call", "stream-tool-call",
    }
    assert vision.model_dump(mode="json")["model_properties"] == {
        "mode": "chat", "context_size": 262144,
    }
    assert vision.fetch_from.value == "predefined-model"
    assert vision.deprecated is False
    assert vision.pricing.input == Decimal("0.035")
    assert vision.pricing.output == Decimal("0.07")
    assert vision.pricing.unit == Decimal("0.000001")
    assert vision.pricing.currency == "USD"
    rules = {rule.name: rule for rule in vision.parameter_rules}
    assert rules["max_tokens"].max == 12345
    assert rules["max_tokens"].default == 4096
    assert rules["response_format"].options == ["text", "json_object"]
    assert models[0].parameter_rules[0].max is None
    get.assert_called_once()
    assert get.call_args.args == (MODELS_URL,)
    assert get.call_args.kwargs["allow_redirects"] is False
    assert get.call_args.kwargs["headers"]["X-Source"] == "dify"
    reply.close.assert_called_once()


def test_fetch_models_shares_digest_cache_and_not_mutable_entities(provider, monkeypatch):
    get = Mock(side_effect=[response({"data": [remote_model("a")]}),
                           response({"data": [remote_model("b")]})])
    monkeypatch.setattr(requests, "get", get)
    models = provider.fetch_models(ModelType.LLM, {"api_key": "rc-a"})
    models[0].model = "mutated"
    assert provider.fetch_models(ModelType.LLM, {"api_key": " rc-a "})[0].model == "a"
    assert provider.fetch_models(ModelType.LLM, {"api_key": "rc-b"})[0].model == "b"
    assert get.call_count == 2


@pytest.mark.parametrize("model_type", [kind for kind in ModelType if kind != ModelType.LLM])
def test_non_llm_catalog_is_empty_without_credentials_or_network(provider, monkeypatch, model_type):
    get = Mock(side_effect=AssertionError("unsupported model type must not fetch"))
    monkeypatch.setattr(requests, "get", get)
    assert provider.fetch_models(model_type, {}) == []
    get.assert_not_called()


@pytest.mark.parametrize("reply,kind", [
    (response({}, 401), InvokeAuthorizationError),
    (response({}, 403), InvokeAuthorizationError),
    (response({}, 429), InvokeRateLimitError),
    (response({}, 302), InvokeConnectionError),
    (response({}, 503), InvokeServerUnavailableError),
    (response({"data": [remote_model(status={"private": "fixture"})]}),
     InvokeServerUnavailableError),
    (requests.ConnectionError("private fixture diagnostic"), InvokeConnectionError),
])
def test_fetch_models_reuses_sanitized_catalog_error_mapping(provider, monkeypatch, reply, kind):
    get = Mock(side_effect=reply) if isinstance(reply, Exception) else Mock(return_value=reply)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("no chat calls")))
    with pytest.raises(kind) as error:
        provider.fetch_models(ModelType.LLM, {"api_key": "rc-fixture"})
    assert "private" not in str(error.value)
    assert "rc-fixture" not in str(error.value)
    if not isinstance(reply, Exception):
        reply.close.assert_called_once()


def test_missing_credentials_is_mapped_before_network(provider, monkeypatch):
    get = Mock(side_effect=AssertionError("missing key must not fetch"))
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(InvokeAuthorizationError):
        provider.fetch_models(ModelType.LLM, {})
    get.assert_not_called()


def test_empty_remote_catalog_is_empty_not_a_fallback(provider, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=response({"data": []})))
    assert provider.fetch_models(ModelType.LLM, {"api_key": "rc-fixture"}) == []


def test_old_sdk_cannot_report_successful_provider_configuration(provider, monkeypatch):
    monkeypatch.delattr(AMDTokenFactoryModelProvider.__bases__[0], "fetch_models", raising=False)
    validate = Mock(side_effect=AssertionError("incompatible SDK must not validate via chat"))
    monkeypatch.setattr("provider.amdtokenfactory.validate_api_key", validate)
    with pytest.raises(InvokeError, match="native model catalog RPC"):
        provider.validate_provider_credentials({"api_key": "rc-offline-fixture"})
    validate.assert_not_called()


def test_paired_sdk_keeps_the_native_provider_validation(provider, monkeypatch):
    monkeypatch.setattr(
        AMDTokenFactoryModelProvider.__bases__[0], "fetch_models", Mock(), raising=False
    )
    validate = Mock()
    monkeypatch.setattr("provider.amdtokenfactory.validate_api_key", validate)
    credentials = {"api_key": "rc-offline-fixture"}
    provider.validate_provider_credentials(credentials)
    validate.assert_called_once_with(credentials)
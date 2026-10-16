"""Offline API/Core -> synthetic HTTP -> real SDK -> real plugin catalogue.

Run in the cached Dify API image with --confcutdir set to this directory,
network disabled, and read-only API/Graphon overlays, SDK src and plugin root
on PYTHONPATH. No app bootstrap, database, daemon process or real key is used.
The synthetic boundary models the daemon envelope, not the actual Go transport.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
import requests
import yaml
from flask import has_app_context
from pydantic import TypeAdapter
from yarl import URL

from configs import dify_config
from core.entities.model_entities import ModelStatus
from core.entities.provider_configuration import ProviderConfiguration
from core.entities.provider_entities import (
    CustomConfiguration,
    CustomProviderConfiguration,
    SystemConfiguration,
)
from core.plugin.entities.plugin_daemon import PluginModelProviderDeclaration
from core.plugin.impl import base as api_transport
from core.plugin.impl.model import PluginModelClient
from core.plugin.impl.model_runtime import PluginModelRuntime
from core.plugin.plugin_service import PluginService
from dify_plugin.config.config import DifyPluginEnv
from dify_plugin.core.entities.plugin.request import ModelActions, ModelFetchModelsRequest, PluginInvokeType
from dify_plugin.core.model_factory import ModelFactory
from dify_plugin.core.plugin_executor import PluginExecutor
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.core.runtime import Session
from dify_plugin.entities.model import AIModelEntity as SDKAIModelEntity
from dify_plugin.entities.model.provider import ModelProviderConfiguration
from extensions.ext_database import db
from graphon.model_runtime.entities.model_entities import AIModelEntity, ModelType
from models.provider import ProviderType

PLUGIN_ID = "amdtokenfactory/amdtokenfactory"
PROVIDER = f"{PLUGIN_ID}/amdtokenfactory"
PUBLIC_KEY = "rc-offline-fixture"
OTHER_PUBLIC_KEY = "rc-offline-fixture-other"
TENANT = "offline-tenant"
USER = "offline-user"


def remote_row(model: str, *, vision: bool = False, **overrides: object) -> dict:
    """Invent identities and metadata; never reuse a live catalogue snapshot."""
    return {
        "id": model,
        "name": model,
        "architecture": {
            "input_modalities": ["text", "image"] if vision else ["text"],
            "output_modalities": ["text"],
        },
        "context_length": 262144,
        "supported_parameters": ["max_tokens", "temperature", "top_p", "tools", "response_format"],
        "providers": [{"reasoning": True, "tools": True, "streaming": True, "ocr": False}],
        "pricing": {"prompt": "3.5e-8", "completion": "7e-8"},
        "json_output": True,
        **overrides,
    }


class DaemonEnvelopeStream(httpx.SyncByteStream):
    """A standard success envelope exposed as an iterator, with EOF/close proof."""

    def __init__(self, catalog: dict) -> None:
        self.content = (
            "data: " + json.dumps({"code": 0, "message": "", "data": catalog}) + "\n\n"
        ).encode()
        self.eof = False
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield self.content
        self.eof = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def integrated_catalog(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    # Dify's regular models package hides the plugin's namespace package.
    # Extend only the test interpreter's search path, retaining real API models.
    import models as api_models
    import model_catalog as catalog
    import dify_plugin

    plugin_root = Path(catalog.__file__).resolve().parent
    assert (plugin_root / "provider/amdtokenfactory.yaml").is_file()
    assert Path(dify_plugin.__file__).resolve().parent.parent.name == "src"
    monkeypatch.setattr(api_models, "__path__", [*api_models.__path__, str(plugin_root / "models")])
    provider_module = importlib.import_module("provider.amdtokenfactory")
    adapter_module = importlib.import_module("models._catalog")
    assert Path(provider_module.__file__).resolve() == plugin_root / "provider/amdtokenfactory.py"
    assert Path(adapter_module.__file__).resolve() == plugin_root / "models/_catalog.py"

    raw = yaml.safe_load((plugin_root / "provider/amdtokenfactory.yaml").read_text())
    sdk_schema = ModelProviderConfiguration.model_validate(deepcopy(raw))
    api_schema = PluginModelProviderDeclaration.model_validate({
        **sdk_schema.model_dump(mode="json"),
        "provider": PROVIDER,
        "provider_name": "amdtokenfactory",
        "plugin_unique_identifier": f"{PLUGIN_ID}:0.0.11@offline-fixture",
        "installation_source": None,
    })
    factory = ModelFactory(sdk_schema, {})
    provider = provider_module.AMDTokenFactoryModelProvider(sdk_schema, factory)
    forbidden_factory = Mock(side_effect=AssertionError("Catalogue must not instantiate a model"))
    forbidden_static = Mock(side_effect=AssertionError("Catalogue must not read static models"))
    forbidden_validate = Mock(side_effect=AssertionError("Catalogue must not perform key validation"))
    monkeypatch.setattr(factory, "get_instance", forbidden_factory)
    monkeypatch.setattr(provider, "models", forbidden_static)
    monkeypatch.setattr(provider_module, "validate_api_key", forbidden_validate)
    registration = Mock(spec=PluginRegistration)
    registration.get_model_provider_instance.return_value = provider
    registration.get_model_instance.side_effect = AssertionError("No per-model SDK registration lookup")
    sdk_executor = PluginExecutor(DifyPluginEnv.model_construct(), registration)
    upstream_get = Mock()
    monkeypatch.setattr(requests, "get", upstream_get)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("No inference requests")))
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("No real HTTP requests")))
    discovery = Mock(return_value=[api_schema])
    monkeypatch.setattr(PluginService, "fetch_plugin_model_providers", discovery)
    monkeypatch.setattr(api_transport, "plugin_daemon_inner_api_baseurl", URL("http://synthetic-daemon.invalid"))
    monkeypatch.setattr(dify_config, "PLUGIN_DAEMON_KEY", PUBLIC_KEY)
    monkeypatch.setattr(dify_config, "ENABLE_OTEL", False)

    state = SimpleNamespace(
        raw=raw, sdk_schema=sdk_schema, schema=api_schema, provider=provider,
        registration=registration, catalog=catalog, get=upstream_get,
        requests=[], sdk_results=[], streams=[], replies=[],
    )

    def reply(rows: list[dict]) -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"data": deepcopy(rows)}).encode()
        response._content_consumed = True
        response.close = Mock(wraps=response.close)
        state.replies.append(response)
        return response

    def configuration(credentials: dict | None) -> ProviderConfiguration:
        result = ProviderConfiguration(
            tenant_id=TENANT,
            provider=api_schema,
            preferred_provider_type=ProviderType.CUSTOM,
            using_provider_type=ProviderType.CUSTOM,
            system_configuration=SystemConfiguration(enabled=False),
            custom_configuration=CustomConfiguration(
                provider=CustomProviderConfiguration(credentials=credentials) if credentials is not None else None,
                models=[],
            ),
            model_settings=[],
        )
        result.bind_model_runtime(state.runtime)
        return result

    state.reply = reply
    state.configuration = configuration
    catalog.clear_catalog_cache()
    assert not has_app_context()
    assert not db._app_engines
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            session = Session("offline-session", worker, reader=Mock(), writer=Mock())

            def boundary(request: httpx.Request) -> httpx.Response:
                assert request.method == "POST"
                assert request.url.host == "synthetic-daemon.invalid"
                assert request.url.path == f"/plugin/{TENANT}/dispatch/model/list"
                assert request.headers["X-Plugin-ID"] == PLUGIN_ID
                assert request.headers["Content-Type"] == "application/json"
                assert request.headers["X-Api-Key"] == PUBLIC_KEY
                body = json.loads(request.content)
                assert set(body) == {"user_id", "data"}
                assert body["user_id"] == USER
                assert set(body["data"]) == {"provider", "model_type", "credentials"}
                # The synthetic daemon flattens HTTP dispatch data into the
                # real SDK action request, including its actual JSON parser.
                parsed = ModelFetchModelsRequest.model_validate_json(json.dumps({
                    **body["data"], "user_id": body["user_id"],
                    "type": "model", "action": "get_ai_model_list",
                }))
                assert parsed.type == PluginInvokeType.Model
                assert parsed.action == ModelActions.GetAIModelList
                assert parsed.provider == "amdtokenfactory"
                assert "model" not in parsed.model_dump()
                state.requests.append(parsed)
                result = sdk_executor.get_ai_model_list(session, parsed)
                assert all(isinstance(model, SDKAIModelEntity) for model in result["models"])
                serialized = TypeAdapter(dict[str, list[SDKAIModelEntity]]).dump_python(result, mode="json")
                state.sdk_results.append(serialized)
                stream = DaemonEnvelopeStream(serialized)
                state.streams.append(stream)
                return httpx.Response(200, stream=stream, headers={"Content-Type": "text/event-stream"})

            with httpx.Client(transport=httpx.MockTransport(boundary), trust_env=False) as http:
                monkeypatch.setattr(api_transport, "_httpx_client", http)
                state.client = PluginModelClient()
                state.runtime = PluginModelRuntime(TENANT, USER, state.client, PluginService)
                yield state
    finally:
        catalog.clear_catalog_cache()
        forbidden_factory.assert_not_called()
        forbidden_static.assert_not_called()
        forbidden_validate.assert_not_called()
        registration.get_model_instance.assert_not_called()
        assert api_schema.models == sdk_schema.models == []
        assert all(stream.eof and stream.closed for stream in state.streams)
        for response in state.replies:
            response.close.assert_called_once()
        for call in upstream_get.call_args_list:
            assert call.args == (catalog.MODELS_URL,)
            assert call.kwargs["headers"]["Authorization"] in {
                f"Bearer {PUBLIC_KEY}", f"Bearer {OTHER_PUBLIC_KEY}",
            }
            assert call.kwargs["headers"]["X-Source"] == "dify"
            assert call.kwargs["timeout"] == (10, 30)
            assert call.kwargs["stream"] is True
            assert call.kwargs["allow_redirects"] is False
        assert not has_app_context()
        assert not db._app_engines


def test_entire_unseen_catalog_and_capabilities_cross_real_sdk_and_core(integrated_catalog: SimpleNamespace) -> None:
    state = integrated_catalog
    prefix = f"offline-unseen-{uuid4().hex}"
    rows = [remote_row(f"{prefix}-{i}") for i in range(80)]
    rows.append(remote_row(f"{prefix}-vision", vision=True, name="Synthetic Vision", max_output_tokens=12345))
    rows.append(remote_row(f"{prefix}-conservative", providers=[
        {"reasoning": True, "tools": True, "streaming": True},
        {"reasoning": False, "tools": False, "streaming": False},
    ]))
    excluded = [
        remote_row(f"{prefix}-offline", status="offline"),
        remote_row(f"{prefix}-temporary", status="temp_offline"),
        remote_row(f"{prefix}-disabled", enabled=False),
        remote_row(f"{prefix}-deprecated", deprecated=True),
        remote_row(f"{prefix}-preview", status="preview"),
        remote_row(f"{prefix}-embedding", architecture={"input_modalities": ["text"], "output_modalities": ["embedding"]}),
        remote_row(f"{prefix}-ocr", providers=[{"ocr": True}]),
        remote_row(f"{prefix}-image-only", architecture={"input_modalities": ["image"], "output_modalities": ["text"]}),
    ]
    state.get.return_value = state.reply(rows + excluded)
    config = state.configuration({"api_key": PUBLIC_KEY})
    models = config.get_provider_models()
    assert [model.model for model in models] == [row["id"] for row in rows]
    assert len(models) == 82
    assert all(model.status == ModelStatus.ACTIVE and model.fetch_from.value == "predefined-model" for model in models)
    assert all(model.provider.provider == PROVIDER and model.model_type == ModelType.LLM for model in models)
    vision = models[-2]
    assert vision.label.en_us == vision.label.zh_hans == "Synthetic Vision"
    assert {feature.value for feature in vision.features} == {"vision", "agent-thought", "tool-call", "stream-tool-call"}
    assert "vision" not in {feature.value for feature in models[0].features}
    assert not models[-1].features
    assert vision.model_dump(mode="json")["model_properties"] == {"mode": "chat", "context_size": 262144}
    assert not vision.deprecated

    # The public API listing exposes capabilities, not pricing/parameter rules;
    # check that full SDK metadata survives real PluginModelClient/Core parsing.
    full = state.runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={"api_key": PUBLIC_KEY})
    assert all(isinstance(model, AIModelEntity) for model in full)
    metadata = full[-2]
    assert metadata.pricing.input == Decimal("0.035")
    assert metadata.pricing.output == Decimal("0.07")
    assert metadata.pricing.unit == Decimal("0.000001")
    assert metadata.pricing.currency == "USD"
    rules = {rule.name: rule for rule in metadata.parameter_rules}
    assert rules["max_tokens"].max == 12345
    assert rules["max_tokens"].default == 4096
    assert rules["response_format"].options == ["text", "json_object"]
    assert full[0].parameter_rules[0].max is None
    assert len(state.requests) == 2
    assert len(state.sdk_results[-1]["models"]) == len(rows)
    state.get.assert_called_once()
    assert config.custom_configuration.models == []
    assert config.custom_configuration.provider.credentials == {"api_key": PUBLIC_KEY}


def test_added_removed_ids_key_isolation_and_explicit_plugin_cache_clear(integrated_catalog: SimpleNamespace) -> None:
    state = integrated_catalog
    first = state.configuration({"api_key": PUBLIC_KEY})
    other = state.configuration({"api_key": OTHER_PUBLIC_KEY})
    state.get.side_effect = [
        state.reply([remote_row("offline-kept"), remote_row("offline-removed")]),
        state.reply([remote_row("offline-other-key-only")]),
        state.reply([remote_row("offline-kept"), remote_row("offline-added")]),
        state.reply([remote_row("offline-other-key-refreshed")]),
    ]
    original = first.get_provider_models()
    original[0].label.en_us = "mutated caller object"
    assert [model.model for model in other.get_provider_models()] == ["offline-other-key-only"]
    cached = first.get_provider_models()
    assert [model.model for model in cached] == ["offline-kept", "offline-removed"]
    assert cached[0].label.en_us == "offline-kept"
    assert state.get.call_count == 2
    assert len(state.requests) == 3  # Core re-dispatches; only the plugin owns its cache.
    assert len(state.catalog._cache) == 2
    assert all(len(key) == 64 and "rc-" not in key for key in state.catalog._cache)
    state.catalog.clear_catalog_cache()
    assert not state.catalog._cache and not state.catalog._pending
    assert [model.model for model in first.get_provider_models()] == ["offline-kept", "offline-added"]
    assert [model.model for model in other.get_provider_models()] == ["offline-other-key-refreshed"]
    assert state.get.call_count == 4
    assert [request.credentials for request in state.requests] == [
        {"api_key": PUBLIC_KEY}, {"api_key": OTHER_PUBLIC_KEY}, {"api_key": PUBLIC_KEY},
        {"api_key": PUBLIC_KEY}, {"api_key": OTHER_PUBLIC_KEY},
    ]


@pytest.mark.parametrize("credentials", [None, {}], ids=["no-provider-key", "empty-credentials"])
def test_missing_key_never_reaches_http_or_sdk(integrated_catalog: SimpleNamespace, credentials: dict | None) -> None:
    state = integrated_catalog
    state.get.side_effect = AssertionError("Missing credentials must not discover")
    assert state.configuration(credentials).get_provider_models() == []
    assert state.runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={}) == []
    assert state.requests == state.sdk_results == state.streams == []
    state.registration.get_model_provider_instance.assert_not_called()
    state.get.assert_not_called()


@pytest.mark.parametrize("key", ["", " "], ids=["empty-key", "blank-key"])
def test_empty_key_real_plugin_rejects_before_models_http(integrated_catalog: SimpleNamespace, key: str) -> None:
    state = integrated_catalog
    state.get.side_effect = AssertionError("An empty key must never reach /models")
    # A nonempty credentials mapping passes Core's presence check. Its empty
    # key is rejected by the actual provider, not a mocked catalogue method.
    with pytest.raises(ValueError, match="Unable to fetch remote model catalog"):
        state.configuration({"api_key": key}).get_provider_models()
    assert len(state.requests) == 1
    assert state.sdk_results == state.streams == []
    state.get.assert_not_called()


def test_all_removed_catalog_stays_empty_without_static_fallback(integrated_catalog: SimpleNamespace) -> None:
    state = integrated_catalog
    config = state.configuration({"api_key": PUBLIC_KEY})
    state.get.side_effect = [state.reply([remote_row("offline-now-removed")]), state.reply([])]
    assert [model.model for model in config.get_provider_models()] == ["offline-now-removed"]
    state.catalog.clear_catalog_cache()
    assert config.get_provider_models() == []
    assert state.sdk_results[-1] == {"models": []}
    assert len(state.requests) == state.get.call_count == 2


def test_real_provider_has_one_key_no_model_id_and_no_static_models(integrated_catalog: SimpleNamespace) -> None:
    state = integrated_catalog
    forms = state.sdk_schema.provider_credential_schema.credential_form_schemas
    assert [form.variable for form in forms] == ["api_key"]
    assert forms[0].required and forms[0].type.value == "secret-input"
    assert state.sdk_schema.model_credential_schema is None
    assert state.raw["models"] == {"llm": {"predefined": []}}
    assert state.schema.remote_model_catalog and state.sdk_schema.remote_model_catalog
    assert [method.value for method in state.schema.configurate_methods] == ["predefined-model"]
    assert state.schema.models == state.sdk_schema.models == []
    assert state.provider.model_factory.models == {}
    assert "model" not in ModelFetchModelsRequest.model_fields
    state.get.assert_not_called()
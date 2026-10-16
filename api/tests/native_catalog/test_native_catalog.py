"""Real Dify catalog owners with only network, cache and policy I/O isolated.

This suite deliberately lives outside unit_tests: those autouse fixtures create
a database and initialize application services. Run with --confcutdir pointing
at this directory. No app bootstrap or database initialization is needed here.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterator
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock, patch

import httpx
import pytest

from core.entities.model_entities import ModelStatus
from core.entities.provider_configuration import ProviderConfiguration
from core.entities.provider_entities import (
    CustomConfiguration,
    CustomModelConfiguration,
    CustomProviderConfiguration,
    ModelLoadBalancingConfiguration,
    ModelSettings,
    ProviderQuotaType,
    QuotaConfiguration,
    QuotaUnit,
    RestrictModel,
    SystemConfiguration,
)
from core.plugin.entities.plugin_daemon import (
    PluginDaemonBasicResponse,
    PluginModelProviderDeclaration,
    PluginModelProviderEntity,
    PluginModelSchemaEntity,
)
from core.plugin.impl.model import PluginModelClient
from core.plugin.impl.model_runtime import PluginModelRuntime
from core.plugin.plugin_service import PluginService
from graphon.model_runtime.entities.common_entities import I18nObject
from graphon.model_runtime.entities.model_entities import AIModelEntity, FetchFrom, ModelType
from graphon.model_runtime.entities.provider_entities import ConfigurateMethod, ProviderEntity
from models.provider import ProviderType

PROVIDER = "example/catalog/catalog"


def ai_model(name: str, model_type: ModelType = ModelType.LLM) -> AIModelEntity:
    return AIModelEntity(
        model=name,
        label=I18nObject(en_US=name),
        model_type=model_type,
        fetch_from=FetchFrom.PREDEFINED_MODEL,
        model_properties={},
    )


def declaration(remote: bool = True) -> PluginModelProviderDeclaration:
    return PluginModelProviderDeclaration(
        provider=PROVIDER,
        provider_name="catalog",
        label=I18nObject(en_US="Catalog"),
        supported_model_types=[ModelType.LLM, ModelType.TEXT_EMBEDDING],
        configurate_methods=[ConfigurateMethod.PREDEFINED_MODEL, ConfigurateMethod.CUSTOMIZABLE_MODEL],
        remote_model_catalog=remote,
        models=[ai_model("declared")],
        plugin_unique_identifier="example/catalog:0.0.1@synthetic",
        installation_source=None,
    )


def configuration(
    schema: ProviderEntity,
    runtime: PluginModelRuntime,
    credentials: dict[str, object] | None,
) -> ProviderConfiguration:
    result = ProviderConfiguration(
        tenant_id=runtime.tenant_id,
        provider=schema,
        preferred_provider_type=ProviderType.CUSTOM,
        using_provider_type=ProviderType.CUSTOM,
        system_configuration=SystemConfiguration(enabled=False),
        custom_configuration=CustomConfiguration(
            provider=CustomProviderConfiguration(credentials=credentials) if credentials is not None else None,
            models=[],
        ),
        model_settings=[],
    )
    result.bind_model_runtime(runtime)
    return result


@pytest.fixture
def schema() -> PluginModelProviderDeclaration:
    return declaration()


@pytest.fixture
def client() -> PluginModelClient:
    return PluginModelClient()


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, schema: ProviderEntity, client: PluginModelClient) -> PluginModelRuntime:
    monkeypatch.setattr(PluginService, "fetch_plugin_model_providers", Mock(return_value=[schema]))
    return PluginModelRuntime(tenant_id="tenant-a", user_id="user-a", client=client, plugin_service=PluginService)


def stream_payload(models: list[AIModelEntity]) -> str:
    return json.dumps({"code": 0, "message": "", "data": {"models": [m.model_dump(mode="json") for m in models]}})


def test_real_client_dispatch_and_bound_runtime(
    monkeypatch: pytest.MonkeyPatch, schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient
) -> None:
    wire = Mock(return_value=iter([stream_payload([ai_model("fresh")])]))
    monkeypatch.setattr(client, "_stream_request", wire)
    credentials = {"synthetic_auth": "fixture-only"}
    config = configuration(schema, runtime, credentials)
    with patch("core.entities.provider_configuration.create_plugin_model_assembly", side_effect=AssertionError):
        models = config.get_provider_models(ModelType.LLM)
    assert [m.model for m in models] == ["fresh"]
    assert models[0].fetch_from == FetchFrom.PREDEFINED_MODEL
    wire.assert_called_once_with(
        "POST",
        "plugin/tenant-a/dispatch/model/list",
        data={
            "user_id": "user-a",
            "data": {"provider": "catalog", "model_type": "llm", "credentials": credentials},
        },
        headers={"X-Plugin-ID": "example/catalog", "Content-Type": "application/json"},
        log_errors=False,
    )


@pytest.mark.parametrize("user_id", [None, "", "user-b"])
def test_client_preserves_user_scope(user_id: str | None, client: PluginModelClient) -> None:
    with patch.object(client, "_stream_request", return_value=iter([stream_payload([])])) as wire:
        assert client.fetch_models("tenant", user_id, "example/catalog", "catalog", "llm", {}) == []
    payload = wire.call_args.kwargs["data"]
    assert ("user_id" in payload) == (user_id is not None)
    if user_id is not None:
        assert payload["user_id"] == user_id


def test_alias_resolves_canonical_identity(runtime: PluginModelRuntime, client: PluginModelClient) -> None:
    with patch.object(client, "_stream_request", return_value=iter([stream_payload([])])) as wire:
        assert runtime.fetch_models(provider="catalog", model_type=ModelType.LLM, credentials={"synthetic": True}) == []
    assert wire.call_args.kwargs["headers"]["X-Plugin-ID"] == "example/catalog"


@pytest.mark.parametrize("credentials", [None, {}])
def test_no_credentials_empty_without_network(
    schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient, credentials: dict[str, object] | None
) -> None:
    config = configuration(schema, runtime, credentials)
    # Even saved model-specific configuration cannot bypass the no-provider-key
    # boundary for an opted-in provider catalog.
    config.custom_configuration.models = [
        CustomModelConfiguration(model="saved", model_type=ModelType.LLM, credentials={"synthetic": True})
    ]
    with patch.object(client, "_stream_request", side_effect=AssertionError) as network:
        assert config.get_provider_models() == []
        assert runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={}) == []
        assert runtime.get_model_schema(provider=PROVIDER, model_type=ModelType.LLM, model="saved", credentials={}) is None
    network.assert_not_called()
    assert [m.model for m in schema.models] == ["declared"]


def test_policy_denied_before_network(schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient) -> None:
    config = configuration(schema, runtime, {"synthetic": True})
    assert config.custom_configuration.provider is not None
    config.custom_configuration.provider.current_credential_id = "synthetic-credential-id"
    with (
        patch("core.helper.credential_utils.runtime_check_credential_policy_compliance", side_effect=ValueError("denied"))
        as policy,
        patch.object(client, "_stream_request", side_effect=AssertionError) as wire,
    ):
        with pytest.raises(ValueError, match="denied"):
            config.get_provider_models(ModelType.LLM)
    policy.assert_called_once()
    assert policy.call_args.kwargs["provider"] == PROVIDER
    wire.assert_not_called()


def test_each_request_refreshes_added_removed_models_and_settings(
    schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient
) -> None:
    config = configuration(schema, runtime, {"synthetic": True})
    config.model_settings = [
        ModelSettings(model="disabled", model_type=ModelType.LLM, enabled=False),
        ModelSettings(
            model="kept",
            model_type=ModelType.LLM,
            load_balancing_enabled=True,
            load_balancing_configs=[
                ModelLoadBalancingConfiguration(id="lb", name="LB", credentials={}, credential_source_type="provider")
            ],
        ),
    ]
    schema.position = {"llm": ["kept", "disabled", "added"]}
    original = schema.model_dump()
    with patch.object(
        client,
        "_stream_request",
        side_effect=[
            iter([stream_payload([ai_model("removed"), ai_model("kept"), ai_model("disabled")])]),
            iter([stream_payload([ai_model("added"), ai_model("kept"), ai_model("disabled")])]),
            iter([stream_payload([ai_model("added"), ai_model("kept"), ai_model("disabled")])]),
        ],
    ) as wire:
        first = config.get_provider_models(ModelType.LLM)
        second = config.get_provider_models(ModelType.LLM)
        active = config.get_provider_models(ModelType.LLM, only_active=True)
    assert [m.model for m in first] == ["kept", "disabled", "removed"]
    assert [m.model for m in second] == ["kept", "disabled", "added"]
    assert [m.model for m in active] == ["kept", "added"]
    assert second[1].status == ModelStatus.DISABLED
    assert second[0].load_balancing_enabled
    assert second[0].has_invalid_load_balancing_configs
    assert wire.call_count == 3
    assert schema.model_dump() == original
    assert config.provider is schema
    assert config._cached_provider_schema is schema
    assert config.model_settings[0].enabled is False


def test_tenant_user_credentials_and_response_objects_do_not_leak(
    monkeypatch: pytest.MonkeyPatch, schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient
) -> None:
    shared_result = ai_model("first")
    other_runtime = PluginModelRuntime(tenant_id="tenant-b", user_id="user-b", client=client, plugin_service=PluginService)
    first_credentials = {"synthetic": {"marker": "a"}}
    first = configuration(schema, runtime, first_credentials)
    second = configuration(schema, other_runtime, {"synthetic": {"marker": "b"}})
    original = deepcopy(first_credentials)
    calls: list[dict[str, object]] = []

    def remote(**kwargs: object) -> list[AIModelEntity]:
        calls.append(deepcopy(kwargs))
        kwargs["credentials"]["synthetic"]["marker"] = "changed"
        return [shared_result]

    monkeypatch.setattr(client, "fetch_models", remote)
    a = first.get_provider_models(ModelType.LLM)
    a[0].label.en_us = "mutated response"
    b = second.get_provider_models(ModelType.LLM)
    assert b[0].label.en_us == "first"
    assert shared_result.label.en_us == "first"
    assert first_credentials == original
    assert [(c["tenant_id"], c["user_id"]) for c in calls] == [("tenant-a", "user-a"), ("tenant-b", "user-b")]
    assert calls[0]["credentials"] != calls[1]["credentials"]
    assert [m.model for m in schema.models] == ["declared"]


def test_relevant_types_and_model_filter(schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient) -> None:
    config = configuration(schema, runtime, {"synthetic": True})
    with patch.object(
        client,
        "_stream_request",
        side_effect=[
            iter([stream_payload([ai_model("llm")])]),
            iter([stream_payload([ai_model("embedding", ModelType.TEXT_EMBEDDING)])]),
            iter([stream_payload([ai_model("one"), ai_model("two")])]),
        ],
    ) as wire:
        assert {m.model for m in config.get_provider_models()} == {"llm", "embedding"}
        assert [m.model for m in config.get_provider_models(ModelType.LLM, model="two")] == ["two"]
    assert [c.kwargs["data"]["data"]["model_type"] for c in wire.call_args_list] == ["llm", "text-embedding", "llm"]


@pytest.mark.parametrize(
    "models",
    [
        [ai_model("wrong", ModelType.TEXT_EMBEDDING)],
        [ai_model("duplicate"), ai_model("duplicate")],
        [ai_model("")],
        [ai_model(" ")],
        [ai_model(str(i)) for i in range(2049)],
    ],
    ids=["wrong-type", "duplicate", "empty-identity", "blank-identity", "oversized"],
)
def test_runtime_rejects_invalid_catalogs(runtime: PluginModelRuntime, client: PluginModelClient, models: list[AIModelEntity]) -> None:
    with patch.object(client, "fetch_models", return_value=models):
        with pytest.raises(ValueError):
            runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={"synthetic": True})


def test_runtime_accepts_2048_models(runtime: PluginModelRuntime, client: PluginModelClient) -> None:
    models = [ai_model(str(i)) for i in range(2048)]
    with patch.object(client, "fetch_models", return_value=models):
        assert len(runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={"synthetic": True})) == 2048


@pytest.mark.parametrize("line", ["not-json", '{"code": 0, "message": "", "data": {}}', '{"code": 0, "message": "", "data": {"models": ["bad"]}}'])
def test_client_rejects_bad_wire_data(client: PluginModelClient, line: str) -> None:
    with patch.object(client, "_stream_request", return_value=iter([line])):
        with pytest.raises(ValueError, match="Unable to fetch remote model catalog"):
            client.fetch_models("tenant", None, "example/catalog", "catalog", "llm", {"synthetic": True})


def test_catalog_failure_does_not_log_or_expose_payloads(
    caplog: pytest.LogCaptureFixture, schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient
) -> None:
    marker = "synthetic-untrusted-private-payload"
    config = configuration(schema, runtime, {"synthetic": True})
    with patch.object(client, "_stream_request", return_value=iter([json.dumps({"code": -500, "message": marker, "data": None})])):
        with pytest.raises(ValueError) as error:
            config.get_provider_models(ModelType.LLM)
    assert marker not in str(error.value)
    assert marker not in caplog.text
    assert [m.model for m in schema.models] == ["declared"]


def test_opt_in_required(runtime: PluginModelRuntime, schema: ProviderEntity, client: PluginModelClient) -> None:
    schema.remote_model_catalog = False
    with patch.object(client, "_stream_request", side_effect=AssertionError) as wire:
        with pytest.raises(ValueError, match="does not support"):
            runtime.fetch_models(provider=PROVIDER, model_type=ModelType.LLM, credentials={"synthetic": True})
        config = configuration(schema, runtime, {"synthetic": True})
        assert [m.model for m in config.get_provider_models(ModelType.LLM)] == ["declared"]
    wire.assert_not_called()


def test_system_provider_uses_existing_quota_policy_without_catalog(
    schema: ProviderEntity, runtime: PluginModelRuntime, client: PluginModelClient
) -> None:
    config = configuration(schema, runtime, {"synthetic": True})
    config.using_provider_type = ProviderType.SYSTEM
    config.system_configuration = SystemConfiguration(
        enabled=True,
        current_quota_type=ProviderQuotaType.TRIAL,
        quota_configurations=[QuotaConfiguration(quota_type=ProviderQuotaType.TRIAL, quota_unit=QuotaUnit.TOKENS, quota_limit=1, quota_used=0, is_valid=False, restrict_models=[RestrictModel(model="other", model_type=ModelType.LLM)])],
    )
    with patch.object(client, "_stream_request", side_effect=AssertionError) as wire:
        models = config.get_provider_models(ModelType.LLM)
    assert [m.model for m in models] == ["declared"]
    assert models[0].status == ModelStatus.NO_PERMISSION
    wire.assert_not_called()


def test_remote_schema_always_uses_existing_fresh_rpc(
    runtime: PluginModelRuntime, client: PluginModelClient, schema: ProviderEntity
) -> None:
    config = configuration(schema, runtime, {"synthetic": True})
    with (
        patch("core.plugin.impl.model_runtime.redis_client", new=Mock()) as redis,
        patch.object(client, "get_model_schema", side_effect=[ai_model("fresh-one"), ai_model("fresh-two"), None]) as rpc,
        patch.object(client, "fetch_models", side_effect=AssertionError),
    ):
        assert config.get_model_schema(ModelType.LLM, "requested", {"synthetic": True}).model == "fresh-one"
        assert config.get_model_schema(ModelType.LLM, "requested", {"synthetic": True}).model == "fresh-two"
        assert config.get_model_schema(ModelType.LLM, "requested", {"synthetic": True}) is None
    redis.get.assert_not_called()
    redis.setex.assert_not_called()
    assert rpc.call_count == 3
    assert rpc.call_args.kwargs["tenant_id"] == "tenant-a"
    assert rpc.call_args.kwargs["user_id"] == "user-a"
    assert rpc.call_args.kwargs["plugin_id"] == "example/catalog"
    assert rpc.call_args.kwargs["provider"] == "catalog"
    assert rpc.call_args.kwargs["remote_model_catalog"] is True


def test_static_schema_retains_cache(runtime: PluginModelRuntime, schema: ProviderEntity, client: PluginModelClient) -> None:
    schema.remote_model_catalog = False
    cached = ai_model("cached")
    with (
        patch("core.plugin.impl.model_runtime.redis_client", new=Mock()) as redis,
        patch.object(client, "get_model_schema", return_value=ai_model("uncached")) as rpc,
    ):
        redis.get.return_value = cached.model_dump_json()
        assert runtime.get_model_schema(provider=PROVIDER, model_type=ModelType.LLM, model="cached", credentials={}) == cached
        rpc.assert_not_called()
        redis.get.return_value = None
        assert runtime.get_model_schema(provider=PROVIDER, model_type=ModelType.LLM, model="uncached", credentials={}).model == "uncached"
        redis.setex.assert_called_once()
        assert "remote_model_catalog" not in rpc.call_args.kwargs


def test_declaration_default_and_serialization_preserve_flag() -> None:
    remote = declaration()
    data = remote.model_dump()
    assert ProviderEntity.model_validate(data).remote_model_catalog is True
    assert PluginModelProviderDeclaration.model_validate_json(remote.model_dump_json()).remote_model_catalog is True
    del data["remote_model_catalog"]
    assert PluginModelProviderDeclaration.model_validate(data).remote_model_catalog is False
    entity = PluginModelProviderEntity(
        id="installation", created_at=datetime(2026, 10, 16), updated_at=datetime(2026, 10, 16),
        provider="catalog", tenant_id="tenant", plugin_unique_identifier=remote.plugin_unique_identifier,
        plugin_id="example/catalog", declaration=remote,
    )
    assert PluginModelProviderEntity.model_validate_json(entity.model_dump_json()).declaration.remote_model_catalog is True


def schema_payload(schema: AIModelEntity | None) -> str:
    return json.dumps(
        {"code": 0, "message": "", "data": {"model_schema": schema.model_dump(mode="json") if schema else None}}
    )


class ClosingStream(Iterator[str]):
    """Track EOF and closure, with an optional read error after the frames."""

    def __init__(self, frames: list[str], read_error: bool = False, close_error: bool = False) -> None:
        self.frames = iter(frames)
        self.read_error = read_error
        self.close_error = close_error
        self.eof = False
        self.closed = False

    def __next__(self) -> str:
        try:
            return next(self.frames)
        except StopIteration:
            if self.read_error:
                raise OSError("synthetic-untrusted-private-payload") from None
            self.eof = True
            raise

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise OSError("synthetic-untrusted-private-payload")


def remote_call(client: PluginModelClient, action: str) -> list[AIModelEntity] | AIModelEntity | None:
    if action == "list":
        return client.fetch_models("tenant", "user", "example/catalog", "catalog", "llm", {"synthetic": True})
    return client.get_model_schema(
        "tenant",
        "user",
        "example/catalog",
        "catalog",
        "llm",
        "requested",
        {"synthetic": True},
        remote_model_catalog=True,
    )


@pytest.mark.parametrize("action", ["list", "schema"])
def test_remote_unary_waits_for_eof_and_closes(client: PluginModelClient, action: str) -> None:
    model = ai_model("requested")
    stream = ClosingStream([stream_payload([model]) if action == "list" else schema_payload(model)])
    with (
        patch.object(client, "_stream_request", return_value=stream) as wire,
        patch.object(client, "_request_with_plugin_daemon_response_stream", side_effect=AssertionError),
    ):
        assert remote_call(client, action) == ([model] if action == "list" else model)
    assert stream.eof
    assert stream.closed
    assert wire.call_args.args == ("POST", f"plugin/tenant/dispatch/model/{action}")
    assert wire.call_args.kwargs["log_errors"] is False
    if action == "schema":
        assert wire.call_args.kwargs["data"] == {
            "user_id": "user",
            "data": {
                "provider": "catalog",
                "model_type": "llm",
                "model": "requested",
                "credentials": {"synthetic": True},
            },
        }
        assert wire.call_args.kwargs["headers"] == {
            "X-Plugin-ID": "example/catalog",
            "Content-Type": "application/json",
        }


@pytest.mark.parametrize("action", ["list", "schema"])
@pytest.mark.parametrize(
    "failure",
    [
        "error-only",
        "success-error",
        "multiple",
        "no-result",
        "missing-data",
        "read-before",
        "read-after",
        "close",
        "malformed-later",
    ],
)
def test_remote_unary_rejects_failures_and_closes(
    client: PluginModelClient, action: str, failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    marker = "synthetic-untrusted-private-payload"
    success = stream_payload([ai_model("requested")]) if action == "list" else schema_payload(ai_model("requested"))
    error = json.dumps({"code": -500, "message": marker, "data": None})
    frames = {
        "error-only": [error],
        "success-error": [success, error],
        "multiple": [success, success],
        "no-result": [],
        "missing-data": ['{"code": 0, "message": "", "data": null}'],
        "read-before": [],
        "read-after": [success],
        "close": [success],
        "malformed-later": [success, marker],
    }[failure]
    stream = ClosingStream(frames, read_error=failure.startswith("read-"), close_error=failure == "close")
    with patch.object(client, "_stream_request", return_value=stream):
        with pytest.raises(
            ValueError, match=f"Unable to fetch remote model {'catalog' if action == 'list' else 'schema'}"
        ) as caught:
            remote_call(client, action)
    assert stream.closed
    assert marker not in "".join(traceback.format_exception(caught.value))
    assert marker not in caplog.text


@pytest.mark.parametrize("action", ["list", "schema"])
@pytest.mark.parametrize("unicode_payload", [False, True])
def test_remote_payload_limit_before_parsing(
    client: PluginModelClient, action: str, unicode_payload: bool, caplog: pytest.LogCaptureFixture
) -> None:
    line = "界" * (3 * 1024 * 1024) if unicode_payload else "x" * (8 * 1024 * 1024 + 1)
    stream = ClosingStream([line])
    with (
        patch.object(client, "_stream_request", return_value=stream),
        patch.object(PluginDaemonBasicResponse, "model_validate_json", side_effect=AssertionError) as parse,
    ):
        with pytest.raises(ValueError):
            remote_call(client, action)
    assert stream.closed
    parse.assert_not_called()
    assert not caplog.text


def test_remote_catalog_accepts_2048_schemas_above_2_mib(client: PluginModelClient) -> None:
    models = [ai_model(f"{i}-" + "x" * 1100) for i in range(2048)]
    payload = stream_payload(models)
    assert 2 * 1024 * 1024 < len(payload.encode("utf-8")) < 8 * 1024 * 1024
    stream = ClosingStream([payload])
    with patch.object(client, "_stream_request", return_value=stream):
        assert client.fetch_models("tenant", None, "example/catalog", "catalog", "llm", {}) == models
    assert stream.eof and stream.closed


@pytest.mark.parametrize("action", ["list", "schema"])
def test_remote_payload_accepts_exact_8_mib(client: PluginModelClient, action: str) -> None:
    payload = stream_payload([]) if action == "list" else schema_payload(None)
    stream = ClosingStream([payload + " " * (8 * 1024 * 1024 - len(payload.encode("utf-8")))])
    with patch.object(client, "_stream_request", return_value=stream):
        assert remote_call(client, action) == ([] if action == "list" else None)
    assert stream.eof and stream.closed


@pytest.mark.parametrize("action", ["list", "schema"])
def test_remote_transport_read_failure_is_not_logged(
    client: PluginModelClient, action: str, caplog: pytest.LogCaptureFixture
) -> None:
    marker = "synthetic-untrusted-private-payload"
    http_response = Mock()
    http_response.iter_lines.side_effect = httpx.ReadError(marker)
    with patch("core.plugin.impl.base._httpx_client.stream") as wire:
        wire.return_value.__enter__.return_value = http_response
        with pytest.raises(ValueError) as caught:
            remote_call(client, action)
    assert marker not in caplog.text
    assert marker not in "".join(traceback.format_exception(caught.value))
    wire.return_value.__exit__.assert_called_once()


def test_remote_schema_explicit_null_is_allowed(client: PluginModelClient) -> None:
    stream = ClosingStream([schema_payload(None)])
    with patch.object(client, "_stream_request", return_value=stream):
        assert remote_call(client, "schema") is None
    assert stream.eof and stream.closed


@pytest.mark.parametrize(
    "payload",
    [
        '{"code": 0, "message": "", "data": {}}',
        '{"code": 0, "message": "", "data": {"model_schema": "synthetic-untrusted-private-payload"}}',
        schema_payload(ai_model("other")),
        schema_payload(ai_model("requested", ModelType.TEXT_EMBEDDING)),
    ],
    ids=["missing-schema", "malformed-schema", "wrong-model", "wrong-type"],
)
def test_remote_schema_rejects_uncorrelated_or_invalid_data(
    client: PluginModelClient, payload: str, caplog: pytest.LogCaptureFixture
) -> None:
    stream = ClosingStream([payload])
    with patch.object(client, "_stream_request", return_value=stream):
        with pytest.raises(ValueError, match="Unable to fetch remote model schema"):
            remote_call(client, "schema")
    assert stream.closed
    assert not caplog.text


def test_static_schema_client_keeps_generic_parser(client: PluginModelClient) -> None:
    schema = ai_model("requested")
    with (
        patch.object(
            client,
            "_request_with_plugin_daemon_response_stream",
            return_value=iter([PluginModelSchemaEntity(model_schema=schema)]),
        ) as parser,
        patch.object(client, "_stream_request", side_effect=AssertionError),
    ):
        assert client.get_model_schema("tenant", None, "example/catalog", "catalog", "llm", "requested", {}) == schema
    parser.assert_called_once()


@pytest.mark.parametrize("action", ["list", "schema"])
@pytest.mark.parametrize("failure", ["none", "malformed", "late-error"])
def test_remote_closes_real_generator_finally(client: PluginModelClient, action: str, failure: str) -> None:
    closed = False

    def stream() -> Iterator[str]:
        nonlocal closed
        try:
            if failure == "malformed":
                yield "not-json"
            else:
                yield stream_payload([]) if action == "list" else schema_payload(None)
            if failure == "late-error":
                raise OSError("synthetic-untrusted-private-payload")
            if failure == "malformed":
                pytest.fail("Malformed unary response should close without reading further.")
        finally:
            closed = True

    with patch.object(client, "_stream_request", return_value=stream()):
        if failure == "none":
            assert remote_call(client, action) == ([] if action == "list" else None)
        else:
            with pytest.raises(ValueError):
                remote_call(client, action)
    assert closed


def test_generic_transport_retains_default_error_logging(client: PluginModelClient) -> None:
    with (
        patch("core.plugin.impl.base._httpx_client.stream", side_effect=httpx.ReadError("synthetic")),
        patch("core.plugin.impl.base.logger.exception") as log,
    ):
        with pytest.raises(Exception):
            list(client._stream_request("POST", "plugin/tenant/dispatch/model/schema"))
    log.assert_called_once_with("Stream request to Plugin Daemon Service failed")
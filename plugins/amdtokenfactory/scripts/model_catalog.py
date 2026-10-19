"""Anonymous public model metadata used only by the snapshot generator.

This module is a development tool under scripts/ and is not shipped in the plugin
package. The packaged plugin reads its model list from models/llm/*.yaml and
never calls this endpoint at runtime.
"""

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

PUBLIC_CATALOG_URL = "https://developer.amd.com.cn/radeon/api/tokenfactory/bootstrap"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_MODELS = 2048


class CatalogError(Exception):
    """Only fixed, non-sensitive messages may be raised by discovery."""


class CatalogConnectionError(CatalogError):
    pass


class CatalogRateLimitError(CatalogError):
    pass


class CatalogUnavailableError(CatalogError):
    pass


class PublicCatalogAuth(requests.auth.AuthBase):
    """Never attach ambient credentials or cookies to the public directory."""

    def __call__(self, request):
        request.headers.pop("Authorization", None)
        request.headers.pop("Cookie", None)
        return request


def parse_public_catalog(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("shared_models"), list):
        raise CatalogUnavailableError("AMD Token Factory returned an invalid public catalog")
    rows = payload["shared_models"]
    if len(rows) > MAX_MODELS:
        raise CatalogUnavailableError("AMD Token Factory public catalog is too large")
    converted = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise CatalogUnavailableError("AMD Token Factory returned an invalid public model")
        display = row.get("token_factory")
        if not isinstance(display, Mapping) or display.get("source") != "model_gateway":
            continue
        access = display.get("access") or {}
        if not isinstance(access, Mapping) or access.get("kind") != "shared_api":
            continue
        outputs = row.get("output")
        if not isinstance(outputs, list):
            raise CatalogUnavailableError("AMD Token Factory returned invalid modality metadata")
        if "text" not in outputs:
            continue
        providers = row.get("provider_pricing", [])
        if not isinstance(providers, list) or any(not isinstance(p, Mapping) for p in providers):
            raise CatalogUnavailableError("AMD Token Factory returned invalid provider metadata")
        inputs = ["text"]
        if any(p.get("vision") is True for p in providers):
            inputs.append("image")
        item = dict(row)
        # Use the API's model ID, not the prefixed UI card ID or display label.
        item.update({
            "id": row.get("model"), "name": display.get("name"),
            # Token Factory lists these shared endpoints as free; show zero cost in Dify.
            **({"pricing": {"prompt": "0", "completion": "0"}}
               if row.get("display_status") == "free_endpoint" else {}),
            "architecture": {"input_modalities": inputs, "output_modalities": outputs},
            "providers": providers,
        })
        converted.append(item)
    return parse_catalog({"data": converted})


def fetch_public_catalog() -> list[dict[str, Any]]:
    """Fetch anonymous public metadata for regenerating the packaged snapshot."""
    response = None
    try:
        response = requests.post(
            PUBLIC_CATALOG_URL,
            headers={
                "Accept": "application/json", "X-Source": "dify",
                "Origin": "https://developer.amd.com.cn",
                "Referer": "https://developer.amd.com.cn/radeon/tokenfactory",
                "Cache-Control": "no-cache",
            },
            auth=PublicCatalogAuth(), timeout=(10, 30), allow_redirects=False, stream=True,
        )
        if response.status_code == 429:
            raise CatalogRateLimitError("AMD Token Factory public model discovery was rate limited")
        if 300 <= response.status_code < 400:
            raise CatalogConnectionError(
                "AMD Token Factory public model discovery refused a redirect"
            )
        if response.status_code != 200:
            raise CatalogUnavailableError("AMD Token Factory public model catalog is unavailable")
        content = bytearray()
        for part in response.iter_content(chunk_size=8192):
            if len(content) + len(part) > MAX_RESPONSE_BYTES:
                raise CatalogUnavailableError(
                    "AMD Token Factory public catalog response is too large"
                )
            content.extend(part)
        return parse_public_catalog(json.loads(content))
    except requests.RequestException:
        raise CatalogConnectionError(
            "AMD Token Factory public model discovery connection failed"
        ) from None
    except (ValueError, UnicodeError):
        raise CatalogUnavailableError(
            "AMD Token Factory returned an invalid public catalog"
        ) from None
    finally:
        if response is not None:
            try:
                response.close()
            except requests.RequestException:
                raise CatalogConnectionError(
                    "AMD Token Factory public model discovery connection failed"
                ) from None


def _positive_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _price(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise CatalogUnavailableError("AMD Token Factory returned invalid catalog pricing")
    try:
        price = Decimal(str(value))
    except InvalidOperation:
        raise CatalogUnavailableError(
            "AMD Token Factory returned invalid catalog pricing"
        ) from None
    if not price.is_finite() or price < 0:
        raise CatalogUnavailableError("AMD Token Factory returned invalid catalog pricing")
    return price


def _providers(row: Mapping) -> list[Mapping]:
    providers = row.get("providers") or []
    if not isinstance(providers, list) or any(not isinstance(item, Mapping) for item in providers):
        raise CatalogUnavailableError("AMD Token Factory returned invalid provider metadata")
    return providers


def _capability(row: Mapping, name: str) -> bool:
    values = [item[name] for item in _providers(row) if isinstance(item.get(name), bool)]
    return bool(values) and all(values)


def parse_catalog(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise CatalogUnavailableError("AMD Token Factory returned an invalid model catalog")
    if len(payload["data"]) > MAX_MODELS:
        raise CatalogUnavailableError("AMD Token Factory model catalog is too large")
    models = []
    seen = set()
    for row in payload["data"]:
        if not isinstance(row, Mapping):
            raise CatalogUnavailableError("AMD Token Factory returned an invalid model record")
        architecture = row.get("architecture") or {}
        if not isinstance(architecture, Mapping):
            raise CatalogUnavailableError("AMD Token Factory returned invalid modality metadata")
        outputs = architecture.get("output_modalities", row.get("output", []))
        inputs = architecture.get("input_modalities", [])
        if not isinstance(outputs, list) or "text" not in outputs:
            continue
        providers = _providers(row)
        if (not isinstance(inputs, list) or "text" not in inputs
            or any(item.get("ocr") is True for item in providers)):
            continue
        if row.get("enabled") is False or row.get("deprecated") is True:
            continue
        status = row.get("status")
        if status is not None and not isinstance(status, str):
            raise CatalogUnavailableError("AMD Token Factory returned invalid model status")
        if status in {"offline", "temp_offline", "disabled", "preview"}:
            continue
        model = row.get("id")
        if (not isinstance(model, str) or not model or len(model) > 255
                or any(ord(character) < 32 or ord(character) == 127 for character in model)):
            raise CatalogUnavailableError("AMD Token Factory returned an invalid model identity")
        if model in seen:
            raise CatalogUnavailableError("AMD Token Factory returned duplicate model identities")
        seen.add(model)
        parameters = row.get("supported_parameters") or []
        if (not isinstance(parameters, list)
            or any(not isinstance(name, str) for name in parameters)):
            raise CatalogUnavailableError("AMD Token Factory returned invalid parameter metadata")
        features = []
        if _capability(row, "reasoning"):
            features.append("agent-thought")
        if "image" in inputs:
            features.append("vision")
        if "tools" in parameters and _capability(row, "tools"):
            features.append("tool-call")
            if _capability(row, "streaming"):
                features.append("stream-tool-call")
        properties: dict[str, Any] = {"mode": "chat"}
        context = _positive_integer(row.get("context_length"))
        if context:
            properties["context_size"] = context
        top_provider = row.get("top_provider") or {}
        if not isinstance(top_provider, Mapping):
            raise CatalogUnavailableError("AMD Token Factory returned invalid provider metadata")
        limits = [row, top_provider, *providers]
        output_limits = [limit for item in limits for field in (
            "max_completion_tokens", "max_output_tokens", "maxOutput"
        ) if (limit := _positive_integer(item.get(field)))]
        maximum = min(output_limits) if output_limits else None
        rules: list[dict[str, Any]] = []
        if "max_tokens" in parameters:
            rule: dict[str, Any] = {
                "name": "max_tokens", "type": "int", "required": False,
                "label": {"en_US": "Max Tokens", "zh_Hans": "最大输出Token"},
                "default": min(4096, maximum) if maximum else 4096, "min": 1,
                "help": {
                    "en_US": "Service output limit is not published; the API enforces its limit."
                    if maximum is None else "Output limit from the published model metadata.",
                    "zh_Hans": "服务未公开最大输出值；由API执行限制。"
                    if maximum is None else "最大输出值取自远端模型目录。",
                },
            }
            if maximum:
                rule["max"] = maximum
            rules.append(rule)
        for name, label, default in (("temperature", "Temperature", 0.7), ("top_p", "Top P", 1.0)):
            if name in parameters:
                rules.append({"name": name, "type": "float", "required": False,
                              "label": {"en_US": label, "zh_Hans": label}, "default": default})
        if "response_format" in parameters:
            rules.append({
                "name": "response_format", "type": "string", "required": False,
                "label": {"en_US": "Response Format", "zh_Hans": "回复格式"},
                "options": ["text", "json_object", "json_schema"],
            })
            rules.append({"name": "json_schema", "use_template": "json_schema"})
        label = row.get("name")
        label = label if isinstance(label, str) and label else model
        schema = {
            "model": model, "label": {"en_US": label, "zh_Hans": label}, "model_type": "llm",
            "features": features, "fetch_from": "predefined-model", "model_properties": properties,
            "parameter_rules": rules, "deprecated": False,
        }
        pricing = row.get("pricing") or {}
        if isinstance(pricing, Mapping):
            if "prompt" in pricing and "completion" in pricing:
                schema["pricing"] = {
                    "input": format(_price(pricing["prompt"]) * 1_000_000, "f"),
                    "output": format(_price(pricing["completion"]) * 1_000_000, "f"),
                    "unit": "0.000001", "currency": "USD",
                }
            elif pricing.get("unit") == "USD / 1M tokens" and "input" in pricing:
                schema["pricing"] = {
                    "input": format(_price(pricing["input"]), "f"),
                    "output": (
                        format(_price(pricing["output"]), "f") if "output" in pricing else None
                    ),
                    "unit": "0.000001", "currency": "USD",
                }
        models.append(schema)
    return models

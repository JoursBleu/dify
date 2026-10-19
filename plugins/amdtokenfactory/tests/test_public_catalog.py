"""Generator-only anonymous metadata client (scripts/), with no real HTTP."""

import copy

import model_catalog as catalog
import pytest
from dify_plugin.entities.model import AIModelEntity


def public_model(model="actual-chat-id", *, vision=False, **values):
    return {
        "id": f"shared-card/{model}",
        "model": model,
        "output": ["text"],
        "context_length": 262144,
        "supported_parameters": ["max_tokens", "temperature", "top_p", "tools", "response_format"],
        "pricing": {"prompt": "3.5e-8", "completion": "7e-8"},
        "provider_pricing": [{
            "tools": True, "vision": vision, "reasoning": True,
            "streaming": True,
        }],
        "token_factory": {
            "source": "model_gateway", "access": {"kind": "shared_api"},
            "name": f"Display {model}",
        },
        **values,
    }


def test_public_parser_uses_actual_ids_and_live_metadata_without_mutating_payload():
    rows = [public_model(f"future-{index}", vision=index < 8) for index in range(11)]
    rows += [public_model("embedding", output=["embedding"]),
             public_model("image", output=["image"]), public_model("audio", output=["audio"])]
    payload = {"shared_models": rows}
    before = copy.deepcopy(payload)
    models = catalog.parse_public_catalog(payload)
    assert len(rows) == 14 and len(models) == 11  # Synthetic shape, not a frozen service list.
    assert [model["model"] for model in models] == [row["model"] for row in rows[:11]]
    assert all(model["model"] != row["id"] for model, row in zip(models, rows, strict=False))
    assert models[0]["label"] == {"en_US": "Display future-0", "zh_Hans": "Display future-0"}
    assert set(models[0]["features"]) == {
        "vision", "agent-thought", "tool-call", "stream-tool-call",
    }
    assert "vision" not in models[-1]["features"]
    assert models[0]["model_properties"] == {"mode": "chat", "context_size": 262144}
    assert models[0]["pricing"] == {
        "input": "0.035000000", "output": "0.07000000", "unit": "0.000001", "currency": "USD",
    }
    free = catalog.parse_public_catalog(
        {"shared_models": [public_model("free", display_status="free_endpoint")]}
    )
    assert free[0]["pricing"] == {
        "input": "0", "output": "0", "unit": "0.000001", "currency": "USD",
    }
    rules = {rule["name"]: rule for rule in models[0]["parameter_rules"]}
    assert "max" not in rules["max_tokens"]
    assert rules["response_format"]["options"] == ["text", "json_object", "json_schema"]
    assert rules["json_schema"] == {"name": "json_schema", "use_template": "json_schema"}
    assert all(AIModelEntity.model_validate(model) for model in models)
    assert payload == before


@pytest.mark.parametrize("values", [
    {"token_factory": {"source": "model_gateway", "access": {"kind": "private_api"}}},
    {"output": ["image"]}, {"status": "offline"},
])
def test_non_shared_non_chat_and_unavailable_rows_are_skipped(values):
    assert catalog.parse_public_catalog({"shared_models": [public_model(**values)]}) == []

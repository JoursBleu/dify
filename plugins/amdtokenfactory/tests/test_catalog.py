import copy

from dify_plugin.entities.model import AIModelEntity
from model_catalog import parse_catalog


def remote_model(model="remote-model", *, vision=False, **values):
    return {
        "id": model,
        "name": model,
        "architecture": {"input_modalities": ["text", "image"] if vision else ["text"],
                         "output_modalities": ["text"]},
        "context_length": 262144,
        "supported_parameters": ["max_tokens", "temperature", "top_p", "tools", "response_format"],
        "providers": [{"reasoning": True, "vision": vision, "tools": True,
                       "streaming": True, "parallelToolCalls": False, "ocr": False}],
        "pricing": {"prompt": "3.5e-8", "completion": "7e-8"},
        **values,
    }


def test_remote_catalog_drives_ids_vision_context_price_and_parameters():
    payload = {"data": [remote_model("a"), remote_model("brand-new-image", vision=True)]}
    before = copy.deepcopy(payload)
    schemas = parse_catalog(payload)
    assert [schema["model"] for schema in schemas] == ["a", "brand-new-image"]
    assert "vision" not in schemas[0]["features"]
    assert "vision" in schemas[1]["features"]
    assert schemas[1]["model_properties"]["context_size"] == 262144
    assert schemas[0]["pricing"] == {
        "input": "0.035000000", "output": "0.07000000", "unit": "0.000001", "currency": "USD"
    }
    assert "multi-tool-call" not in schemas[0]["features"]
    rules = {rule["name"]: rule for rule in schemas[0]["parameter_rules"]}
    assert "max" not in rules["max_tokens"]
    assert "use_template" not in rules["max_tokens"]
    assert rules["response_format"]["options"] == ["text", "json_object", "json_schema"]
    assert rules["json_schema"] == {"name": "json_schema", "use_template": "json_schema"}
    for schema in schemas:
        AIModelEntity.model_validate(schema)
    assert payload == before

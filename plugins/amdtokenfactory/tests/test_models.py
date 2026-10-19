from unittest.mock import Mock

from dify_plugin.entities.model import AIModelEntity, I18nObject, ModelFeature, ModelType
from dify_plugin.entities.model.message import AssistantPromptMessage, UserPromptMessage

from models.llm.llm import AMDTokenFactoryLargeLanguageModel


def _schema(model: str, features: list[ModelFeature]) -> AIModelEntity:
    return AIModelEntity(
        model=model,
        label=I18nObject(en_US=model),
        model_type=ModelType.LLM,
        features=features,
        model_properties={"mode": "chat", "context_size": 4096},
    )


def test_non_stream_reasoning_round_trips_through_history() -> None:
    entity = _schema("DeepSeek-test", [ModelFeature.AGENT_THOUGHT])
    model = AMDTokenFactoryLargeLanguageModel(model_schemas=[entity])
    response = Mock()
    response.json.return_value = {
        "id": "chatcmpl-1",
        "model": "DeepSeek-test",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "reasoning_content": "must preserve </think> & exactly",
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    credentials = {"mode": "chat", "_current_model": "DeepSeek-test"}

    result = model._handle_generate_response(
        "DeepSeek-test",
        credentials,
        response,
        [UserPromptMessage(content="hi")],
    )
    assert isinstance(result.message.opaque_body, dict)
    assert result.message.opaque_body["reasoning_content"] == "must preserve </think> & exactly"
    assert "<!--dify-amdtokenfactory-reasoning-->" in result.message.content
    assert "<!--dify-amdgpucloud-reasoning-->" not in result.message.content
    assert "<!--dify-radeon-reasoning-->" not in result.message.content

    payload = model._convert_prompt_message_to_dict(result.message, credentials)
    assert payload["content"] == "answer"
    assert payload["reasoning_content"] == "must preserve </think> & exactly"

    restored = AssistantPromptMessage(content=result.message.content)
    restored_payload = model._convert_prompt_message_to_dict(restored, credentials)
    assert restored_payload["content"] == "answer"
    assert restored_payload["reasoning_content"] == "must preserve </think> & exactly"

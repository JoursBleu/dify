import re
from collections.abc import Generator, Mapping
from html import escape, unescape

from dify_plugin import OAICompatLargeLanguageModel
from dify_plugin.entities.model import ModelFeature
from dify_plugin.entities.model.llm import LLMResult
from dify_plugin.entities.model.message import (
    AssistantPromptMessage,
    PromptMessage,
    PromptMessageTool,
)
from requests import Response

from models._credentials import (
    ENDPOINT_URL,
    SOURCE_HEADER,
    SOURCE_VALUE,
    normalize_api_key,
    validate_model_access,
)


class RadeonCloudLargeLanguageModel(OAICompatLargeLanguageModel):
    _THINK_MARKER = "<!--dify-radeon-reasoning-->"
    _THINK_PATTERN = re.compile(
        rf"<think>\n{re.escape(_THINK_MARKER)}(.*?)\n</think>",
        re.DOTALL | re.IGNORECASE,
    )

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        return super()._invoke(
            model=model,
            credentials=self._model_credentials(model, credentials),
            prompt_messages=prompt_messages,
            model_parameters=model_parameters,
            tools=tools,
            stop=stop,
            stream=stream,
            user=user,
        )

    def validate_credentials(self, model: str, credentials: dict) -> None:
        validate_model_access(credentials, model)

    def get_num_tokens(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        tools: list[PromptMessageTool] | None = None,
    ) -> int:
        return super().get_num_tokens(
            model,
            self._model_credentials(model, credentials),
            prompt_messages,
            tools,
        )

    def _model_credentials(self, model: str, credentials: Mapping) -> dict:
        extra_headers = credentials.get("extra_headers")
        headers = dict(extra_headers) if isinstance(extra_headers, Mapping) else {}
        headers = {
            key: value
            for key, value in headers.items()
            if key.lower() != SOURCE_HEADER.lower()
        }
        headers[SOURCE_HEADER] = SOURCE_VALUE

        resolved = {
            **credentials,
            "api_key": normalize_api_key(credentials),
            "endpoint_url": ENDPOINT_URL,
            "mode": "chat",
            "extra_headers": headers,
            "_current_model": model,
        }
        schema = self.get_model_schema(model)
        features = set(schema.features or []) if schema else set()
        if {ModelFeature.TOOL_CALL, ModelFeature.MULTI_TOOL_CALL} & features:
            resolved["function_calling_type"] = "tool_call"
        if ModelFeature.STREAM_TOOL_CALL in features:
            resolved["stream_function_calling"] = "supported"
        return resolved

    def _handle_generate_response(
        self,
        model: str,
        credentials: dict,
        response: Response,
        prompt_messages: list[PromptMessage],
    ) -> LLMResult:
        result = super()._handle_generate_response(
            model,
            credentials,
            response,
            prompt_messages,
        )
        response_message = response.json()["choices"][0].get("message", {})
        reasoning_content = response_message.get("reasoning_content")
        if not isinstance(reasoning_content, str):
            reasoning_content = response_message.get("reasoning")
        if not isinstance(reasoning_content, str):
            return result

        opaque_body = (
            result.message.opaque_body
            if isinstance(result.message.opaque_body, dict)
            else {}
        )
        result.message.opaque_body = {
            **opaque_body,
            "reasoning_content": reasoning_content,
        }
        if reasoning_content:
            result.message.content = (
                f"<think>\n{self._THINK_MARKER}"
                f"{escape(reasoning_content, quote=False)}\n</think>"
                f"{result.message.content or ''}"
            )
        return result

    def _wrap_thinking_by_reasoning_content(
        self,
        delta: dict,
        is_reasoning: bool,
    ) -> tuple[str, bool]:
        content = delta.get("content") or ""
        reasoning_content = delta.get("reasoning_content") or delta.get("reasoning")
        if not reasoning_content:
            return ("\n</think>" if is_reasoning else "") + content, False

        output = escape(str(reasoning_content), quote=False)
        if not is_reasoning:
            output = f"<think>\n{self._THINK_MARKER}" + output
        if content or delta.get("tool_calls") or delta.get("function_call"):
            return output + "\n</think>" + content, False
        return output, True

    def _convert_prompt_message_to_dict(
        self,
        message: PromptMessage,
        credentials: dict | None = None,
    ) -> dict:
        credentials = credentials or {}
        message_dict = super()._convert_prompt_message_to_dict(message, credentials)
        if not isinstance(message, AssistantPromptMessage):
            return message_dict

        content = message.content or ""
        reasoning_content = None
        if isinstance(message.opaque_body, dict):
            raw_reasoning = message.opaque_body.get("reasoning_content")
            if isinstance(raw_reasoning, str):
                reasoning_content = raw_reasoning
        if isinstance(content, str):
            content, extracted_reasoning = self._extract_reasoning_content(content)
            if reasoning_content is None:
                reasoning_content = extracted_reasoning

        if self._supports_reasoning(credentials.get("_current_model")) or reasoning_content:
            message_dict["reasoning_content"] = reasoning_content or ""
            message_dict["content"] = content
        return message_dict

    def _supports_reasoning(self, model: object) -> bool:
        if not isinstance(model, str):
            return False
        schema = self.get_model_schema(model)
        return bool(schema and ModelFeature.AGENT_THOUGHT in (schema.features or []))

    def _extract_reasoning_content(self, text: str) -> tuple[str, str | None]:
        if not text:
            return text, None
        matches = self._THINK_PATTERN.findall(text)
        reasoning_content = "\n\n".join(map(unescape, matches)) if matches else None
        return self._THINK_PATTERN.sub("", text), reasoning_content
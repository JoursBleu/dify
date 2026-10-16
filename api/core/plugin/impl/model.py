import binascii
from collections.abc import Generator, Sequence
from typing import IO, Any

from pydantic import BaseModel

from core.plugin.entities.plugin_daemon import (
    PluginBasicBooleanResponse,
    PluginDaemonBasicResponse,
    PluginDaemonInnerError,
    PluginLLMNumTokensResponse,
    PluginModelListEntity,
    PluginModelProviderBinding,
    PluginModelProviderEntity,
    PluginModelSchemaEntity,
    PluginStringResultResponse,
    PluginTextEmbeddingNumTokensResponse,
    PluginTTSResultResponse,
    PluginVoicesResponse,
    TTSAudioChunk,
)
from core.plugin.impl.base import BasePluginClient
from core.plugin.impl.exc import PluginInvokeError, PluginLLMPollingUnsupportedError
from graphon.model_runtime.entities.llm_entities import LLMPollingResult, LLMResultChunk
from graphon.model_runtime.entities.message_entities import PromptMessage, PromptMessageTool
from graphon.model_runtime.entities.model_entities import AIModelEntity, ModelType
from graphon.model_runtime.entities.rerank_entities import MultimodalRerankInput, RerankResult
from graphon.model_runtime.entities.text_embedding_entities import EmbeddingResult
from graphon.model_runtime.protocols.tts_runtime import TTSModelVoice
from graphon.model_runtime.utils.encoders import jsonable_encoder

_POLLING_UNSUPPORTED_INVOKE_ERROR_TYPES = frozenset((NotImplementedError.__name__,))
_POLLING_UNSUPPORTED_ERROR_MESSAGE = "does not support polling"
_REMOTE_MODEL_RESPONSE_MAX_BYTES = 8 * 1024 * 1024


class PluginModelClient(BasePluginClient):
    @staticmethod
    def _dispatch_payload(*, user_id: str | None, data: dict[str, Any], app_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"data": data}
        if user_id is not None:
            payload["user_id"] = user_id
        if app_id is not None:
            payload["app_id"] = app_id
        return payload

    def fetch_model_providers(self, tenant_id: str) -> Sequence[PluginModelProviderEntity]:
        """
        Fetch model providers for the given tenant.
        """
        response = self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/models",
            list[PluginModelProviderEntity],
            params={"page": 1, "page_size": 256},
        )
        return response

    def fetch_model_provider_bindings(self, tenant_id: str) -> Sequence[PluginModelProviderBinding]:
        """Fetch only model-provider installation identities from the daemon."""
        return self._request_with_plugin_daemon_response(
            "GET",
            f"plugin/{tenant_id}/management/models/bindings",
            list[PluginModelProviderBinding],
        )

    @staticmethod
    def _read_remote_model_response[T: BaseModel | dict[str, Any]](response: Generator[str], type_: type[T]) -> T:
        """Accept one bounded success frame only after EOF, closing on every exit.

        Credential-aware payloads must not use the generic daemon parser: its
        error handling can log or expose untrusted response contents.
        """
        try:
            data: T | None = None
            for line in response:
                # Check characters first to avoid encoding an already oversized
                # string, then enforce the actual UTF-8 byte bound before JSON.
                if (
                    len(line) > _REMOTE_MODEL_RESPONSE_MAX_BYTES
                    or len(line.encode("utf-8")) > _REMOTE_MODEL_RESPONSE_MAX_BYTES
                ):
                    raise ValueError("Remote model response exceeds its byte limit.")
                result = PluginDaemonBasicResponse[type_].model_validate_json(line)
                if result.code != 0 or result.data is None or data is not None:
                    raise ValueError("Invalid unary remote model response.")
                data = result.data
            if data is None:
                raise ValueError("Empty unary remote model response.")
            return data
        finally:
            # The transport returns a generator; tolerate plain iterators used
            # by callers' existing test doubles as well.
            close = getattr(response, "close", None)
            if close is not None:
                close()

    def fetch_models(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model_type: str,
        credentials: dict[str, Any],
    ) -> list[AIModelEntity]:
        """Dispatch get_ai_model_list without logging untrusted catalog/error payloads."""
        try:
            response = self._stream_request(
                "POST",
                f"plugin/{tenant_id}/dispatch/model/list",
                data=self._dispatch_payload(
                    user_id=user_id,
                    data={"provider": provider, "model_type": model_type, "credentials": credentials},
                ),
                headers={"X-Plugin-ID": plugin_id, "Content-Type": "application/json"},
                log_errors=False,
            )
            return self._read_remote_model_response(response, PluginModelListEntity).models
        except Exception:
            raise ValueError("Unable to fetch remote model catalog.") from None

    def get_model_schema(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model_type: str,
        model: str,
        credentials: dict[str, Any],
        remote_model_catalog: bool = False,
    ) -> AIModelEntity | None:
        """
        Get model schema, using a safe fresh unary RPC for opted-in catalogs.
        """
        if remote_model_catalog:
            return self._get_remote_model_schema(
                tenant_id, user_id, plugin_id, provider, model_type, model, credentials
            )

        response = self._request_with_plugin_daemon_response_stream(
            "POST",
            f"plugin/{tenant_id}/dispatch/model/schema",
            PluginModelSchemaEntity,
            data=self._dispatch_payload(
                user_id=user_id,
                data={
                    "provider": provider,
                    "model_type": model_type,
                    "model": model,
                    "credentials": credentials,
                },
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp.model_schema

        return None

    def _get_remote_model_schema(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model_type: str,
        model: str,
        credentials: dict[str, Any],
    ) -> AIModelEntity | None:
        """Parse nullable remote metadata without widening the static entity contract."""
        try:
            response = self._stream_request(
                "POST",
                f"plugin/{tenant_id}/dispatch/model/schema",
                data=self._dispatch_payload(
                    user_id=user_id,
                    data={"provider": provider, "model_type": model_type, "model": model, "credentials": credentials},
                ),
                headers={"X-Plugin-ID": plugin_id, "Content-Type": "application/json"},
                log_errors=False,
            )
            data = self._read_remote_model_response(response, dict[str, Any])
            # Missing metadata is a protocol error; an explicit null means this
            # credential-aware catalog no longer contains the requested model.
            raw_schema = data["model_schema"]
            if raw_schema is None:
                return None
            schema = AIModelEntity.model_validate(raw_schema)
            if schema.model != model or schema.model_type.value != model_type:
                raise ValueError("Remote model schema does not match the request.")
            return schema
        except Exception:
            raise ValueError("Unable to fetch remote model schema.") from None

    def validate_provider_credentials(
        self, tenant_id: str, user_id: str | None, plugin_id: str, provider: str, credentials: dict[str, Any]
    ) -> bool:
        """
        validate the credentials of the provider
        """
        response = self._request_with_plugin_daemon_response_stream(
            "POST",
            f"plugin/{tenant_id}/dispatch/model/validate_provider_credentials",
            PluginBasicBooleanResponse,
            data=self._dispatch_payload(
                user_id=user_id,
                data={
                    "provider": provider,
                    "credentials": credentials,
                },
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            if resp.credentials and isinstance(resp.credentials, dict):
                credentials.update(resp.credentials)

            return resp.result

        return False

    def validate_model_credentials(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model_type: str,
        model: str,
        credentials: dict[str, Any],
    ) -> bool:
        """
        validate the credentials of the provider
        """
        response = self._request_with_plugin_daemon_response_stream(
            "POST",
            f"plugin/{tenant_id}/dispatch/model/validate_model_credentials",
            PluginBasicBooleanResponse,
            data=self._dispatch_payload(
                user_id=user_id,
                data={
                    "provider": provider,
                    "model_type": model_type,
                    "model": model,
                    "credentials": credentials,
                },
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            if resp.credentials and isinstance(resp.credentials, dict):
                credentials.update(resp.credentials)

            return resp.result

        return False

    def invoke_llm(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        prompt_messages: list[PromptMessage],
        model_parameters: dict[str, Any] | None = None,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        app_id: str | None = None,
    ) -> Generator[LLMResultChunk]:
        """
        Invoke llm
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/llm/invoke",
            type_=LLMResultChunk,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "llm",
                        "model": model,
                        "credentials": credentials,
                        "prompt_messages": prompt_messages,
                        "model_parameters": model_parameters,
                        "tools": tools,
                        "stop": stop,
                        "stream": stream,
                    },
                    app_id=app_id,
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        try:
            yield from response
        except PluginDaemonInnerError as e:
            raise ValueError(e.message + str(e.code))

    def start_llm_polling(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        prompt_messages: list[PromptMessage],
        model_parameters: dict[str, Any] | None = None,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMPollingResult:
        """Start an LLM polling request for plugin-backed long-running jobs."""
        try:
            return self._request_with_plugin_daemon_response(
                method="POST",
                path=f"plugin/{tenant_id}/dispatch/model/polling/start",
                type_=LLMPollingResult,
                data=jsonable_encoder(
                    self._dispatch_payload(
                        user_id=user_id,
                        data={
                            "provider": provider,
                            "model_type": ModelType.LLM.value,
                            "model": model,
                            "credentials": credentials,
                            "prompt_messages": prompt_messages,
                            "model_parameters": model_parameters,
                            "tools": tools,
                            "stop": stop,
                            "stream": False,
                            "json_schema": json_schema,
                        },
                    )
                ),
                headers={
                    "X-Plugin-ID": plugin_id,
                    "Content-Type": "application/json",
                },
            )
        except PluginInvokeError as error:
            self._raise_typed_polling_unsupported_error(error)
            raise

    def check_llm_polling(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        plugin_state: dict[str, Any],
    ) -> LLMPollingResult:
        """Check the latest state for a plugin-backed LLM polling job."""
        try:
            return self._request_with_plugin_daemon_response(
                method="POST",
                path=f"plugin/{tenant_id}/dispatch/model/polling/check",
                type_=LLMPollingResult,
                data=jsonable_encoder(
                    self._dispatch_payload(
                        user_id=user_id,
                        data={
                            "provider": provider,
                            "model_type": ModelType.LLM.value,
                            "model": model,
                            "credentials": credentials,
                            "plugin_state": plugin_state,
                        },
                    )
                ),
                headers={
                    "X-Plugin-ID": plugin_id,
                    "Content-Type": "application/json",
                },
            )
        except PluginInvokeError as error:
            self._raise_typed_polling_unsupported_error(error)
            raise

    @staticmethod
    def _raise_typed_polling_unsupported_error(error: PluginInvokeError) -> None:
        """Convert plugin polling capability failures into a dedicated Dify exception."""
        if error.get_error_type() == PluginLLMPollingUnsupportedError.__name__:
            raise PluginLLMPollingUnsupportedError(description=error.description) from error

        if (
            error.get_error_type() in _POLLING_UNSUPPORTED_INVOKE_ERROR_TYPES
            # This is ugly, we should not rely on error messages while checking
            # error types.
            and _POLLING_UNSUPPORTED_ERROR_MESSAGE in error.get_error_message().lower()
        ):
            raise PluginLLMPollingUnsupportedError(description=error.description) from error

    def get_llm_num_tokens(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model_type: str,
        model: str,
        credentials: dict[str, Any],
        prompt_messages: list[PromptMessage],
        tools: list[PromptMessageTool] | None = None,
    ) -> int:
        """
        Get number of tokens for llm
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/llm/num_tokens",
            type_=PluginLLMNumTokensResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": model_type,
                        "model": model,
                        "credentials": credentials,
                        "prompt_messages": prompt_messages,
                        "tools": tools,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp.num_tokens

        return 0

    def invoke_text_embedding(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        texts: list[str],
        input_type: str,
    ) -> EmbeddingResult:
        """
        Invoke text embedding
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/text_embedding/invoke",
            type_=EmbeddingResult,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "text-embedding",
                        "model": model,
                        "credentials": credentials,
                        "texts": texts,
                        "input_type": input_type,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp

        raise ValueError("Failed to invoke text embedding")

    def invoke_multimodal_embedding(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        documents: list[dict],
        input_type: str,
    ) -> EmbeddingResult:
        """
        Invoke file embedding
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/multimodal_embedding/invoke",
            type_=EmbeddingResult,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "text-embedding",
                        "model": model,
                        "credentials": credentials,
                        "documents": documents,
                        "input_type": input_type,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp

        raise ValueError("Failed to invoke file embedding")

    def get_text_embedding_num_tokens(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        texts: list[str],
    ) -> list[int]:
        """
        Get number of tokens for text embedding
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/text_embedding/num_tokens",
            type_=PluginTextEmbeddingNumTokensResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "text-embedding",
                        "model": model,
                        "credentials": credentials,
                        "texts": texts,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp.num_tokens

        return []

    def invoke_rerank(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        query: str,
        docs: list[str],
        score_threshold: float | None = None,
        top_n: int | None = None,
    ) -> RerankResult:
        """
        Invoke rerank
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/rerank/invoke",
            type_=RerankResult,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "rerank",
                        "model": model,
                        "credentials": credentials,
                        "query": query,
                        "docs": docs,
                        "score_threshold": score_threshold,
                        "top_n": top_n,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp

        raise ValueError("Failed to invoke rerank")

    def invoke_multimodal_rerank(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        query: MultimodalRerankInput,
        docs: list[MultimodalRerankInput],
        score_threshold: float | None = None,
        top_n: int | None = None,
    ) -> RerankResult:
        """
        Invoke multimodal rerank
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/multimodal_rerank/invoke",
            type_=RerankResult,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "rerank",
                        "model": model,
                        "credentials": credentials,
                        "query": query,
                        "docs": docs,
                        "score_threshold": score_threshold,
                        "top_n": top_n,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )
        for resp in response:
            return resp

        raise ValueError("Failed to invoke multimodal rerank")

    def invoke_tts(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        content_text: str,
        voice: str,
    ) -> Generator[TTSAudioChunk]:
        """
        Invoke tts
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/tts/invoke",
            type_=PluginTTSResultResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "tts",
                        "model": model,
                        "credentials": credentials,
                        "tenant_id": tenant_id,
                        "content_text": content_text,
                        "voice": voice,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        try:
            for result in response:
                hex_str = result.result
                yield TTSAudioChunk(binascii.unhexlify(hex_str), mime_type=result.mime_type)
        except PluginDaemonInnerError as e:
            raise ValueError(e.message + str(e.code))

    def get_tts_model_voices(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        language: str | None = None,
    ) -> list[TTSModelVoice]:
        """
        Get tts model voices
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/tts/model/voices",
            type_=PluginVoicesResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "tts",
                        "model": model,
                        "credentials": credentials,
                        "language": language,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            voices: list[TTSModelVoice] = []
            for voice in resp.voices:
                voices.append({"name": voice.name, "value": voice.value})

            return voices

        return []

    def invoke_speech_to_text(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        file: IO[bytes],
    ) -> str:
        """
        Invoke speech to text
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/speech2text/invoke",
            type_=PluginStringResultResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "speech2text",
                        "model": model,
                        "credentials": credentials,
                        "file": binascii.hexlify(file.read()).decode(),
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp.result

        raise ValueError("Failed to invoke speech to text")

    def invoke_moderation(
        self,
        tenant_id: str,
        user_id: str | None,
        plugin_id: str,
        provider: str,
        model: str,
        credentials: dict[str, Any],
        text: str,
    ) -> bool:
        """
        Invoke moderation
        """
        response = self._request_with_plugin_daemon_response_stream(
            method="POST",
            path=f"plugin/{tenant_id}/dispatch/moderation/invoke",
            type_=PluginBasicBooleanResponse,
            data=jsonable_encoder(
                self._dispatch_payload(
                    user_id=user_id,
                    data={
                        "provider": provider,
                        "model_type": "moderation",
                        "model": model,
                        "credentials": credentials,
                        "text": text,
                    },
                )
            ),
            headers={
                "X-Plugin-ID": plugin_id,
                "Content-Type": "application/json",
            },
        )

        for resp in response:
            return resp.result

        raise ValueError("Failed to invoke moderation")

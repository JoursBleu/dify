from dify_plugin import ModelProvider
from dify_plugin.entities.model import AIModelEntity, ModelType
from dify_plugin.errors.model import InvokeError

from models._catalog import discover_models
from models._credentials import validate_api_key


class AMDTokenFactoryModelProvider(ModelProvider):
    def fetch_models(self, model_type: ModelType, credentials: dict) -> list[AIModelEntity]:
        """Native catalog hook; dispatch requires the paired, unreleased host stack."""
        if model_type != ModelType.LLM:
            return []
        return [AIModelEntity.model_validate(schema) for schema in discover_models(credentials)]

    def validate_provider_credentials(self, credentials: dict) -> None:
        if not callable(getattr(ModelProvider, "fetch_models", None)):
            raise InvokeError(
                "AMDTokenFactory requires the native model catalog RPC in the paired SDK, "
                "plugin-daemon, Dify and Graphon; this SDK cannot configure automatic discovery."
            )
        validate_api_key(credentials)
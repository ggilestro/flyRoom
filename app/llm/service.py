"""LLM service for AI-powered features via OpenRouter API."""

import logging

import httpx

from app.config import get_settings
from app.llm.schemas import LLMError, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with LLM APIs via OpenRouter.

    Uses httpx.AsyncClient to make requests to any OpenAI-compatible
    chat completions endpoint. Configured via application settings.

    Attributes:
        settings: Application settings containing LLM configuration.
        configured: Whether a valid API key is set.
    """

    def __init__(self):
        """Initialize the LLM service with settings."""
        self.settings = get_settings()
        self.configured = bool(self.settings.llm_api_key)
        if not self.configured:
            logger.warning("LLM service initialized without API key — AI features disabled")

    async def chat(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to the LLM API.

        Args:
            messages: List of conversation messages.
            model: Model identifier (defaults to settings.llm_default_model).
            temperature: Sampling temperature (defaults to settings.llm_temperature).
            max_tokens: Maximum tokens to generate (defaults to settings.llm_max_tokens).

        Returns:
            LLMResponse: The model's response with content, usage, and metadata.

        Raises:
            LLMError: If the service is not configured or the API call fails.
        """
        if not self.configured:
            raise ValueError(
                LLMError(
                    error_type="not_configured",
                    message="LLM service is not configured — set LLM_API_KEY in .env",
                ).model_dump_json()
            )

        resolved_model = model or self.settings.llm_default_model
        resolved_temperature = (
            temperature if temperature is not None else self.settings.llm_temperature
        )
        resolved_max_tokens = max_tokens or self.settings.llm_max_tokens

        payload = {
            "model": resolved_model,
            "messages": [msg.model_dump() for msg in messages],
            "temperature": resolved_temperature,
            "max_tokens": resolved_max_tokens,
        }

        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.settings.llm_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})

            return LLMResponse(
                content=content,
                model=data.get("model", resolved_model),
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                raw_response=data,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API error (HTTP {e.response.status_code}): {e.response.text}")
            raise ValueError(
                LLMError(
                    error_type="api_error",
                    message=f"LLM API returned HTTP {e.response.status_code}",
                    status_code=e.response.status_code,
                ).model_dump_json()
            ) from e

        except httpx.RequestError as e:
            logger.error(f"LLM network error: {e}")
            raise ValueError(
                LLMError(
                    error_type="network_error",
                    message=f"Failed to connect to LLM API: {e}",
                ).model_dump_json()
            ) from e

    async def ask(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Convenience method: send a prompt and get back just the text response.

        Args:
            prompt: The user prompt to send.
            system_prompt: Optional system prompt for context/instructions.
            model: Model identifier override.
            temperature: Sampling temperature override.
            max_tokens: Maximum tokens override.

        Returns:
            str: The model's text response.

        Raises:
            ValueError: If the service is not configured or the API call fails.
        """
        messages = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))

        response = await self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content


# Singleton instance
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the LLM service singleton.

    Returns:
        LLMService: The LLM service instance.
    """
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

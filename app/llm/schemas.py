"""Pydantic schemas for LLM integration."""

from typing import Any

from pydantic import BaseModel


class LLMMessage(BaseModel):
    """A single message in a chat conversation.

    Attributes:
        role: The role of the message sender (system, user, assistant).
        content: The message content.
    """

    role: str
    content: str


class LLMResponse(BaseModel):
    """Response from an LLM chat completion.

    Attributes:
        content: The generated text content.
        model: The model that generated the response.
        usage: Token usage information (prompt_tokens, completion_tokens, total_tokens).
        raw_response: The full raw response from the API.
    """

    content: str
    model: str
    usage: dict[str, int]
    raw_response: dict[str, Any]


class LLMError(BaseModel):
    """Structured error information from an LLM API call.

    Attributes:
        error_type: Category of the error (e.g. "api_error", "network_error", "not_configured").
        message: Human-readable error description.
        status_code: HTTP status code if applicable.
    """

    error_type: str
    message: str
    status_code: int | None = None

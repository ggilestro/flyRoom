"""Tests for LLM service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.llm.schemas import LLMError, LLMMessage, LLMResponse
from app.llm.service import LLMService, get_llm_service

# --- Schema tests ---


class TestLLMSchemas:
    """Tests for LLM Pydantic schemas."""

    def test_llm_message(self):
        """Test LLMMessage creation."""
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_llm_response(self):
        """Test LLMResponse creation."""
        resp = LLMResponse(
            content="Hi there",
            model="test-model",
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            raw_response={"id": "123"},
        )
        assert resp.content == "Hi there"
        assert resp.model == "test-model"
        assert resp.usage["total_tokens"] == 8

    def test_llm_error(self):
        """Test LLMError creation."""
        err = LLMError(error_type="api_error", message="Bad request", status_code=400)
        assert err.error_type == "api_error"
        assert err.status_code == 400

    def test_llm_error_without_status_code(self):
        """Test LLMError with no status code."""
        err = LLMError(error_type="network_error", message="Connection refused")
        assert err.status_code is None


# --- Service initialization tests ---


class TestLLMServiceInit:
    """Tests for LLMService initialization."""

    @patch("app.llm.service.get_settings")
    def test_init_with_api_key(self, mock_settings):
        """Test service is configured when API key is set."""
        mock_settings.return_value = MagicMock(llm_api_key="sk-test-key")
        service = LLMService()
        assert service.configured is True

    @patch("app.llm.service.get_settings")
    def test_init_without_api_key(self, mock_settings):
        """Test service is not configured when API key is empty."""
        mock_settings.return_value = MagicMock(llm_api_key="")
        service = LLMService()
        assert service.configured is False


# --- chat() tests ---


class TestLLMServiceChat:
    """Tests for LLMService.chat()."""

    def _mock_settings(self):
        """Create mock settings with LLM config."""
        settings = MagicMock()
        settings.llm_api_key = "sk-test-key"
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_default_model = "anthropic/claude-sonnet-4"
        settings.llm_temperature = 0.7
        settings.llm_max_tokens = 1024
        return settings

    def _mock_api_response(self):
        """Create a mock successful API response body."""
        return {
            "id": "gen-abc123",
            "model": "anthropic/claude-sonnet-4",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help?",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 6,
                "total_tokens": 16,
            },
        }

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_not_configured(self, mock_settings):
        """Test chat raises ValueError when not configured."""
        mock_settings.return_value = MagicMock(llm_api_key="")
        service = LLMService()

        with pytest.raises(ValueError, match="not_configured"):
            await service.chat([LLMMessage(role="user", content="Hi")])

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_success(self, mock_settings):
        """Test successful chat completion."""
        mock_settings.return_value = self._mock_settings()
        service = LLMService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_api_response()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await service.chat([LLMMessage(role="user", content="Hi")])

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello! How can I help?"
        assert result.model == "anthropic/claude-sonnet-4"
        assert result.usage["total_tokens"] == 16

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_custom_model(self, mock_settings):
        """Test chat with custom model parameter."""
        mock_settings.return_value = self._mock_settings()
        service = LLMService()

        api_response = self._mock_api_response()
        api_response["model"] = "openai/gpt-4o"

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            result = await service.chat(
                [LLMMessage(role="user", content="Hi")],
                model="openai/gpt-4o",
                temperature=0.0,
                max_tokens=256,
            )

        # Verify custom params were sent
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["model"] == "openai/gpt-4o"
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 256
        assert result.model == "openai/gpt-4o"

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_api_error(self, mock_settings):
        """Test chat handles HTTP errors from the API."""
        mock_settings.return_value = self._mock_settings()
        service = LLMService()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(ValueError, match="api_error"):
                await service.chat([LLMMessage(role="user", content="Hi")])

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_network_error(self, mock_settings):
        """Test chat handles network connectivity errors."""
        mock_settings.return_value = self._mock_settings()
        service = LLMService()

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(ValueError, match="network_error"):
                await service.chat([LLMMessage(role="user", content="Hi")])

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_chat_sends_auth_header(self, mock_settings):
        """Test that the API key is sent as a Bearer token."""
        mock_settings.return_value = self._mock_settings()
        service = LLMService()

        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_api_response()
        mock_response.raise_for_status = MagicMock()

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            await service.chat([LLMMessage(role="user", content="Hi")])

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test-key"


# --- ask() tests ---


class TestLLMServiceAsk:
    """Tests for LLMService.ask() convenience method."""

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_ask_returns_text(self, mock_settings):
        """Test ask() returns just the text content."""
        settings = MagicMock()
        settings.llm_api_key = "sk-test"
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_default_model = "test-model"
        settings.llm_temperature = 0.7
        settings.llm_max_tokens = 1024
        mock_settings.return_value = settings

        service = LLMService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": "42"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await service.ask("What is the meaning of life?")

        assert result == "42"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_ask_with_system_prompt(self, mock_settings):
        """Test ask() includes system prompt in messages."""
        settings = MagicMock()
        settings.llm_api_key = "sk-test"
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_default_model = "test-model"
        settings.llm_temperature = 0.7
        settings.llm_max_tokens = 1024
        mock_settings.return_value = settings

        service = LLMService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": "response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            await service.ask(
                "Analyze this genotype",
                system_prompt="You are a Drosophila genetics expert.",
            )

        call_kwargs = mock_post.call_args
        messages = call_kwargs.kwargs["json"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a Drosophila genetics expert."
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    @patch("app.llm.service.get_settings")
    async def test_ask_without_system_prompt(self, mock_settings):
        """Test ask() sends only user message when no system prompt."""
        settings = MagicMock()
        settings.llm_api_key = "sk-test"
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_default_model = "test-model"
        settings.llm_temperature = 0.7
        settings.llm_max_tokens = 1024
        mock_settings.return_value = settings

        service = LLMService()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            await service.ask("Hello")

        call_kwargs = mock_post.call_args
        messages = call_kwargs.kwargs["json"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


# --- Singleton tests ---


class TestGetLLMService:
    """Tests for the get_llm_service() singleton factory."""

    def test_returns_llm_service(self):
        """Test that get_llm_service returns an LLMService instance."""
        # Reset singleton
        import app.llm.service as svc

        svc._llm_service = None

        with patch("app.llm.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(llm_api_key="")
            service = get_llm_service()
            assert isinstance(service, LLMService)

        svc._llm_service = None  # Clean up

    def test_returns_same_instance(self):
        """Test singleton returns the same instance on repeated calls."""
        import app.llm.service as svc

        svc._llm_service = None

        with patch("app.llm.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(llm_api_key="")
            service1 = get_llm_service()
            service2 = get_llm_service()
            assert service1 is service2

        svc._llm_service = None  # Clean up

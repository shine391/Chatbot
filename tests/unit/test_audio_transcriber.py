"""Unit tests for AudioTranscriber."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.audio_transcriber import AudioTranscriber


@pytest.mark.asyncio
async def test_audio_transcriber_requires_api_key() -> None:
    """Should raise ValueError if API key is missing."""
    transcriber = AudioTranscriber(api_key="")
    with pytest.raises(ValueError, match="API key"):
        await transcriber.transcribe(audio_data=b"fake_audio_bytes")


@pytest.mark.asyncio
async def test_audio_transcriber_transcribes_bytes() -> None:
    """Should call Gemini API with audio part and return transcription text."""
    transcriber = AudioTranscriber(api_key="test-api-key")

    mock_response = MagicMock()
    mock_response.text = "Chào shop, mình muốn tư vấn mua ví da nam."

    mock_generate = AsyncMock(return_value=mock_response)
    transcriber._client = MagicMock()
    transcriber._client.aio = MagicMock()
    transcriber._client.aio.models = MagicMock()
    transcriber._client.aio.models.generate_content = mock_generate

    text = await transcriber.transcribe(
        audio_data=b"\x00\x01\x02\x03",
        mime_type="audio/mp3",
    )

    assert text == "Chào shop, mình muốn tư vấn mua ví da nam."
    assert mock_generate.call_count == 1

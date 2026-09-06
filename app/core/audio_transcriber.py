"""Audio transcription service using Google Gemini multimodal capabilities."""

import logging
from typing import Any

import httpx
from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger(__name__)


class AudioTranscriber:
    """Transcribes customer voice messages to text via Gemini multimodal."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model
        self._client: Any = None
        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)

    async def transcribe(
        self,
        audio_data: bytes | str,
        mime_type: str = "audio/mp3",
    ) -> str:
        """Transcribe audio bytes or audio URL into text.

        Args:
            audio_data: Raw audio bytes or an HTTP/HTTPS audio URL.
            mime_type: The audio MIME type (e.g. audio/mp3, audio/ogg, audio/wav, audio/m4a).

        Returns:
            The transcribed text string in Vietnamese.
        """
        if not self._client or not self._api_key:
            raise ValueError("Google Gemini API key is not configured for AudioTranscriber.")

        raw_bytes: bytes
        if isinstance(audio_data, str):
            if audio_data.startswith(("http://", "https://")):
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(audio_data)
                    resp.raise_for_status()
                    raw_bytes = resp.content
            else:
                raise ValueError("audio_data string must be a valid HTTP or HTTPS URL.")
        else:
            raw_bytes = audio_data

        audio_part = types.Part.from_bytes(data=raw_bytes, mime_type=mime_type)
        instruction = (
            "Hãy nghe và chép chính xác từng câu chữ trong file âm thanh này sang tiếng Việt. "
            "Chỉ trả về nội dung chép lời thực tế của người nói, tuyệt đối không thêm lời giải thích, "
            "không thêm mở đầu hoặc nhận xét."
        )

        prompt_part = types.Part.from_text(text=instruction)

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=[prompt_part, audio_part],
        )

        return (response.text or "").strip()

import asyncio
import io
import logging
import os
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from retries import with_retry

load_dotenv()

logger = logging.getLogger("quill.transcribe")

MOCK = os.getenv("QUILL_MOCK", "").lower() in ("1", "true")


def _client():
    if MOCK:
        from mocks import MockOpenAI
        return MockOpenAI()
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def transcribe(audio_path: Path) -> str:
    """Return a text transcript of an audio file via OpenAI Whisper."""
    async with aiofiles.open(audio_path, "rb") as f:
        data = await f.read()

    buf = io.BytesIO(data)
    buf.name = audio_path.name  # SDK uses the name to infer the audio format

    client = _client()

    model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")

    async def _call():
        buf.seek(0)  # reset for each retry attempt
        return await client.audio.transcriptions.create(file=buf, model=model)

    result = await with_retry(_call, attempts=3, base_delay=2.0, timeout=30.0,
                              label="whisper")
    logger.info("transcribed %s → %d chars", audio_path.name, len(result.text))
    return result.text


async def transcribe_and_save(audio_path: Path) -> Path:
    """Transcribe audio and save the transcript alongside the source file.

    Returns the path of the saved .txt file.
    """
    transcript = await transcribe(audio_path)
    txt_path = audio_path.with_suffix(".txt")
    async with aiofiles.open(txt_path, "w", encoding="utf-8") as f:
        await f.write(transcript)
    logger.info("saved → %s", txt_path.name)
    return txt_path


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    if len(sys.argv) < 2:
        print("usage: python transcribe.py <audio.ogg>")
        raise SystemExit(1)

    result = asyncio.run(transcribe(Path(sys.argv[1])))
    print(result)

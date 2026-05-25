import asyncio
import base64
import logging
import os
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from retries import with_retry

load_dotenv()

logger = logging.getLogger("quill.describe")

MOCK = os.getenv("QUILL_MOCK", "").lower() in ("1", "true")

_PROMPT = (
    "Describe this image in one or two sentences as it might appear in a personal biography. "
    "Focus on atmosphere, setting, and any human elements. Be evocative but concise."
)


def _client():
    if MOCK:
        from mocks import MockOpenAI
        return MockOpenAI()
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def describe(image_path: Path) -> str:
    """Return a biography-ready caption for an image via GPT-4o Vision."""
    async with aiofiles.open(image_path, "rb") as f:
        data = await f.read()

    b64 = base64.b64encode(data).decode("utf-8")
    mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    client = _client()
    payload = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                },
                {"type": "text", "text": _PROMPT},
            ],
        }
    ]

    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")
    result = await with_retry(
        lambda: client.chat.completions.create(
            model=model, max_tokens=150, messages=payload
        ),
        attempts=3, base_delay=2.0, timeout=30.0, label="gpt4o-vision",
    )
    caption = result.choices[0].message.content
    logger.info("described %s → %d chars", image_path.name, len(caption))
    return caption


async def describe_and_save(image_path: Path) -> Path:
    """Describe an image and save the caption alongside the source file.

    Returns the path of the saved .txt file.
    """
    caption = await describe(image_path)
    txt_path = image_path.with_suffix(".txt")
    async with aiofiles.open(txt_path, "w", encoding="utf-8") as f:
        await f.write(caption)
    logger.info("saved → %s", txt_path.name)
    return txt_path


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    if len(sys.argv) < 2:
        print("usage: python describe.py <image.jpg>")
        raise SystemExit(1)

    result = asyncio.run(describe(Path(sys.argv[1])))
    print(result)

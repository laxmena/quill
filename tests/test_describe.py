import pytest
from describe import describe, describe_and_save


async def test_describe_returns_nonempty_string(jpg_file):
    result = await describe(jpg_file)
    assert isinstance(result, str)
    assert result.strip()


async def test_describe_and_save_creates_txt(jpg_file):
    txt_path = await describe_and_save(jpg_file)
    assert txt_path.exists()
    assert txt_path.suffix == ".txt"
    assert txt_path.stem == jpg_file.stem


async def test_describe_and_save_content_is_nonempty(jpg_file):
    txt_path = await describe_and_save(jpg_file)
    assert txt_path.read_text(encoding="utf-8").strip()


async def test_describe_accepts_png(tmp_inbox):
    png = tmp_inbox / "2024-05-11_090000_photo.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    txt_path = await describe_and_save(png)
    assert txt_path.exists()
    assert txt_path.read_text().strip()


async def test_describe_accepts_jpeg_extension(tmp_inbox):
    jpeg = tmp_inbox / "2024-05-11_100000_photo.jpeg"
    jpeg.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 16)
    txt_path = await describe_and_save(jpeg)
    assert txt_path.exists()

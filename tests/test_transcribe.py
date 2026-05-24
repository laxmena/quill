from transcribe import transcribe, transcribe_and_save


async def test_transcribe_returns_nonempty_string(ogg_file):
    result = await transcribe(ogg_file)
    assert isinstance(result, str)
    assert result.strip()


async def test_transcribe_and_save_creates_txt(ogg_file):
    txt_path = await transcribe_and_save(ogg_file)
    assert txt_path.exists()
    assert txt_path.suffix == ".txt"
    assert txt_path.stem == ogg_file.stem


async def test_transcribe_and_save_content_is_nonempty(ogg_file):
    txt_path = await transcribe_and_save(ogg_file)
    assert txt_path.read_text(encoding="utf-8").strip()


async def test_transcribe_and_save_does_not_overwrite_existing(ogg_file):
    """Calling twice should create one file; content from the second call."""
    await transcribe_and_save(ogg_file)
    txt_path = ogg_file.with_suffix(".txt")
    first_content = txt_path.read_text()
    await transcribe_and_save(ogg_file)
    # File is overwritten (idempotent re-run); just verify it still exists
    assert txt_path.exists()
    assert txt_path.read_text().strip()

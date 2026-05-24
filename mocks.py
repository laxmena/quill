"""
Mock clients for OpenAI and Anthropic. Active when QUILL_MOCK=true in .env.

Every class is a drop-in for its real SDK counterpart:
  MockOpenAI    →  openai.AsyncOpenAI
  MockAnthropic →  anthropic.AsyncAnthropic

Response shapes mirror the real types field-for-field so downstream code
works identically in mock and production mode.
"""
import asyncio
import random

# ── Realistic sample data ─────────────────────────────────────────────────────

_TRANSCRIPTS = [
    "Had a really good coffee this morning while reading. The fog outside was thick and the city felt far away.",
    "Went for a long walk along the waterfront today. I ended up sitting at the pier for almost an hour.",
    "Called Mum this evening. She's doing well. We talked about the garden and her neighbour's new dog.",
    "Finished Middlemarch today. Took me six weeks. George Eliot is astonishing — I feel bereft now it's over.",
    "Tried a new pasta recipe tonight. Cacio e pepe, properly made. Better than expected, honestly.",
    "Sat in the garden this afternoon. The light at around four o'clock was extraordinary — everything golden.",
    "Spent the morning at the library. Got through a lot. There's something about that particular silence.",
]

_CAPTIONS = [
    "A sunlit wooden desk bearing an open book, a ceramic coffee mug, and morning light falling across crowded bookshelves.",
    "An outdoor path lined with tall trees at dusk, warm golden light filtering through the canopy overhead.",
    "A kitchen counter with fresh vegetables — tomatoes, courgette, a bunch of basil — arranged beside a worn cutting board.",
    "A quiet residential street seen through a window, soft morning light and an empty pavement.",
    "A handwritten note on cream paper, the ink slightly smudged at the margins as if written quickly.",
    "Two coffee cups on a small café table, one half-drunk, afternoon light cutting across the surface.",
]

_BIOGRAPHY_PASSAGE = """\
<h2>The Texture of These Days</h2>

<p>The fortnight unfolded with the quiet momentum of ordinary life made luminous by
attention. There were mornings given over to reading — long, unhurried stretches before
the city woke — and afternoons shaped by walks whose destinations mattered far less than
the thinking they permitted.</p>

<p>A call home carried the particular warmth of a voice that has known you longest. A
finished novel brought the bittersweet satisfaction of having lived inside another
consciousness for weeks. These fragments, gathered and held together, form something
larger than their parts: a portrait of a life being thoughtfully lived.</p>

<div class="divider">✦</div>

<p>Food appeared as a recurring motif — not mere sustenance but an act of care, of
deliberate making. The kitchen became a place of small experiments, each one a quiet
assertion that the evening was worth attending to.</p>
"""


# ── OpenAI response types ─────────────────────────────────────────────────────

class _Transcription:
    """Mirrors openai.types.audio.Transcription"""
    def __init__(self, text: str) -> None:
        self.text     = text
        self.task     = "transcribe"
        self.language = "english"
        self.duration = round(random.uniform(12.0, 90.0), 2)
        self.segments = []
        self.words    = []


class _ChatMessage:
    """Mirrors openai.types.chat.ChatCompletionMessage"""
    def __init__(self, content: str) -> None:
        self.content       = content
        self.role          = "assistant"
        self.function_call = None
        self.tool_calls    = None


class _ChatChoice:
    """Mirrors openai.types.chat.Choice"""
    def __init__(self, content: str) -> None:
        self.message      = _ChatMessage(content)
        self.finish_reason = "stop"
        self.index        = 0
        self.logprobs     = None


class _ChatCompletion:
    """Mirrors openai.types.chat.ChatCompletion"""
    def __init__(self, content: str) -> None:
        self.choices    = [_ChatChoice(content)]
        self.model      = "gpt-4o"
        self.object     = "chat.completion"
        self.created    = 1_700_000_000
        self.id         = "mock-chatcmpl-000"
        self.usage      = _make_usage(128, 64)


# ── Anthropic response types ──────────────────────────────────────────────────

class _ContentBlock:
    """Mirrors anthropic.types.TextBlock"""
    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _AnthropicMessage:
    """Mirrors anthropic.types.Message"""
    def __init__(self, text: str) -> None:
        self.content     = [_ContentBlock(text)]
        self.model       = "claude-opus-4-7"
        self.stop_reason = "end_turn"
        self.role        = "assistant"
        self.type        = "message"
        self.id          = "mock-msg-000"
        self.usage       = _make_usage(1024, 512)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_usage(input_tokens: int, output_tokens: int):
    return type("Usage", (), {
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
    })()


# ── Mock OpenAI client ────────────────────────────────────────────────────────

class _MockAudioTranscriptions:
    async def create(self, *, file, model: str = "whisper-1", **kwargs) -> _Transcription:
        await asyncio.sleep(0.15)
        return _Transcription(random.choice(_TRANSCRIPTS))


class _MockAudio:
    def __init__(self) -> None:
        self.transcriptions = _MockAudioTranscriptions()


class _MockChatCompletions:
    async def create(self, *, model: str, messages: list, **kwargs) -> _ChatCompletion:
        await asyncio.sleep(0.2)
        return _ChatCompletion(random.choice(_CAPTIONS))


class _MockChat:
    def __init__(self) -> None:
        self.completions = _MockChatCompletions()


class MockOpenAI:
    """Drop-in for openai.AsyncOpenAI."""
    def __init__(self, api_key: str = "") -> None:
        self.audio = _MockAudio()
        self.chat  = _MockChat()


# ── Mock Anthropic client ─────────────────────────────────────────────────────

class _MockAnthropicMessages:
    async def create(self, *, model: str, max_tokens: int,
                     messages: list, **kwargs) -> _AnthropicMessage:
        await asyncio.sleep(0.3)
        return _AnthropicMessage(_BIOGRAPHY_PASSAGE)


class MockAnthropic:
    """Drop-in for anthropic.AsyncAnthropic."""
    def __init__(self, api_key: str = "") -> None:
        self.messages = _MockAnthropicMessages()

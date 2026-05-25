# Quill — Architecture

## Overview

Quill is a single-machine Python application structured as a linear pipeline. Each stage is an independent async module with a clean public API. The pipeline is orchestrated by `processor.py`, which also runs a daily scheduler. Every stage can be invoked standalone for development and debugging.

---

## System Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                            Your Telegram                               │
│                    (voice notes · photos · text)                       │
└───────────────────────────────┬────────────────────────────────────────┘
                                │  webhook POST  /  polling
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│  bot.py                                                               │
│  • Receives Telegram updates                                          │
│  • Saves .ogg, .jpg, and .txt files to inbox/ with timestamp names   │
│  • Replies "Got it. 🖊" to every message                              │
│  • Supports webhook mode (public URL) or polling (any machine)        │
└───────────────────────────────┬───────────────────────────────────────┘
                                │  YYYY-MM-DD_HHMMSS_{kind}.{ext}
                                ▼
                          ┌─────────────┐
                          │   inbox/    │  ◀── raw captured content
                          └──────┬──────┘
                                 │
                    ┌────────────▼────────────┐
                    │      processor.py        │
                    │  (scheduler/orchestrator)│
                    │  runs daily at           │
                    │  PROCESSING_HOUR         │
                    └────┬──────────┬──────────┘
                         │          │
              .ogg files │          │ .jpg / .png files
                         ▼          ▼
              ┌───────────────┐  ┌───────────────┐
              │ transcribe.py │  │  describe.py   │
              │ OpenAI Whisper│  │ GPT-4o Vision  │
              │ .ogg → .txt   │  │ .jpg  → .txt   │
              └───────┬───────┘  └───────┬────────┘
                      │                  │
                      └────────┬─────────┘
                               │  .txt files (all kinds)
                               ▼
                    ┌──────────────────────┐
                    │    synthesize.py      │
                    │    Claude Opus        │
                    │    .txt × N →         │
                    │    _content.html      │
                    └──────────┬───────────┘
                               │  biography inner HTML
                               ▼
                    ┌──────────────────────┐
                    │      render.py        │
                    │      Playwright       │
                    │      HTML → .html     │
                    │              → .pdf   │
                    └──────────┬───────────┘
                               │  A4 PDF
                               ▼
                    ┌──────────────────────┐
                    │      deliver.py       │
                    │      Gmail SMTP       │
                    │      PDF → email      │
                    └──────────┬───────────┘
                               │
                               ▼
                         📬  Your inbox
                               │
                    ┌──────────▼───────────┐
                    │     processed/        │  ◀── archived source files
                    └───────────────────────┘
```

---

## Module Reference

### `bot.py` — Telegram Gateway

**Purpose:** Receive messages from Telegram and persist them to `inbox/`.

**Modes:**
- **Webhook** — Telegram POSTs updates to `https://<WEBHOOK_URL>/<BOT_TOKEN>`. Requires a public HTTPS URL. The bot token is used as the URL path to prevent unauthenticated POSTs.
- **Polling** — Active when `TELEGRAM_WEBHOOK_URL` is not set. Works on any machine without a public URL.

**File naming:**

| Message type | Saved as |
|---|---|
| Text | `YYYY-MM-DD_HHMMSS_note.txt` |
| Voice | `YYYY-MM-DD_HHMMSS_voice.ogg` |
| Photo | `YYYY-MM-DD_HHMMSS_photo.jpg` (highest resolution `photo[-1]`) |

**Commands handled:**
- `/start` — welcome message with command descriptions and privacy disclosure
- `/status` — inbox count, last biography date, days until next chapter
- `/preview` — synthesise a draft biography for the current period and return structured plain text
- `/delete-last` — remove the most recent inbox entry (all files sharing its timestamp stem)
- `/help` — full command guide with privacy notice

**Message handlers:**
- `VOICE` — saves `.ogg`, replies with confirmation
- `PHOTO` — saves `.jpg` + optional caption `.txt`, tip for uncaptioned photos
- `TEXT` — saves `_note.txt`, replies with confirmation
- Fallback — any other message type replies with a hint to use voice, photo, or text

**Key dependencies:** `python-telegram-bot==20.7`, `aiofiles`

---

### `transcribe.py` — Audio Transcription

**Purpose:** Convert `.ogg` voice notes to `.txt` using OpenAI Whisper.

**Public API:**
```python
await transcribe(audio_path: Path) -> str
await transcribe_and_save(audio_path: Path) -> Path   # saves .txt alongside .ogg
```

**Flow:**
1. Read the `.ogg` file asynchronously with `aiofiles`
2. Wrap bytes in `io.BytesIO` with `.name` set so the SDK infers the audio format
3. Call `AsyncOpenAI.audio.transcriptions.create(model="whisper-1")`
4. Return `result.text`

**Mock:** `MockOpenAI` returns a random entry from `_TRANSCRIPTS` after 150 ms.

---

### `describe.py` — Image Captioning

**Purpose:** Generate a biography-appropriate caption for `.jpg`/`.png` photos using GPT-4o Vision.

**Public API:**
```python
await describe(image_path: Path) -> str
await describe_and_save(image_path: Path) -> Path   # saves .txt alongside image
```

**Flow:**
1. Read the image and base64-encode it
2. Build a chat completion request with an `image_url` content block (data URI) and a literary captioning prompt
3. `"detail": "high"` instructs GPT-4o to examine the full resolution

**Prompt:** *"Describe this image in one or two sentences as it might appear in a personal biography. Focus on atmosphere, setting, and any human elements. Be evocative but concise."*

**Mock:** `MockOpenAI` returns a random entry from `_CAPTIONS` after 200 ms.

---

### `synthesize.py` — Biography Synthesis

**Purpose:** Collect all processed `.txt` entries for a period and ask Claude to write a literary biography chapter.

**Data model:**
```python
@dataclass
class Entry:
    timestamp: datetime
    kind: str   # "note" | "voice" | "photo"
    text: str
```

**Public API:**
```python
await collect_entries(since, until, inbox_dir) -> list[Entry]
await synthesize(entries, period_start, period_end) -> str        # returns HTML
await synthesize_and_save(period_start, period_end, ...) -> tuple[Path, int]
```

**`collect_entries` logic:**
- Globs `inbox/*.txt`
- Parses `YYYY-MM-DD_HHMMSS_kind.txt` filenames to extract timestamp and kind
- Filters to the requested date range
- Skips empty files and unknown kinds
- Returns entries sorted chronologically

**Claude prompt:**
The system prompt instructs Claude to write in the voice of a Bloomsbury literary biographer — third person, evocative, attentive to texture. It specifies the exact HTML elements to use (`<h2>`, `<p>`, `<blockquote>`, `<div class="moment">`, `<div class="divider">`) so the output slots directly into `bloomsbury.html` without post-processing.

**Output:** Saves inner HTML to `biographies/YYYY-MM-DD_content.html`. Returns `(path, entry_count)`.

**Mock:** `MockAnthropic` returns `_BIOGRAPHY_PASSAGE` — a short, well-formed HTML excerpt — after 300 ms.

---

### `render.py` — PDF Rendering

**Purpose:** Inject biography HTML into the Bloomsbury template and render to A4 HTML + PDF.

**Public API:**
```python
await render(content_html, period_start, period_end, entry_count, biographies_dir) -> tuple[Path, Path]
await render_from_file(content_path, period_start, period_end, entry_count, biographies_dir) -> tuple[Path, Path]
```

**Template injection:** `_fill_template()` performs plain string replacement of `{{ placeholder }}` tokens in `bloomsbury.html`. No external template engine — no dependency on Jinja2.

**Playwright rendering:**
1. Write the complete HTML to `biographies/YYYY-MM-DD.html`
2. Load it via `file://` URL so relative `../fonts/` paths resolve
3. Call `page.pdf(format="A4", print_background=True, prefer_css_page_size=True)`

`prefer_css_page_size=True` delegates page geometry entirely to the stylesheet's `@page { size: A4; margin: ... }` declaration.

**A4 in browser:** `bloomsbury.html` includes a `@media screen` block that constrains `<body>` to `max-width: 210mm; min-height: 297mm` with a matching paper shadow, so the HTML renders at A4 dimensions when opened in a browser.

**Output files:**

| File | Description |
|---|---|
| `biographies/YYYY-MM-DD_content.html` | Raw inner HTML from Claude (intermediate) |
| `biographies/YYYY-MM-DD.html` | Complete, self-contained page (screen preview) |
| `biographies/YYYY-MM-DD.pdf` | Print-ready A4 PDF |

---

### `deliver.py` — Email Delivery

**Purpose:** Send the biography PDF to `BIOGRAPHY_RECIPIENT_EMAIL` via Gmail SMTP.

**Public API:**
```python
await deliver(pdf_path, period_start, period_end, entry_count) -> None
```

**SMTP strategy:** Uses `smtplib.SMTP_SSL` on port 465 (immediate TLS) wrapped in `asyncio.to_thread` to keep the event loop unblocked during the SMTP handshake and upload.

**Email structure:**
- **Subject:** `Your Quill Biography — 1 May – 14 May 2024`
- **Body:** Styled HTML with period metadata and entry count
- **Attachment:** The biography PDF

**Mock:** Logs the full delivery intent (subject, recipient, size, entry count) without opening a socket.

**Validation:** In real mode, raises `ValueError` if any of `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, or `BIOGRAPHY_RECIPIENT_EMAIL` are empty.

---

### `processor.py` — Orchestrator and Scheduler

**Purpose:** Chain all pipeline stages and run them on a schedule.

**Public API:**
```python
async def process_inbox(inbox_dir) -> int            # transcribe + describe
async def archive_inbox(until, inbox_dir, processed_dir) -> int
async def run_pipeline(period_start, period_end, ...) -> tuple[Path, Path]
def next_run_dt(from_dt=None) -> datetime
async def start_scheduler() -> None                 # blocks forever
```

**`run_pipeline` sequence:**
1. `process_inbox()` — transcribe all `.ogg`, describe all `.jpg/.png` without a `.txt` sidecar
2. `synthesize_and_save()` — synthesise all `.txt` in the period
3. `render_from_file()` — render to HTML + PDF
4. `deliver()` — email the PDF (if `deliver_email=True`)
5. `archive_inbox()` — move processed files to `processed/`
6. `save_state()` — persist `last_run_date` and `biography_count`

**Scheduler logic:**
- Sleeps until `PROCESSING_HOUR:00` each day
- On wake, checks `logs/state.json` for `last_run_date`
- Only runs if `(today − last_run_date).days ≥ BIOGRAPHY_PERIOD_DAYS`
- Catches and logs exceptions without crashing

**State file:** `logs/state.json`
```json
{
  "last_run_date": "2024-05-14",
  "biography_count": 3
}
```

---

### `cli.py` — Command-Line Interface

**Purpose:** Manual controls and one-off triggers using Click.

| Command | What it does |
|---|---|
| `status` | Inbox item counts by kind, last biography date, total PDF count |
| `process-inbox` | Run transcribe + describe without synthesising |
| `run [--from DATE] [--to DATE] [--no-email]` | Full pipeline |
| `preview [--from DATE] [--to DATE]` | Full pipeline, no email |
| `set-webhook` | Register webhook URL with Telegram API |
| `start` | Start the background scheduler |

---

### `mocks.py` — Simulation Layer

**Purpose:** Drop-in replacements for all external API clients. Active when `QUILL_MOCK=true`.

**Design principle:** Every mock class mirrors the real SDK type's public surface exactly — same attribute names, same response shapes, same method signatures. Downstream code works identically in mock and production mode.

| Mock | Replaces | Response type | Simulated latency |
|---|---|---|---|
| `MockOpenAI` | `openai.AsyncOpenAI` | — | — |
| `._MockAudioTranscriptions` | `AsyncOpenAI.audio.transcriptions` | `_Transcription` (`.text`, `.language`, `.duration`) | 150 ms |
| `._MockChatCompletions` | `AsyncOpenAI.chat.completions` | `_ChatCompletion` (`.choices[0].message.content`) | 200 ms |
| `MockAnthropic` | `anthropic.AsyncAnthropic` | — | — |
| `._MockAnthropicMessages` | `AsyncAnthropic.messages` | `_AnthropicMessage` (`.content[0].text`, `.stop_reason`, `.usage`) | 300 ms |

---

## File Lifecycle

```
Telegram message
      │
      ▼  bot.py saves
inbox/2024-05-10_143022_voice.ogg      ← raw voice note
inbox/2024-05-10_150000_photo.jpg      ← raw photo
inbox/2024-05-10_162200_note.txt       ← text note (already .txt)

      │  process_inbox() runs
      ▼  transcribe / describe
inbox/2024-05-10_143022_voice.txt      ← transcript (sidecar)
inbox/2024-05-10_150000_photo.txt      ← caption (sidecar)

      │  synthesize_and_save() runs
      ▼
biographies/2024-05-14_content.html    ← inner HTML from Claude

      │  render_from_file() runs
      ▼
biographies/2024-05-14.html            ← complete A4 HTML page
biographies/2024-05-14.pdf             ← print-ready A4 PDF

      │  deliver() runs
      ▼
📬 email delivered

      │  archive_inbox() runs
      ▼
processed/2024-05-10_143022_voice.ogg  ← moved here
processed/2024-05-10_143022_voice.txt
processed/2024-05-10_150000_photo.jpg
processed/2024-05-10_150000_photo.txt
processed/2024-05-10_162200_note.txt
```

**Naming convention:** `YYYY-MM-DD_HHMMSS_{kind}.{ext}`

- `kind` ∈ `{note, voice, photo}`
- Sidecar `.txt` files always share the stem of the source media file
- `synthesize.py` only reads `.txt` files — it never touches raw media
- `archive_inbox` moves all files whose date ≤ `period_end`

---

## External Services

| Service | Used by | Purpose | Fallback in mock mode |
|---|---|---|---|
| Telegram Bot API | `bot.py` | Receive messages, send replies | Not mocked (bot must run on a machine with internet) |
| OpenAI Whisper (`whisper-1`) | `transcribe.py` | Speech-to-text | `_TRANSCRIPTS` pool |
| OpenAI GPT-4o Vision | `describe.py` | Image captioning | `_CAPTIONS` pool |
| Anthropic Claude (`claude-opus-4-7`) | `synthesize.py` | Biography synthesis | `_BIOGRAPHY_PASSAGE` |
| Gmail SMTP (port 465) | `deliver.py` | Email delivery | Logs intent, no socket |

---

## Template System

`templates/bloomsbury.html` is a standalone HTML document with two roles:

1. **PDF master** — Playwright loads it via `file://` and renders to A4 using `@page { size: A4; margin: ... }`. Page numbers are injected via CSS `counter(page)` in `@bottom-center`.

2. **Browser preview** — `@media screen` styles constrain the body to `210mm × 297mm` with a warm grey background and paper shadow, approximating the printed page in a browser.

**Template tokens** (replaced by `render._fill_template`):

| Token | Value |
|---|---|
| `{{ title }}` | `Lakshmanan Meiyappan — May 2024` |
| `{{ user_name }}` | Full name from `USER_NAME` |
| `{{ subtitle }}` | `A chronicle of Lakshmanan's life, 1 May to 14 May 2024` |
| `{{ period_start }}` | `1 May 2024` |
| `{{ period_end }}` | `14 May 2024` |
| `{{ content }}` | Inner HTML from Claude |
| `{{ generated_date }}` | `24 May 2024` |
| `{{ entry_count }}` | `23` |

**HTML classes emitted by Claude** (referenced in the prompt, styled in the template):

| Class | Element | Purpose |
|---|---|---|
| `.cover` | `<div>` | Full-page cover with page-break-after |
| `.moment` | `<div>` | Isolated scene card with left border |
| `.moment-date` | `<p>` | Small-caps date label inside a moment |
| `.divider` | `<div>` | Centred `✦` section separator |
| `.colophon` | `<p>` | Footer attribution line |

---

## Testing Strategy

The test suite has 95+ tests across 9 modules. All tests run with `QUILL_MOCK=true` (set in `conftest.py` before any import) so no real API calls, network connections, or SMTP sessions occur.

| File | Tests | What it covers |
|---|---|---|
| `test_transcribe.py` | 4 | Return type, file creation, content, idempotency |
| `test_describe.py` | 5 | Return type, file creation, PNG/JPEG extensions |
| `test_synthesize.py` | 11 | Entry parsing, date filtering, empty/unknown kinds, synthesis, save |
| `test_render.py` | 9 | Template substitution, HTML validity, file creation, PDF creation |
| `test_deliver.py` | 7 | Mock path, SMTP not called, credential validation, message structure |
| `test_processor.py` | 15 | Inbox processing, archiving, scheduler timing, state persistence, end-to-end pipeline |

**Playwright** is replaced by a `mock_playwright` fixture in `conftest.py` that intercepts `render.async_playwright` and writes `b"%PDF-1.4 mock"` to disk without launching a browser.

**`monkeypatch.setattr`** is used to test real-mode branches (e.g., `deliver.MOCK = False`) without changing the environment.

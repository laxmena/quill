# Quill — Personal Historian

> Capture your life through Telegram. Receive a beautifully typeset biography PDF every two weeks.

You send Quill voice notes, photos, and text throughout your days. Every two weeks — at 2 AM while you sleep — Quill transcribes your voice, captions your photos, and asks Claude to weave everything into flowing biographical prose. It renders the result into a print-ready A4 PDF using a Bloomsbury-inspired typographic template, and delivers it to your inbox.

The result is a living chronicle. A record of your life as it actually happened, in language worthy of it.

---

## Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running Quill](#running-quill)
- [CLI Reference](#cli-reference)
- [Development](#development)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Architecture](#architecture)

---

## How It Works

```
You (Telegram)
     │  voice notes · photos · text
     ▼
  bot.py  ──────────────────────────────────────▶  inbox/
                                                      │
                                             processor.py  (scheduler)
                                            ┌────────┤
                                            │        │
                                     transcribe   describe
                                     (Whisper)   (GPT-4o)
                                            │        │
                                            └───┬────┘
                                                │  .txt files
                                                ▼
                                          synthesize.py
                                          (Claude Opus)
                                                │  biography HTML
                                                ▼
                                           render.py
                                          (Playwright)
                                                │  A4 PDF
                                                ▼
                                           deliver.py
                                          (Gmail SMTP)
                                                │
                                                ▼
                                         📬 Your inbox
```

| Stage | Module | Service | Input → Output |
|---|---|---|---|
| Capture | `bot.py` | Telegram webhook / polling | Messages → `inbox/` files |
| Transcribe | `transcribe.py` | OpenAI Whisper | `.ogg` → `.txt` |
| Caption | `describe.py` | GPT-4o Vision | `.jpg/.png` → `.txt` |
| Synthesise | `synthesize.py` | Claude Opus | `.txt` × N → biography HTML |
| Render | `render.py` | Playwright + Chromium | HTML → A4 PDF + HTML |
| Deliver | `deliver.py` | Gmail SMTP | PDF → email |
| Orchestrate | `processor.py` | — | Schedules and chains all stages |
| Control | `cli.py` | — | Manual triggers via terminal |

---

## Prerequisites

- Python 3.11 or later
- A [Telegram bot token](https://core.telegram.org/bots/tutorial) from @BotFather
- An [Anthropic API key](https://console.anthropic.com)
- An [OpenAI API key](https://platform.openai.com)
- A Gmail account with an [App Password](https://support.google.com/accounts/answer/185833) (not your regular password)
- Chromium for Playwright (`playwright install chromium`)

> **No public URL?** Leave `TELEGRAM_WEBHOOK_URL` blank and the bot runs in polling mode — no server or tunnel required.

> **No API keys yet?** Set `QUILL_MOCK=true` to run the entire pipeline with realistic simulated responses.

---

## Installation

**1. Clone the repository**

```bash
git clone https://github.com/laxmena/quill.git ~/quill
cd ~/quill
```

**2. Create a virtual environment**

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
playwright install chromium
```

**4. Create runtime directories**

These are gitignored and must be created locally:

```bash
mkdir -p inbox processed biographies logs
touch logs/quill.log
```

**5. Configure your environment**

```bash
cp .env.template .env
# open .env and fill in your keys
```

---

## Configuration

All configuration lives in `.env`. Copy `.env.template` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✓ | — | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_URL` | — | — | Public HTTPS base URL for webhook mode. Leave blank for polling. |
| `TELEGRAM_WEBHOOK_SECRET` | — | — | Random secret validated in `X-Telegram-Bot-Api-Secret-Token`. Set to a long random string when using webhook mode. |
| `TELEGRAM_ALLOWED_CHAT_ID` | — | — | Your Telegram numeric chat ID. When set, all other users are silently ignored. Find yours via @userinfobot. |
| `ANTHROPIC_API_KEY` | ✓* | — | API key for Claude (synthesis) |
| `OPENAI_API_KEY` | ✓* | — | API key for Whisper + GPT-4o (transcription + captions) |
| `GMAIL_ADDRESS` | ✓* | — | Gmail address used to send biographies |
| `GMAIL_APP_PASSWORD` | ✓* | — | Gmail App Password (16-character, not your account password) |
| `BIOGRAPHY_RECIPIENT_EMAIL` | ✓* | — | Destination email for delivered PDFs |
| `USER_NAME` | — | `Lakshmanan Meiyappan` | Your name as it appears in the biography |
| `BIOGRAPHY_PERIOD_DAYS` | — | `14` | How many days each biography covers |
| `PROCESSING_HOUR` | — | `2` | Hour of day (0–23) when the scheduler runs |
| `QUILL_MOCK` | — | `false` | Set to `true` to simulate all API calls without real keys |

*Not required when `QUILL_MOCK=true`.

---

## Running Quill

### Start the Telegram bot

```bash
python bot.py
```

With `TELEGRAM_WEBHOOK_URL` set, the bot listens for Telegram webhooks on port 8080. Without it, polling mode starts automatically — works anywhere without a public URL.

The Rich startup banner shows the active mode:

```
╭─────────────────────────────────╮
│ Quill  personal historian       │
╰─────────────────────────────────╯
  mode    polling
  inbox   /Users/you/quill/inbox
  port    8080
```

### Start the scheduler

The scheduler runs the full biography pipeline on a recurring schedule. It fires once a day at `PROCESSING_HOUR` and only generates a biography when at least `BIOGRAPHY_PERIOD_DAYS` have elapsed since the last one.

```bash
python processor.py
# or via CLI:
python cli.py start
```

### Run the pipeline manually

```bash
python cli.py run
python cli.py run --no-email          # skip delivery
python cli.py run --from 2024-01-01 --to 2024-01-14
```

### Preview without sending

Runs the full pipeline (transcribe → synthesize → render) but does not deliver the email. Opens a draft PDF.

```bash
python cli.py preview
python cli.py preview --from 2024-05-01 --to 2024-05-14
```

---

## CLI Reference

```
python cli.py --help
```

| Command | Description |
|---|---|
| `status` | Inbox item counts, last biography date, total generated |
| `process-inbox` | Transcribe voice notes and caption photos without synthesising |
| `run` | Full pipeline — transcribe → synthesise → render → deliver |
| `run --no-email` | Full pipeline, skip email delivery |
| `run --from DATE --to DATE` | Run for a specific date range |
| `preview` | Full pipeline without email (for proofing) |
| `set-webhook` | Register the Telegram webhook URL with Telegram's API |
| `start` | Start the background scheduler (runs indefinitely) |

---

## Development

### Mock mode

Set `QUILL_MOCK=true` in `.env` to run the entire pipeline without real API keys. Every external call — Whisper, GPT-4o Vision, Claude, Gmail SMTP — is replaced by a realistic mock that returns plausible data and simulates network latency.

```bash
QUILL_MOCK=true python cli.py run --no-email
```

The mocks are defined in `mocks.py` and mirror the real SDK types field-for-field:

| Mock class | Replaces | Key response fields |
|---|---|---|
| `MockOpenAI` | `openai.AsyncOpenAI` | `.audio.transcriptions`, `.chat.completions` |
| `MockAnthropic` | `anthropic.AsyncAnthropic` | `.messages` |

### Running a single pipeline step

Each module is also a standalone script:

```bash
python bot.py                                                  # start the bot
python transcribe.py inbox/2024-05-10_143022_voice.ogg         # transcribe one file
python describe.py inbox/2024-05-10_150000_photo.jpg           # caption one photo
python synthesize.py 2024-05-01 2024-05-14                     # synthesise a period
python render.py biographies/2024-05-14_content.html           # render to PDF
python deliver.py biographies/2024-05-14.pdf                   # send by email
```

---

## Testing

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the full suite:

```bash
pytest
```

Run a specific module's tests:

```bash
pytest tests/test_synthesize.py -v
```

The test suite has 51 tests across 6 modules. `conftest.py` sets `QUILL_MOCK=true` before any import, so no real API calls or SMTP connections are made. Playwright is replaced by a fixture that writes a minimal PDF to disk.

```
tests/
  conftest.py          shared fixtures + QUILL_MOCK setup
  test_transcribe.py   4 tests
  test_describe.py     5 tests
  test_synthesize.py   11 tests
  test_render.py       9 tests
  test_deliver.py      7 tests
  test_processor.py    15 tests
```

---

## Project Structure

```
quill/
├── bot.py              Telegram bot — captures messages into inbox/
├── transcribe.py       Audio → text via OpenAI Whisper
├── describe.py         Image → caption via GPT-4o Vision
├── synthesize.py       Text entries → biography HTML via Claude
├── render.py           Biography HTML → A4 PDF via Playwright
├── deliver.py          PDF → email via Gmail SMTP
├── processor.py        Pipeline orchestrator and daily scheduler
├── cli.py              Click CLI — manual controls
├── mocks.py            Drop-in mock clients for all external APIs
│
├── templates/
│   └── bloomsbury.html  Typographic PDF template (Bloomsbury style)
├── fonts/              Drop .ttf / .woff2 files here
│
├── inbox/              Raw captured content (gitignored)
├── processed/          Archived content after biography generation (gitignored)
├── biographies/        Generated HTML and PDF files (gitignored)
├── logs/
│   └── quill.log       Runtime log (gitignored)
│   └── state.json      Scheduler state — last run date, biography count
│
├── tests/
│   ├── conftest.py
│   ├── test_transcribe.py
│   ├── test_describe.py
│   ├── test_synthesize.py
│   ├── test_render.py
│   ├── test_deliver.py
│   └── test_processor.py
│
├── docs/
│   ├── ARCHITECTURE.md
│   └── ARCHITECTURE.html
│
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .env.template
└── .gitignore
```

---

## Architecture

For a detailed breakdown of every module, data flow, file lifecycle, external services, and the mock system, see:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — Markdown (renders on GitHub)
- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — Standalone HTML (open in browser)

---

## PDF Template

The biography is rendered using `templates/bloomsbury.html`, a typographic template inspired by the Bloomsbury literary aesthetic — generous margins, elegant serif type, and careful whitespace.

To use custom fonts, drop `.ttf` or `.woff2` files into `fonts/` and reference them in the template's `@font-face` declarations. The template currently calls for Cormorant Garamond, freely available from [Google Fonts](https://fonts.google.com/specimen/Cormorant+Garamond).

The HTML version of the biography also renders at A4 dimensions in a browser via `@media screen` styles — useful for proofing before printing.

---

## License

MIT

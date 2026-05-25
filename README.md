# Quill — Personal Historian

> Capture your life through Telegram. Receive a beautifully typeset biography PDF, delivered on your schedule.

You send Quill voice notes, photos, and text throughout your days. On a configurable schedule — by default every two weeks, at 2 AM while you sleep — Quill transcribes your voice, captions your photos, and asks Claude to weave everything into flowing biographical prose. It renders the result into a print-ready A4 PDF using a Bloomsbury-inspired typographic template, and delivers it to your inbox.

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
                                       (claude-opus-4-7)
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
| Synthesise | `synthesize.py` | claude-opus-4-7 | `.txt` × N → biography HTML |
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

**3. Install dependencies and set up**

```bash
make setup
```

This installs all Python dependencies, creates the required runtime directories (`inbox/`, `processed/`, `biographies/`, `logs/`, `fonts/`), copies `.env.template` → `.env`, and installs the Playwright Chromium browser in one step.

Then open `.env` and fill in your keys.

**Prefer manual steps?**

```bash
pip install -r requirements.txt
playwright install chromium
mkdir -p inbox processed biographies logs fonts
touch logs/quill.log
cp .env.template .env
```

---

## Configuration

All configuration lives in `.env`. Copy `.env.template` to get started.

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✓ | — | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_URL` | — | — | Public HTTPS base URL for webhook mode. Leave blank for polling. |
| `TELEGRAM_WEBHOOK_SECRET` | — | — | Random secret validated in `X-Telegram-Bot-Api-Secret-Token`. Set to a long random string when using webhook mode. |
| `TELEGRAM_ALLOWED_CHAT_ID` | ✓ | — | Your Telegram numeric chat ID. Without this any user who finds your bot can invoke commands. Find yours via @userinfobot. |
| `ANTHROPIC_API_KEY` | ✓* | — | API key for Claude (synthesis) |
| `OPENAI_API_KEY` | ✓* | — | API key for Whisper + GPT-4o (transcription + captions) |
| `GMAIL_ADDRESS` | ✓* | — | Gmail address used to send biographies |
| `GMAIL_APP_PASSWORD` | ✓* | — | Gmail App Password (16-character, not your account password) |
| `BIOGRAPHY_RECIPIENT_EMAIL` | ✓* | — | Destination email for delivered PDFs |
| `USER_NAME` | — | `Your Name` | Your name as it appears in the biography |
| `BIOGRAPHY_PERIOD_DAYS` | — | `14` | How many days each biography covers |
| `PROCESSING_HOUR` | — | `2` | Hour of day (0–23) when the scheduler runs |
| `NUDGE_AFTER_DAYS` | — | `3` | Days of silence before a gentle capture reminder is sent. Set to `0` to disable. |
| `PORT` | — | `8443` | Webhook listen port. Open this port in your firewall when using webhook mode. |
| `ANTHROPIC_MODEL` | — | `claude-opus-4-7` | Claude model used for biography synthesis. Swap to any compatible model (e.g. `claude-sonnet-4-6`). |
| `OPENAI_VISION_MODEL` | — | `gpt-4o` | OpenAI model used for photo captioning. |
| `OPENAI_WHISPER_MODEL` | — | `whisper-1` | OpenAI model used for voice transcription. |
| `QUILL_MOCK` | — | `false` | Set to `true` to simulate all API calls without real keys |

*Not required when `QUILL_MOCK=true`.

---

## Running Quill

### One-time setup commands

After deploying for the first time, register your bot with Telegram:

```bash
# Register the bot command menu so Telegram shows / autocomplete
python cli.py set-commands

# Register the webhook URL (only needed if TELEGRAM_WEBHOOK_URL is set)
python cli.py set-webhook
```

These are idempotent — safe to re-run after any config change.

### Start the Telegram bot

```bash
python bot.py
```

With `TELEGRAM_WEBHOOK_URL` set, the bot listens for Telegram webhooks on port 8443 (configurable via `PORT` in `.env`). Without it, polling mode starts automatically — works anywhere without a public URL.

The Rich startup banner shows the active mode:

```
╭─────────────────────────────────╮
│ Quill  personal historian       │
╰─────────────────────────────────╯
  mode    polling
  inbox   /Users/you/quill/inbox
```

### Start the scheduler

The scheduler runs the full biography pipeline on a recurring schedule. It fires once a day at `PROCESSING_HOUR` and only generates a biography when at least `BIOGRAPHY_PERIOD_DAYS` have elapsed since the last one.

```bash
python processor.py
# or via CLI:
python cli.py start
```

> **Both processes must run simultaneously.** `bot.py` receives messages from Telegram; `processor.py` (or `cli.py start`) transcribes and synthesises them on schedule. If only one is running, messages are captured but biographies are never generated (or vice versa). Run them in separate terminals, a tmux session, or as systemd services.

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
| `status` | Inbox item counts, last biography date, days until next chapter |
| `process-inbox` | Transcribe voice notes and caption photos without synthesising |
| `run` | Full pipeline — transcribe → synthesise → render → deliver |
| `run --no-email` | Full pipeline, skip email delivery |
| `run --from DATE --to DATE` | Run for a specific date range |
| `preview` | Full pipeline without email (for proofing) |
| `set-webhook` | Register the Telegram webhook URL with Telegram's API |
| `set-commands` | Register the bot command menu with Telegram (native `/` autocomplete) |
| `start` | Start the background scheduler (runs indefinitely) |

**Bot commands**

| Command | Description |
|---|---|
| `/start` | Welcome message with privacy disclosure |
| `/status` | Items in inbox, last chapter date, days until next |
| `/preview` | Read a plain-text draft of the current period's biography |
| `/delete-last` | Remove the most recently captured item from the inbox |
| `/help` | List all commands with descriptions |

---

## Development

### Makefile targets

```bash
make setup   # create directories, copy .env, install Playwright
make test    # run pytest
make lint    # run ruff (install with pip install ruff)
```

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

The test suite has 113 tests across 10 modules. `conftest.py` sets `QUILL_MOCK=true` before any import, so no real API calls or SMTP connections are made. Playwright is replaced by a fixture that writes a minimal PDF to disk.

```
tests/
  conftest.py            shared fixtures + QUILL_MOCK setup
  test_transcribe.py     4 tests
  test_describe.py       5 tests
  test_synthesize.py     18 tests
  test_render.py         9 tests
  test_deliver.py        9 tests
  test_processor.py      23 tests
  test_retries.py        7 tests
  test_notify.py         4 tests
  test_bot_preview.py    23 tests
  test_cli.py            10 tests
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

## Troubleshooting

**Running Quill as a background service**

On Linux with systemd, create `/etc/systemd/system/quill-bot.service`:

```ini
[Unit]
Description=Quill Telegram Bot
After=network.target

[Service]
WorkingDirectory=/home/you/quill
ExecStart=/home/you/quill/.venv/bin/python bot.py
Restart=always
EnvironmentFile=/home/you/quill/.env

[Install]
WantedBy=multi-user.target
```

Create a matching `quill-scheduler.service` for `cli.py start`. Then `sudo systemctl enable --now quill-bot quill-scheduler`.

On macOS use a launchd plist, or simply run both in a `tmux` session.

**Biographies never arrive**
Start both processes: `python bot.py` (in one terminal) and `python cli.py start` (in another). The scheduler runs at `PROCESSING_HOUR` each day and only sends a biography when `BIOGRAPHY_PERIOD_DAYS` have elapsed.

**Playwright / Chromium errors**
Run `playwright install chromium` to install the browser. On low-memory servers you may need to reduce the number of concurrent processes or add a swap file.

**Gmail authentication fails**
Use a 16-character [App Password](https://support.google.com/accounts/answer/185833), not your regular Gmail password. Two-factor authentication must be enabled on the account.

**Bot doesn't receive messages**
If running without a public URL, ensure `TELEGRAM_WEBHOOK_URL` is blank so the bot falls back to polling. With a webhook, check that the port (8443) is open and `python cli.py set-webhook` was run after deploying.

**PDF renders in the wrong font**
Download [Cormorant Garamond](https://fonts.google.com/specimen/Cormorant+Garamond) and place the `.ttf` files in the `fonts/` directory. Without them the PDF falls back to the browser's default serif font.

**Recovering accidentally archived entries**
Files moved to `processed/` after a biography run are never deleted. To include them in a re-run, move them back to `inbox/` and run `python cli.py run --no-email` (or restart the scheduler). The `processed/` directory is gitignored; nothing is lost on disk.

---

## License

MIT

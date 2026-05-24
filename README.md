# Quill — Personal Historian

Quill is a personal historian that captures your life through Telegram and synthesizes it into a beautifully typeset biography PDF every two weeks. Send it voice notes, photos, and text throughout your days; Quill transcribes, describes, and weaves everything into a narrative delivered straight to your inbox.

---

## How It Works

```
You (Telegram)
     │
     ▼
  bot.py          ← receives messages, saves to inbox/
     │
     ▼
processor.py      ← orchestrates the pipeline on a schedule
  ├── transcribe.py   ← converts voice notes to text (OpenAI Whisper)
  ├── describe.py     ← captions images (GPT-4o Vision)
  └── synthesize.py   ← weaves everything into a narrative (Claude)
     │
     ▼
  render.py        ← renders narrative → PDF (Playwright + bloomsbury.html)
     │
     ▼
  deliver.py       ← emails the PDF to BIOGRAPHY_RECIPIENT_EMAIL
```

You can also trigger any step manually via `cli.py`.

---

## Project Structure

```
quill/
├── bot.py            # Telegram bot — receives and stores incoming content
├── processor.py      # Scheduled pipeline — runs synthesis every N days
├── transcribe.py     # Audio → text via OpenAI Whisper
├── describe.py       # Image → caption via GPT-4o Vision
├── synthesize.py     # All content → biography narrative via Claude
├── render.py         # Narrative HTML → PDF via Playwright
├── deliver.py        # PDF → email via Gmail SMTP
├── cli.py            # Manual CLI controls (trigger, status, preview, etc.)
├── requirements.txt
├── .env.template     # Copy to .env and fill in your keys
├── templates/
│   └── bloomsbury.html   # PDF layout and typography
├── fonts/            # Drop custom fonts here (referenced in bloomsbury.html)
├── inbox/            # Raw captured content lands here (gitignored)
├── processed/        # Archived content after biography generation (gitignored)
├── biographies/      # Final rendered PDFs (gitignored)
└── logs/
    └── quill.log     # Runtime logs (gitignored)
```

---

## Setup

### 1. Clone and enter the repo

```bash
git clone https://github.com/laxmena/quill.git
cd quill
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

```bash
cp .env.template .env
```

Open `.env` and fill in every variable:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS URL where Telegram delivers updates |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com) |
| `OPENAI_API_KEY` | From [platform.openai.com](https://platform.openai.com) |
| `GMAIL_ADDRESS` | Gmail address used to send biographies |
| `GMAIL_APP_PASSWORD` | Gmail App Password (not your account password) |
| `BIOGRAPHY_RECIPIENT_EMAIL` | Where the finished PDF is delivered |
| `USER_NAME` | Your name, as it should appear in the biography |
| `BIOGRAPHY_PERIOD_DAYS` | How many days each biography covers (default: 14) |
| `PROCESSING_HOUR` | Hour of day (0–23) when synthesis runs (default: 2) |

### 5. Create local runtime directories

These are gitignored and must be created manually:

```bash
mkdir -p inbox processed biographies logs
touch logs/quill.log
```

### 6. Set up the Telegram webhook

Once your bot is running at a public URL, register the webhook:

```bash
python cli.py set-webhook
```

---

## Running Each Component

### Start the Telegram bot

Listens for incoming messages and saves content to `inbox/`.

```bash
python bot.py
```

### Run the full pipeline manually

Transcribes, describes, synthesizes, renders, and delivers in one shot.

```bash
python processor.py --run-now
```

### Transcribe a specific audio file

```bash
python transcribe.py --file inbox/voice_20240115_143022.ogg
```

### Describe a specific image

```bash
python describe.py --file inbox/photo_20240115_143022.jpg
```

### Synthesize a biography from processed content

```bash
python synthesize.py --from 2024-01-01 --to 2024-01-14
```

### Render a biography HTML to PDF

```bash
python render.py --input biographies/2024-01-14.html --output biographies/2024-01-14.pdf
```

### Deliver a PDF by email

```bash
python deliver.py --file biographies/2024-01-14.pdf
```

### CLI commands

```bash
python cli.py --help          # List all commands
python cli.py status          # Show inbox content count and last run time
python cli.py preview         # Render a draft PDF without sending
python cli.py set-webhook     # Register the Telegram webhook URL
python cli.py trigger         # Manually trigger a full pipeline run
```

---

## Scheduling (macOS)

To have `processor.py` run automatically, add a launchd plist or a cron job:

```bash
# Run the processor daily at PROCESSING_HOUR (e.g. 2 AM)
crontab -e
# Add:
0 2 * * * /path/to/quill/.venv/bin/python /path/to/quill/processor.py
```

---

## PDF Template

The biography is rendered using `templates/bloomsbury.html`, a typographic template inspired by the Bloomsbury literary aesthetic — generous margins, elegant serif type, and careful whitespace. Drop `.ttf` or `.woff2` font files into `fonts/` and reference them from the template's `@font-face` declarations.

---

## License

MIT

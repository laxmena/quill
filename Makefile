.PHONY: setup test lint

setup:
	@echo "Installing Python dependencies..."
	pip install -r requirements.txt
	@echo "Creating runtime directories..."
	mkdir -p inbox processed biographies logs fonts
	touch logs/quill.log
	@if [ ! -f .env ]; then \
		cp .env.template .env; \
		echo "Created .env from template — open it and fill in your keys."; \
	else \
		echo ".env already exists, skipping."; \
	fi
	@echo "Installing Playwright browser..."
	playwright install chromium
	@echo ""
	@echo "Setup complete! Open .env and fill in:"
	@echo "  TELEGRAM_BOT_TOKEN       — from @BotFather"
	@echo "  TELEGRAM_ALLOWED_CHAT_ID — your numeric chat ID (find via @userinfobot)"
	@echo "  ANTHROPIC_API_KEY        — from console.anthropic.com"
	@echo "  OPENAI_API_KEY           — from platform.openai.com"
	@echo "  GMAIL_ADDRESS + GMAIL_APP_PASSWORD + BIOGRAPHY_RECIPIENT_EMAIL"
	@echo ""
	@echo "Then run: python bot.py   (in one terminal)"
	@echo "      and: python cli.py start   (in another)"

test:
	pytest

lint:
	ruff check .

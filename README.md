# VZhTelegram

Automated pipeline for the Telegram channel [@zharkov2much](https://t.me/zharkov2much).

Monitors 80+ sources (RSS, web, social media), scores articles by relevance, generates posts in the author's style via LLM (OpenRouter API), and sends drafts to a Telegram bot for review and one-click publishing.

## Architecture

```
[80+ Sources] → Collector → Scorer → Generator (LLM) → Telegram Bot → Channel
     RSS          dedup      weighted    OpenRouter      review UI     @zharkov2much
     Web          freshness  scoring     Anthropic       3 buttons
     Social       filter     selection   models          publish
```

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url> && cd VZhTelegram
pip install -e .

# 2. Configure
cp .env.example .env
# Edit .env with your API keys

# 3. Validate sources
python scripts/seed_sources.py

# 4. Run single cycle (dry-run, no bot)
python scripts/run_pipeline.py --mode once

# 5. Run bot + scheduler (production)
python scripts/run_pipeline.py --mode bot
```

## Docker

```bash
cp .env.example .env  # fill in keys
docker compose up -d
```

## Configuration

| File | Purpose |
|------|---------|
| `config/sources.yaml` | 80+ monitored sources with RSS URLs, categories, tiers |
| `config/scoring.yaml` | Scoring weights, thresholds, topic keywords |
| `config/style.yaml` | Author style prompt, example posts, format settings |
| `config/settings.yaml` | Pipeline intervals, DB path, LLM model selection |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for LLM generation |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `TELEGRAM_CHANNEL_ID` | Yes | Numeric ID of @zharkov2much |
| `TELEGRAM_ADMIN_CHAT_ID` | Yes | Your personal chat ID for draft review |
| `SCRAPECREATORS_API_KEY` | No | For Reddit/TikTok/Instagram via last30days |
| `BRAVE_API_KEY` | No | For web search via last30days |

## Bot Controls

Each draft arrives with 3 buttons:
- **Опубликовать** — publish to channel immediately
- **Перегенерировать** — regenerate with a different angle
- **Редактировать** — provide custom instructions for regeneration

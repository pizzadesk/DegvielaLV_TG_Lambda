# Latvia Fuel Prices Telegram Bot (AWS Lambda)

A Telegram bot that scrapes and compares fuel prices from multiple Latvia fuel providers and returns the data on demand.

## Features

- Aggregates prices from:
  - Circle K: https://www.circlek.lv/degviela-miles/degvielas-cenas
  - Neste: https://www.neste.lv/lv/content/degvielas-cenas
  - Virsi: https://www.virsi.lv/lv/privatpersonam/degviela/degvielas-un-elektrouzlades-cenas
  - Viada: https://www.viada.lv/zemakas-degvielas-cenas/
- Fuel name normalization across providers (for example, `95miles`/`95E`/`Neste Futura 95` -> `95`).
- Combined comparison output via `/fuel`.
- Cheapest-by-fuel lookup across all providers via `/price <fuel>`.
- Cheapest-per-fuel summary via `/best`.
- Provider-specific views via `/circlek`, `/neste`, `/virsi`, and `/viada`.
- Cache and scraper health inspection via `/status`.
- In-memory cache to reduce source-site requests.
- Webhook-compatible AWS Lambda handler.
- Buy Me a Coffee credit included in bot responses.

## Quickstart: Add Bot based on this framework To Telegram

1. Open Telegram and start a chat with `@BotFather`.
2. Run `/newbot`, choose a bot name and a unique username ending with `bot`.
3. Copy the bot token returned by BotFather.
4. Open AWS Lambda for this project and set environment variables:
   - `TELEGRAM_TOKEN=<your bot token>`
   - `TELEGRAM_SECRET=<your random secret>` (recommended)
5. Deploy your Lambda and copy its public HTTPS webhook URL.
6. Register webhook with Telegram:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"<YOUR_LAMBDA_WEBHOOK_URL>","secret_token":"<TELEGRAM_SECRET>"}'
```

7. In Telegram, open your bot chat and press Start or send `/start`.
8. Optional: add the bot to a group via group info -> Add Members, then grant needed admin permissions.

## Project Structure

- `lambda_function.py` - AWS Lambda webhook entrypoint.
- `fuel_price_telegram_bot/config.py` - environment configuration.
- `fuel_price_telegram_bot/scraper.py` - scraping, normalization, and caching logic.
- `fuel_price_telegram_bot/formatter.py` - response formatting logic.
- `fuel_price_telegram_bot/bot.py` - Telegram command handlers and app setup.
- `fuel_price_telegram_bot/__init__.py` - package exports.

## How It Works

1. Telegram sends webhook updates to your Lambda endpoint.
2. `lambda_function.py` validates request shape and optional secret header.
3. The update payload is converted to a Telegram `Update` object.
4. Command handlers in `fuel_price_telegram_bot/bot.py` process commands.
5. `fuel_price_telegram_bot/scraper.py` fetches and normalizes provider prices.
6. `fuel_price_telegram_bot/formatter.py` returns user-friendly message output.

## AWS Lambda Usage

### Environment Variables

Set these in Lambda configuration:

- `TELEGRAM_TOKEN` (required): Telegram bot token.
- `TARGET_URL` (optional): primary Circle K URL override.
- `TELEGRAM_SECRET` (optional): expected Telegram secret token for webhook verification.
- `ENABLED_PROVIDERS` (optional): comma-separated provider list such as `circlek,neste,virsi,viada`.

Default `TARGET_URL`:

- `https://www.circlek.lv/degviela-miles/degvielas-cenas` - because I personally use it often, not because I am sponsored or advertising in any commercial way.

### Lambda Handler

Use:

- `lambda_function.lambda_handler`

### Telegram Webhook Secret (optional)

If `TELEGRAM_SECRET` is set, Lambda checks incoming header:

- `x-telegram-bot-api-secret-token`

Mismatched secret returns `403 Forbidden`.

### Response Behavior

- `200 OK` on success.
- `400` for invalid or empty JSON body.
- `500` for invalid token/configuration/runtime errors.

## Local Development Notes

This repository stores source code only. Install dependencies from `requirements.txt`.

Install dependencies:

```bash
pip install -r requirements.txt
```

For quick local bot run (polling mode), execute:

```bash
python -m fuel_price_telegram_bot.bot
```

## Build Lambda Deployment Zip

Create a deployment zip (code + dependencies) with:

```powershell
./scripts/build_lambda_zip.ps1
```

This generates `lambda-deployment.zip` in the repository root.

## Automated GitHub Release Artifact

This repository includes a GitHub Actions workflow that builds and uploads `lambda-deployment.zip` to a GitHub Release when you push a version tag.

Example:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Continuous Integration

This repository includes a CI workflow that runs on push and pull requests:

- Installs dependencies from `requirements.txt`
- Compiles Python sources
- Runs import smoke checks for Lambda entrypoint and bot modules

## Telegram Commands

Command reference is documented in:

- [TELEGRAM_COMMANDS.md](TELEGRAM_COMMANDS.md)

Core commands include `/fuel`, `/price`, `/best`, `/status`, `/refresh`, and per-brand commands for each enabled provider.

## Third-Party Licenses

This repository depends on third-party packages installed from `requirements.txt`.

- See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for package-level license attributions.
- Keep that file when redistributing source or deployment artifacts.

## Credits

- Buy me a coffee: https://buymeacoffee.com/pizzadesk

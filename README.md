# Latvia Fuel Prices Telegram Bot Framework

AWS Lambda-friendly Telegram bot framework for scraping and comparing fuel prices from Latvia fuel providers.

The repository is usable as-is for the included providers, but it is also structured so you can fork it, deploy your own bot, choose which providers to expose, and define your own credit or support message through environment variables.

## What it does

- Scrapes prices from Circle K, Neste, Virsi, and Viada.
- Normalizes fuel names across providers into a consistent set.
- Serves Telegram commands and inline-button flows for browsing fuel prices.
- Caches results in memory to reduce repeated scraping.
- Runs behind an AWS Lambda webhook endpoint.
- Supports deployment-time customization through environment variables.

## Supported providers

- Circle K: https://www.circlek.lv/degviela-miles/degvielas-cenas
- Neste: https://www.neste.lv/lv/content/degvielas-cenas
- Virsi: https://www.virsi.lv/lv/privatpersonam/degviela/degvielas-un-elektrouzlades-cenas
- Viada: https://www.viada.lv/zemakas-degvielas-cenas/

## Project layout

- `lambda_function.py`: AWS Lambda webhook entrypoint.
- `fuel_price_telegram_bot/config.py`: environment-driven runtime configuration.
- `fuel_price_telegram_bot/scraper.py`: scraping, normalization, and cache management.
- `fuel_price_telegram_bot/formatter.py`: user-facing message formatting.
- `fuel_price_telegram_bot/bot.py`: Telegram handlers, callbacks, and application setup.
- `scripts/build_lambda_zip.ps1`: deployment zip builder for Lambda.

## How the request flow works

1. Telegram sends an update to your Lambda webhook URL.
2. `lambda_function.py` validates the request and optional Telegram secret header.
3. The payload is converted into a Telegram `Update` object.
4. `fuel_price_telegram_bot/bot.py` routes the command or button action.
5. `fuel_price_telegram_bot/scraper.py` fetches cached data or refreshes provider prices.
6. `fuel_price_telegram_bot/formatter.py` builds the response message.

## Environment variables

Set these in AWS Lambda or a local `.env` file.

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather. |
| `TELEGRAM_SECRET` | No | Secret used to validate the `x-telegram-bot-api-secret-token` webhook header. |
| `TARGET_URL` | No | Override for the primary Circle K source URL. Defaults to the built-in Circle K page. |
| `ENABLED_PROVIDERS` | No | Comma-separated provider list such as `circlek,neste,virsi,viada`. Defaults to all supported providers. |
| `CREDIT_MESSAGE` | No | Custom footer/support/credit text appended to price, status, and help messages. Set to an empty string to disable it entirely. |

### Default credit message

If `CREDIT_MESSAGE` is not provided, the framework uses the built-in support line:

```text
☕ Ja noderēja, kafijai. Ja ne, nu neko: buymeacoffee.com/pizzadesk
```

### Example Lambda configuration

```text
TELEGRAM_TOKEN=123456:example-token
TELEGRAM_SECRET=replace-with-random-secret
ENABLED_PROVIDERS=circlek,neste,virsi
CREDIT_MESSAGE=Built on DegvielaLV framework by YourProject. Support: https://example.com
```

## Deploy your own bot

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Deploy this repository to AWS Lambda.
3. Configure the environment variables listed above.
4. Expose the Lambda through a public HTTPS endpoint.
5. Register the webhook with Telegram.

Webhook registration example:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url":"<YOUR_LAMBDA_WEBHOOK_URL>","secret_token":"<TELEGRAM_SECRET>"}'
```

Lambda handler:

```text
lambda_function.lambda_handler
```

## Local development

Install dependencies:

```bash
pip install -r requirements.txt
```

Optional local `.env` example:

```text
TELEGRAM_TOKEN=123456:example-token
TELEGRAM_SECRET=replace-with-random-secret
ENABLED_PROVIDERS=circlek,neste,virsi,viada
CREDIT_MESSAGE=Custom footer text for your deployment
```

Start the bot locally in polling mode:

```bash
python -m fuel_price_telegram_bot.bot
```

## Build a Lambda deployment package

Create the deployment zip with:

```powershell
./scripts/build_lambda_zip.ps1
```

The script outputs `lambda-deployment.zip` in the repository root.

## Bot capabilities

- `/fuel`: full comparison for all available fuels.
- `/fuel <type>` and `/price <type>`: cheapest provider for one fuel.
- `/best`: cheapest provider for each fuel type.
- `/status`: cache details and provider health.
- `/refresh`: forces a refresh with cooldown protection.
- `/mode`: per-chat compact/full rendering preference.
- `/fav`: per-chat favorite fuels for faster menu access.
- `/circlek`, `/neste`, `/virsi`, `/viada`: provider-specific price views when enabled.

Full command behavior is documented in [TELEGRAM_COMMANDS.md](TELEGRAM_COMMANDS.md).

## Notes for framework users

- `ENABLED_PROVIDERS` controls both scraping and which provider commands are available.
- `CREDIT_MESSAGE` is deployment-specific, so forks can add their own support link or attribution without editing Python code.
- Setting `CREDIT_MESSAGE` to an empty string removes the footer credit from formatted responses.
- Status, fuel, best-price, and provider-specific messages all use the same configured credit value.

## Lambda responses

- `200 OK`: update accepted or console test without a webhook payload.
- `400 Bad Request`: invalid JSON or empty request body.
- `403 Forbidden`: webhook secret mismatch.
- `500 Internal Server Error`: invalid token, invalid configuration, or runtime failure.

## CI and release notes

This repository includes GitHub workflows that:

- install Python dependencies,
- compile Python sources,
- run import smoke checks,
- build `lambda-deployment.zip` for releases.

You can publish a tagged release artifact with:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Third-party notices

Dependencies are listed in `requirements.txt`.

- See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for package-level license notices.
- Keep that file when redistributing source or deployment artifacts.

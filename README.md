# Latvia Fuel Prices Telegram Bot Framework

AWS Lambda-friendly Telegram bot framework for scraping and comparing fuel prices from Latvia fuel providers.

The repository is usable as-is for the included providers, but it is also structured so you can fork it, deploy your own bot, choose which providers to expose, and define your own credit or support message through environment variables.

## What it does

- Scrapes prices from Circle K, Neste, Virsi, and Viada.
- Normalizes fuel names across providers into a consistent set.
- Serves Telegram commands and inline-button flows for browsing fuel prices.
- Stores price snapshots in S3 and rotates them when prices change, enabling price-change indicators (▲/▼) on all views.
- Caches results in memory to reduce repeated scraping.
- Runs behind an AWS Lambda webhook endpoint; a second EventBridge trigger refreshes the S3 snapshot on a schedule.
- Supports deployment-time customization through environment variables.

## Supported providers

- Circle K: https://www.circlek.lv/degviela-miles/degvielas-cenas
- Neste: https://www.neste.lv/lv/content/degvielas-cenas
- Virsi: https://www.virsi.lv/lv/privatpersonam/degviela/degvielas-un-elektrouzlades-cenas
- Viada: https://www.viada.lv/zemakas-degvielas-cenas/

## Project layout

- `lambda_function.py`: AWS Lambda entrypoint — handles both Telegram webhook updates and EventBridge scheduled snapshot triggers.
- `fuel_price_telegram_bot/config.py`: environment-driven runtime configuration.
- `fuel_price_telegram_bot/scraper.py`: scraping, normalization, and cache management.
- `fuel_price_telegram_bot/snapshot.py`: S3 snapshot read/write, price-change detection, and diff computation.
- `fuel_price_telegram_bot/formatter.py`: user-facing message formatting including price-change indicators.
- `fuel_price_telegram_bot/bot.py`: Telegram handlers, callbacks, and application setup.
- `scripts/build_lambda_zip.ps1`: deployment zip builder for Lambda.

## How the request flow works

### Telegram webhook (user-initiated)

1. Telegram sends an update to your Lambda webhook URL.
2. `lambda_function.py` validates the request and optional Telegram secret header.
3. The payload is converted into a Telegram `Update` object.
4. `fuel_price_telegram_bot/bot.py` routes the command or button action.
5. `fuel_price_telegram_bot/bot.py` reads price data from S3 `current.json` via `snapshot.py` (fast, ~100 ms). Falls back to a live scrape only if S3 data is missing or older than 3 hours.
6. `fuel_price_telegram_bot/formatter.py` builds the response message, including ▲/▼ diff indicators computed against `previous.json`.

### EventBridge scheduled trigger (background)

1. EventBridge fires the Lambda on your configured schedule (recommended: every 30–60 minutes).
2. `lambda_function.py` detects `event.source == 'aws.events'` and calls `_run_scheduled_snapshot()`.
3. All providers are scraped in parallel.
4. Scraped prices are compared to `current.json`. If any price changed, `current.json` is rotated to `previous.json` and new data is written as `current.json` with an updated `changed_at` timestamp. If prices are unchanged only `scraped_at` is updated.

## Environment variables

Set these in AWS Lambda or a local `.env` file.

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Bot token from BotFather. |
| `TELEGRAM_SECRET` | No | Secret used to validate the `x-telegram-bot-api-secret-token` webhook header. |
| `TARGET_URL` | No | Override for the primary Circle K source URL. Defaults to the built-in Circle K page. |
| `ENABLED_PROVIDERS` | No | Comma-separated provider list such as `circlek,neste,virsi,viada`. Defaults to all supported providers. |
| `CREDIT_MESSAGE` | No | Custom footer/support/credit text appended to price, status, and help messages. Set to an empty string to disable it entirely. |
| `S3_BUCKET_NAME` | No | S3 bucket name used for price snapshots. When unset the diff/change feature is disabled and the bot falls back to live scraping only. |
| `S3_CURRENT_KEY` | No | S3 key for the current price snapshot. Defaults to `prices/current.json`. |
| `S3_PREVIOUS_KEY` | No | S3 key for the previous price snapshot used for diff computation. Defaults to `prices/previous.json`. |

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
S3_BUCKET_NAME=my-fuel-bot-snapshots
```

## Deploy your own bot

1. Create a Telegram bot with `@BotFather` and copy the token.
2. Deploy **the Release .zip** to AWS Lambda. You can also create a release .zip locally by running `./scripts/build_lambda_zip.ps1` from repository root.
3. Configure the environment variables listed above.
4. Expose the Lambda through a public HTTPS endpoint.
5. Register the webhook with Telegram.
6. *(Optional but recommended)* Create an S3 bucket and an EventBridge rule that invokes the same Lambda function on a schedule (e.g. every 30 minutes) to keep snapshots fresh and enable price-change indicators.

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

- `/fuel`: full comparison for all available fuels, with ▲/▼ price-change indicators.
- `/fuel <type>` and `/price <type>`: cheapest provider for one fuel.
- `/best`: cheapest provider for each fuel type.
- `/refresh`: forces a refresh with cooldown protection.
- `/mode`: per-chat compact/full rendering preference.
- `/fav`: per-chat favorite fuels for faster menu access.
- `/circlek`, `/neste`, `/virsi`, `/viada`: provider-specific price views when enabled.
- All price views include a `📅 Mainījās:` timestamp indicating when prices last changed (requires S3 snapshot setup).
- `/ping` and `/status` are internal diagnostics commands and are disabled in public deployments by default.

Full command and button behaviour is documented in [TELEGRAM_COMMANDS.md](TELEGRAM_COMMANDS.md).

## Notes for framework users

- `ENABLED_PROVIDERS` controls both scraping and which provider commands are available.
- `CREDIT_MESSAGE` is deployment-specific, so forks can add their own support link or attribution without editing Python code.
- Setting `CREDIT_MESSAGE` to an empty string removes the footer credit from formatted responses.
- Status, fuel, best-price, and provider-specific messages all use the same configured credit value.
- `S3_BUCKET_NAME` is optional. Without it the bot works fully but shows no ▲/▼ price-change indicators and no `📅 Mainījās:` timestamps.
- The Lambda execution role must have bucket-level `s3:ListBucket` and object-level `s3:GetObject`/`s3:PutObject` on the configured S3 bucket/prefix when `S3_BUCKET_NAME` is set.

Example IAM policy (replace bucket name/prefix as needed):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FuelSnapshotsBucketList",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::telegram-bot-s3-snapshots",
      "Condition": {
        "StringLike": {
          "s3:prefix": [
            "prices/*"
          ]
        }
      }
    },
    {
      "Sid": "FuelSnapshotsObjectsRW",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::telegram-bot-s3-snapshots/prices/*"
    }
  ]
}
```

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

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from telegram import Update
from telegram.error import InvalidToken
from fuel_price_telegram_bot.bot import create_application
from fuel_price_telegram_bot.config import Config

logger = logging.getLogger(__name__)

_app = None
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)


async def _get_app():
    global _app
    if _app is not None:
        return _app
    app = create_application(Config())
    await app.initialize()
    _app = app
    return _app


async def _handle_update(update_data: dict):
    app = await _get_app()
    update = Update.de_json(update_data, app.bot)
    await app.process_update(update)


def _run_scheduled_snapshot() -> None:
    """Scrape prices and maintain current/previous S3 snapshots for price-diff display."""
    from fuel_price_telegram_bot.scraper import scrape_fuel_prices
    from fuel_price_telegram_bot.snapshot import read_snapshot, write_snapshot, prices_changed

    try:
        config = Config()
    except ValueError as exc:
        logger.error('Config error in scheduled snapshot: %s', exc)
        return

    bucket = config.S3_BUCKET_NAME
    if not bucket:
        logger.warning('S3_BUCKET_NAME not set; skipping scheduled snapshot')
        return

    fresh_prices = scrape_fuel_prices(config.TARGET_URL, enabled_sources=config.ENABLED_PROVIDERS)
    if not fresh_prices:
        logger.error('Scheduled scrape returned no data; skipping snapshot write')
        return

    now = datetime.now(timezone.utc).isoformat()
    current_snapshot = read_snapshot(bucket, config.S3_CURRENT_KEY)
    current_prices = current_snapshot.get('prices', []) if current_snapshot else []

    if prices_changed(current_prices, fresh_prices):
        # Prices changed: rotate current → previous, write new current.
        if current_snapshot:
            write_snapshot(bucket, config.S3_PREVIOUS_KEY, current_snapshot)
        changed_at = now
    else:
        # Prices unchanged: preserve the original change timestamp.
        changed_at = (current_snapshot or {}).get('changed_at', now)

    write_snapshot(bucket, config.S3_CURRENT_KEY, {
        'prices': fresh_prices,
        'scraped_at': now,
        'changed_at': changed_at,
    })
    logger.info('Scheduled snapshot written to s3://%s/%s', bucket, config.S3_CURRENT_KEY)


def lambda_handler(event, context):
    # EventBridge scheduled invocation (e.g. hourly price snapshot).
    if event.get('source') == 'aws.events':
        _run_scheduled_snapshot()
        return {'statusCode': 200, 'body': 'OK: scheduled snapshot complete'}

    # Allow Lambda console test invocations that don't send Telegram webhook payloads.
    if "body" not in event:
        return {"statusCode": 200, "body": "OK: no webhook payload"}

    secret = os.environ.get("TELEGRAM_SECRET")
    if secret:
        token = event.get("headers", {}).get("x-telegram-bot-api-secret-token")
        if token != secret:
            return {"statusCode": 403, "body": "Forbidden"}

    try:
        body = json.loads(event["body"])
    except json.JSONDecodeError as err:
        logger.error("JSON decode failed: %s", err)
        return {"statusCode": 400, "body": "Bad Request: invalid JSON"}

    if not body:
        return {"statusCode": 400, "body": "Bad Request: empty body"}

    try:
        _loop.run_until_complete(_handle_update(body))
    except InvalidToken:
        logger.exception("Invalid TELEGRAM_TOKEN")
        return {"statusCode": 500, "body": "Configuration error: invalid TELEGRAM_TOKEN"}
    except ValueError as err:
        logger.exception("Configuration error")
        return {"statusCode": 500, "body": f"Configuration error: {err}"}
    except Exception:
        logger.exception("Error processing update")
        return {"statusCode": 500, "body": "Internal Server Error"}

    return {"statusCode": 200, "body": "OK"}
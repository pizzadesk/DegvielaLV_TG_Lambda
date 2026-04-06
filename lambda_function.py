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
_config = None
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


async def _get_app():
    global _app
    if _app is not None:
        return _app
    app = create_application(_get_config())
    await app.initialize()
    _app = app
    return _app


async def _handle_update(update_data: dict):
    app = await _get_app()
    update = Update.de_json(update_data, app.bot)
    await app.process_update(update)


def _is_scheduled_invocation(event: dict) -> bool:
    """Detect EventBridge Rule/Scheduler invocations and explicit scheduled test payloads."""
    source = event.get('source')
    if source in {'aws.events', 'aws.scheduler'}:
        return True

    if event.get('detail-type') == 'Scheduled Event':
        return True

    resources = event.get('resources')
    if isinstance(resources, list) and any(':rule/' in str(resource) for resource in resources):
        return True

    # Allows simple manual tests like {"scheduled": true}.
    if event.get('scheduled') is True:
        return True

    return False


def _run_scheduled_snapshot() -> dict:
    """Scrape prices and maintain current/previous S3 snapshots for price-diff display."""
    from fuel_price_telegram_bot.scraper import scrape_fuel_prices
    from fuel_price_telegram_bot.snapshot import read_snapshot, write_snapshot, prices_changed

    try:
        config = _get_config()
    except ValueError as exc:
        logger.error('Config error in scheduled snapshot: %s', exc)
        return {'ok': False, 'reason': f'config_error: {exc}'}

    bucket = config.S3_BUCKET_NAME
    if not bucket:
        logger.warning('S3_BUCKET_NAME not set; skipping scheduled snapshot')
        return {'ok': False, 'reason': 'missing_s3_bucket'}

    fresh_prices = scrape_fuel_prices(config.TARGET_URL, enabled_sources=config.ENABLED_PROVIDERS)
    if not fresh_prices:
        logger.error('Scheduled scrape returned no data; skipping snapshot write')
        return {'ok': False, 'reason': 'empty_scrape'}

    now = datetime.now(timezone.utc).isoformat()
    current_snapshot = read_snapshot(bucket, config.S3_CURRENT_KEY)
    current_prices = current_snapshot.get('prices', []) if current_snapshot else []
    rotated_previous = False

    if prices_changed(current_prices, fresh_prices):
        # Prices changed: rotate current → previous, write new current.
        if current_snapshot:
            rotated_previous = write_snapshot(bucket, config.S3_PREVIOUS_KEY, current_snapshot)
        changed_at = now
    else:
        # Prices unchanged: preserve the original change timestamp.
        changed_at = (current_snapshot or {}).get('changed_at', now)

    wrote_current = write_snapshot(bucket, config.S3_CURRENT_KEY, {
        'prices': fresh_prices,
        'scraped_at': now,
        'changed_at': changed_at,
    })

    if not wrote_current:
        logger.error('Scheduled snapshot failed to write current snapshot to s3://%s/%s', bucket, config.S3_CURRENT_KEY)
        return {
            'ok': False,
            'reason': 'write_current_failed',
            'bucket': bucket,
            'current_key': config.S3_CURRENT_KEY,
        }

    logger.info(
        'Scheduled snapshot written to s3://%s/%s (rotated_previous=%s, price_rows=%d)',
        bucket,
        config.S3_CURRENT_KEY,
        rotated_previous,
        len(fresh_prices),
    )
    return {
        'ok': True,
        'bucket': bucket,
        'current_key': config.S3_CURRENT_KEY,
        'rotated_previous': rotated_previous,
        'price_rows': len(fresh_prices),
    }


def lambda_handler(event, context):
    # EventBridge scheduled invocation (e.g. hourly price snapshot).
    if isinstance(event, dict) and _is_scheduled_invocation(event):
        logger.info('Detected scheduled invocation (source=%s, detail-type=%s)', event.get('source'), event.get('detail-type'))
        result = _run_scheduled_snapshot()
        code = 200 if result.get('ok') else 500
        return {'statusCode': code, 'body': json.dumps(result)}

    # Some EventBridge Scheduler targets may send empty payloads; treat no-body events
    # as scheduled snapshot attempts to avoid silent no-op runs.
    if "body" not in event:
        logger.info(
            'No webhook body present; running scheduled snapshot fallback (keys=%s)',
            sorted(event.keys()) if isinstance(event, dict) else type(event).__name__,
        )
        result = _run_scheduled_snapshot()
        code = 200 if result.get('ok') else 500
        result['fallback_no_body_event'] = True
        return {'statusCode': code, 'body': json.dumps(result)}

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
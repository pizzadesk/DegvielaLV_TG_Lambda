import asyncio
import json
import logging
import os

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


def lambda_handler(event, context):
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
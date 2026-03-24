import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from .config import Config
from .scraper import get_fuel_prices, get_scrape_status, refresh_fuel_prices
from .formatter import (
    format_best_prices,
    format_help_text,
    format_lowest_price,
    format_message,
    format_provider_prices,
    format_start_text,
    format_status,
)

logger = logging.getLogger(__name__)


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data['config']


def _get_data(context: ContextTypes.DEFAULT_TYPE, force_refresh: bool = False) -> list[dict]:
    config = _get_config(context)
    return get_fuel_prices(
        config.TARGET_URL,
        force_refresh=force_refresh,
        enabled_sources=config.ENABLED_PROVIDERS,
    )


async def _reply_html(update: Update, text: str) -> None:
    await update.message.reply_html(text, disable_web_page_preview=True)


async def _provider_command(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str) -> None:
    config = _get_config(context)
    if provider not in config.ENABLED_PROVIDERS:
        await update.message.reply_text(f'{provider} is currently disabled in this deployment.')
        return

    text = format_provider_prices(_get_data(context), provider)
    await _reply_html(update, text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await update.message.reply_text(format_start_text(config.ENABLED_PROVIDERS))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await update.message.reply_text(format_help_text(config.ENABLED_PROVIDERS))


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


async def fuel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    config = _get_config(context)
    data = _get_data(context)

    if args:
        fuel_query = args[0]
        text = format_lowest_price(data, fuel_query, config.ENABLED_PROVIDERS)
    else:
        text = format_message(data, config.ENABLED_PROVIDERS)

    await _reply_html(update, text)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text('Usage: /price <95|95+|98|diesel|diesel+|xtl|gas|lpg|cng|e85>')
        return

    config = _get_config(context)
    fuel_query = args[0]
    text = format_lowest_price(_get_data(context), fuel_query, config.ENABLED_PROVIDERS)
    await _reply_html(update, text)


async def best(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    text = format_best_prices(_get_data(context), config.ENABLED_PROVIDERS)
    await _reply_html(update, text)


async def circlek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _provider_command(update, context, 'circlek')


async def neste(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _provider_command(update, context, 'neste')


async def virsi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _provider_command(update, context, 'virsi')


async def viada(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _provider_command(update, context, 'viada')


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    text = format_status(get_scrape_status(config.ENABLED_PROVIDERS))
    await _reply_html(update, text)


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    refresh_result = refresh_fuel_prices(
        config.TARGET_URL,
        enabled_sources=config.ENABLED_PROVIDERS,
    )
    data = refresh_result.data

    if not refresh_result.refreshed:
        if data:
            text = format_message(data, config.ENABLED_PROVIDERS)
            await _reply_html(update, '⚠️ Could not refresh fuel prices; showing cached data.\n\n' + text)
            return
        await update.message.reply_text('⚠️ Could not refresh fuel prices; please try again.')
        return

    text = format_message(data, config.ENABLED_PROVIDERS)
    await _reply_html(update, '✅ Cache updated. ' + text)


def create_application(config: Config | None = None) -> Application:
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    cfg = config or Config()

    app = Application.builder().token(cfg.TELEGRAM_TOKEN).build()
    app.bot_data['config'] = cfg

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('ping', ping))
    app.add_handler(CommandHandler('fuel', fuel))
    app.add_handler(CommandHandler('price', price))
    app.add_handler(CommandHandler('best', best))
    app.add_handler(CommandHandler('circlek', circlek))
    app.add_handler(CommandHandler('neste', neste))
    app.add_handler(CommandHandler('virsi', virsi))
    app.add_handler(CommandHandler('viada', viada))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('refresh', refresh))

    return app


def main() -> None:
    app = create_application()
    logger.info('Fuel price bot started (polling)')
    app.run_polling()


if __name__ == '__main__':
    main()

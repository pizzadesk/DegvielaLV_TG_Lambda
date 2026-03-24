import logging
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from .config import Config
from .scraper import get_fuel_prices, get_scrape_status, refresh_fuel_prices
from .formatter import (
    format_compact_message,
    format_best_prices,
    format_help_text,
    format_lowest_price,
    format_message,
    format_provider_prices,
    format_start_text,
    format_status,
    get_brand_name,
)

logger = logging.getLogger(__name__)
_CB_PREFIX = 'act:'


def _fuel_to_key(fuel: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', fuel.lower())


def _available_fuels(data: list[dict]) -> list[str]:
    fuels = [item.get('fuel') for item in data if item.get('fuel')]
    return [fuel for fuel in fuels if isinstance(fuel, str)]


def _find_fuel_by_key(data: list[dict], fuel_key: str) -> str | None:
    for fuel in _available_fuels(data):
        if _fuel_to_key(fuel) == fuel_key:
            return fuel
    return None


def _is_compact_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in {'group', 'supergroup', 'channel'})


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data['config']


def _get_data(context: ContextTypes.DEFAULT_TYPE, force_refresh: bool = False) -> list[dict]:
    config = _get_config(context)
    return get_fuel_prices(
        config.TARGET_URL,
        force_refresh=force_refresh,
        enabled_sources=config.ENABLED_PROVIDERS,
    )


def _get_reply_message(update: Update):
    message = update.effective_message
    if message is None:
        logger.warning('Skipping reply for update without effective_message: %s', update.update_id)
    return message


def _shortcuts_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('⛽ Fuel Menu', callback_data=f'{_CB_PREFIX}fuelmenu'),
                InlineKeyboardButton('🏁 Best', callback_data=f'{_CB_PREFIX}best'),
            ],
            [
                InlineKeyboardButton('95', callback_data=f'{_CB_PREFIX}fuelbest:95'),
                InlineKeyboardButton('Diesel', callback_data=f'{_CB_PREFIX}fuelbest:diesel'),
            ],
            [
                InlineKeyboardButton('🔄 Refresh', callback_data=f'{_CB_PREFIX}refresh'),
                InlineKeyboardButton('📊 Status', callback_data=f'{_CB_PREFIX}status'),
            ],
        ]
    )


def _fuel_menu_markup(data: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for fuel in _available_fuels(data):
        current.append(InlineKeyboardButton(fuel, callback_data=f'{_CB_PREFIX}fuelsel:{_fuel_to_key(fuel)}'))
        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([InlineKeyboardButton('⬅️ Back', callback_data=f'{_CB_PREFIX}home')])
    return InlineKeyboardMarkup(rows)


def _fuel_actions_markup(fuel_key: str, enabled_providers: tuple[str, ...] | list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton('🏁 Best for this fuel', callback_data=f'{_CB_PREFIX}fuelbest:{fuel_key}'),
            InlineKeyboardButton('⛽ All providers', callback_data=f'{_CB_PREFIX}fuelall:{fuel_key}'),
        ]
    ]

    current: list[InlineKeyboardButton] = []
    for provider in enabled_providers:
        current.append(
            InlineKeyboardButton(
                get_brand_name(provider),
                callback_data=f'{_CB_PREFIX}fuelprov:{provider}:{fuel_key}',
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([
        InlineKeyboardButton('🔙 Fuel list', callback_data=f'{_CB_PREFIX}fuelmenu'),
        InlineKeyboardButton('🏠 Home', callback_data=f'{_CB_PREFIX}home'),
    ])

    return InlineKeyboardMarkup(rows)


async def _edit_callback_html(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    query = update.callback_query
    if query is None:
        await _reply_html(update, text, shortcuts=True)
        return
    await query.edit_message_text(text=text, parse_mode='HTML', disable_web_page_preview=True, reply_markup=reply_markup)


def _extract_fuel_row(data: list[dict], fuel: str) -> dict | None:
    return next((item for item in data if item.get('fuel') == fuel), None)


async def _reply_text(update: Update, text: str, shortcuts: bool = False) -> None:
    message = _get_reply_message(update)
    if message is None:
        return
    kwargs = {'reply_markup': _shortcuts_markup()} if shortcuts else {}
    await message.reply_text(text, **kwargs)


async def _reply_html(update: Update, text: str, shortcuts: bool = False) -> None:
    message = _get_reply_message(update)
    if message is None:
        return
    kwargs = {'reply_markup': _shortcuts_markup()} if shortcuts else {}
    await message.reply_html(text, disable_web_page_preview=True, **kwargs)


async def _handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error('Telegram handler error', exc_info=context.error)

    if not isinstance(update, Update):
        return

    message = update.effective_message
    if message is None:
        return

    try:
        await message.reply_text('⚠️ An internal error occurred. Please try again later.')
    except Exception:
        logger.exception('Failed to send error notification')


async def _provider_command(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str) -> None:
    config = _get_config(context)
    if provider not in config.ENABLED_PROVIDERS:
        await _reply_text(update, f'{provider} is currently disabled in this deployment.')
        return

    text = format_provider_prices(_get_data(context), provider)
    await _reply_html(update, text, shortcuts=True)


def _format_fuel_view(update: Update, data: list[dict], enabled_providers: tuple[str, ...] | list[str]) -> str:
    if _is_compact_chat(update):
        return format_compact_message(data, enabled_providers)
    return format_message(data, enabled_providers)


async def _send_fuel_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    config = _get_config(context)
    data = _get_data(context)

    if args:
        text = format_lowest_price(data, args[0], config.ENABLED_PROVIDERS)
    else:
        text = _format_fuel_view(update, data, config.ENABLED_PROVIDERS)

    await _reply_html(update, text, shortcuts=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_start_text(config.ENABLED_PROVIDERS), shortcuts=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_help_text(config.ENABLED_PROVIDERS), shortcuts=True)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_text(update, 'pong')


async def fuel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_fuel_view(update, context)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await _reply_text(update, 'Usage: /price <95|95+|98|diesel|diesel+|xtl|gas|lpg|cng|e85>', shortcuts=True)
        return

    config = _get_config(context)
    fuel_query = args[0]
    text = format_lowest_price(_get_data(context), fuel_query, config.ENABLED_PROVIDERS)
    await _reply_html(update, text, shortcuts=True)


async def best(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    text = format_best_prices(_get_data(context), config.ENABLED_PROVIDERS)
    await _reply_html(update, text, shortcuts=True)


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
    await _reply_html(update, text, shortcuts=True)


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    refresh_result = refresh_fuel_prices(
        config.TARGET_URL,
        enabled_sources=config.ENABLED_PROVIDERS,
    )
    data = refresh_result.data

    if not refresh_result.refreshed:
        if data:
            text = _format_fuel_view(update, data, config.ENABLED_PROVIDERS)
            await _reply_html(update, '⚠️ Could not refresh fuel prices; showing cached data.\n\n' + text, shortcuts=True)
            return
        await _reply_text(update, '⚠️ Could not refresh fuel prices; please try again.', shortcuts=True)
        return

    text = _format_fuel_view(update, data, config.ENABLED_PROVIDERS)
    await _reply_html(update, '✅ Cache updated. ' + text, shortcuts=True)


async def shortcuts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return

    await query.answer()
    action = query.data
    config = _get_config(context)
    data = _get_data(context)

    if action == f'{_CB_PREFIX}home':
        await _edit_callback_html(update, 'Choose an action:', reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}fuelmenu':
        if not data:
            await _edit_callback_html(
                update,
                '⛽ Fuel data is currently unavailable. Try Refresh and try again.',
                reply_markup=_shortcuts_markup(),
            )
            return
        await _edit_callback_html(
            update,
            '⛽ <b>Select Fuel Type</b>\n\nChoose one fuel to open detailed actions.',
            reply_markup=_fuel_menu_markup(data),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelsel:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(
                update,
                '❌ Fuel type is no longer available in current data. Open Fuel Menu again.',
                reply_markup=_shortcuts_markup(),
            )
            return

        await _edit_callback_html(
            update,
            f'🛢️ <b>{fuel}</b>\n\nChoose how to view this fuel.',
            reply_markup=_fuel_actions_markup(fuel_key, config.ENABLED_PROVIDERS),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelbest:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Fuel type is no longer available.', reply_markup=_shortcuts_markup())
            return

        text = format_lowest_price(data, fuel, config.ENABLED_PROVIDERS)
        await _edit_callback_html(update, text, reply_markup=_fuel_actions_markup(fuel_key, config.ENABLED_PROVIDERS))
        return

    if action.startswith(f'{_CB_PREFIX}fuelall:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Fuel type is no longer available.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ Fuel type is no longer available.', reply_markup=_shortcuts_markup())
            return

        text = format_message([row], config.ENABLED_PROVIDERS)
        await _edit_callback_html(update, text, reply_markup=_fuel_actions_markup(fuel_key, config.ENABLED_PROVIDERS))
        return

    if action.startswith(f'{_CB_PREFIX}fuelprov:'):
        parts = action.split(':', 3)
        if len(parts) != 4:
            await _edit_callback_html(update, '❌ Unsupported action.', reply_markup=_shortcuts_markup())
            return

        provider = parts[2]
        fuel_key = parts[3]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Fuel type is no longer available.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ Fuel type is no longer available.', reply_markup=_shortcuts_markup())
            return

        text = format_provider_prices([row], provider)
        await _edit_callback_html(update, text, reply_markup=_fuel_actions_markup(fuel_key, config.ENABLED_PROVIDERS))
        return

    if action == f'{_CB_PREFIX}fuel':
        await _edit_callback_html(update, _format_fuel_view(update, data, config.ENABLED_PROVIDERS), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}best':
        await _edit_callback_html(update, format_best_prices(_get_data(context), config.ENABLED_PROVIDERS), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}status':
        await _edit_callback_html(update, format_status(get_scrape_status(config.ENABLED_PROVIDERS)), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}refresh':
        await refresh(update, context)
        return

    if action == f'{_CB_PREFIX}price:95':
        await _edit_callback_html(update, format_lowest_price(_get_data(context), '95', config.ENABLED_PROVIDERS), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}price:diesel':
        await _edit_callback_html(update, format_lowest_price(_get_data(context), 'diesel', config.ENABLED_PROVIDERS), reply_markup=_shortcuts_markup())
        return


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
    app.add_handler(CallbackQueryHandler(shortcuts_callback, pattern=f'^{_CB_PREFIX}'))
    app.add_error_handler(_handle_error)

    return app


def main() -> None:
    app = create_application()
    logger.info('Fuel price bot started (polling)')
    app.run_polling()


if __name__ == '__main__':
    main()

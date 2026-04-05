import logging
import re
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
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
    normalize_fuel_query,
)

logger = logging.getLogger(__name__)
_CB_PREFIX = 'act:'
_CHAT_PREFS_KEY = 'chat_preferences'
_REFRESH_BY_CHAT_KEY = 'refresh_last_by_chat'
_REFRESH_GLOBAL_KEY = 'refresh_last_global'
_MODE_COMPACT = 'compact'
_MODE_FULL = 'full'
_REFRESH_CHAT_COOLDOWN_SECONDS = 45
_REFRESH_GLOBAL_COOLDOWN_SECONDS = 20
_FUEL_ORDER = {
    '95': 0,
    '95 Premium': 1,
    '98': 2,
    'Diesel': 3,
    'Diesel Premium': 4,
    'XTL': 5,
    'LPG': 6,
    'CNG': 7,
    'E85': 8,
}


def _fuel_to_key(fuel: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', fuel.lower())


def _available_fuels(data: list[dict]) -> list[str]:
    unique: dict[str, None] = {}
    for item in data:
        fuel = item.get('fuel')
        if isinstance(fuel, str):
            unique[fuel] = None
    return sorted(unique.keys(), key=lambda fuel: (_FUEL_ORDER.get(fuel, 999), fuel))


def _find_fuel_by_key(data: list[dict], fuel_key: str) -> str | None:
    for fuel in _available_fuels(data):
        if _fuel_to_key(fuel) == fuel_key:
            return fuel
    return None


def _is_compact_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in {'group', 'supergroup', 'channel'})


def _get_chat_preferences(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.bot_data.setdefault(_CHAT_PREFS_KEY, {})


def _get_chat_id(update: Update) -> int | None:
    chat = update.effective_chat
    if chat is None:
        return None
    return chat.id


def _get_chat_preference(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None) -> dict:
    if chat_id is None:
        return {}
    prefs = _get_chat_preferences(context)
    return prefs.setdefault(chat_id, {})


def _get_chat_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    chat_id = _get_chat_id(update)
    pref = _get_chat_preference(context, chat_id)
    mode = pref.get('mode')
    if mode in {_MODE_COMPACT, _MODE_FULL}:
        return mode
    return _MODE_COMPACT if _is_compact_chat(update) else _MODE_FULL


def _is_compact_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return _get_chat_mode(update, context) == _MODE_COMPACT


def _get_favorites(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None) -> list[str]:
    pref = _get_chat_preference(context, chat_id)
    favorites = pref.get('favorites', [])
    if not isinstance(favorites, list):
        return []
    return [item for item in favorites if isinstance(item, str)]


def _set_favorites(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, favorites: list[str]) -> None:
    pref = _get_chat_preference(context, chat_id)
    pref['favorites'] = favorites


def _resolve_fuel_name(data: list[dict], fuel_input: str) -> str | None:
    if not fuel_input:
        return None

    normalized = normalize_fuel_query(fuel_input)
    if normalized:
        return normalized

    needle = fuel_input.strip().lower()
    for fuel in _available_fuels(data):
        if fuel.lower() == needle:
            return fuel
    return None


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.bot_data['config']


def _get_credit_message(context: ContextTypes.DEFAULT_TYPE) -> str:
    return _get_config(context).CREDIT_MESSAGE


def _get_diff_context(
    config: Config,
    live_data: list[dict],
) -> 'tuple[dict | None, object]':
    """Return (diffs, changed_at) from S3 snapshots, or (None, None) if unavailable."""
    if not config.S3_BUCKET_NAME:
        return None, None
    try:
        from .snapshot import get_current_snapshot, get_previous_snapshot, compute_diffs
        from datetime import datetime
        cur = get_current_snapshot(config.S3_BUCKET_NAME, config.S3_CURRENT_KEY)
        prev = get_previous_snapshot(config.S3_BUCKET_NAME, config.S3_PREVIOUS_KEY)
        if cur is None or prev is None:
            return None, None
        diffs = compute_diffs(live_data, prev.get('prices', []))
        changed_at_str = cur.get('changed_at')
        changed_at = datetime.fromisoformat(changed_at_str) if changed_at_str else None
        return diffs, changed_at
    except Exception:
        logger.exception('Failed to load snapshot diff context')
        return None, None


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
                InlineKeyboardButton('⛽ Choose Fuel', callback_data=f'{_CB_PREFIX}fuelmenu'),
                InlineKeyboardButton('📉 Cheapest', callback_data=f'{_CB_PREFIX}best'),
            ],
            [
                InlineKeyboardButton('95', callback_data=f'{_CB_PREFIX}fuelbest:95'),
                InlineKeyboardButton('Diesel', callback_data=f'{_CB_PREFIX}fuelbest:diesel'),
            ],
            [
                InlineKeyboardButton('❓ Help', callback_data=f'{_CB_PREFIX}help'),
                InlineKeyboardButton('🔄 Update Prices', callback_data=f'{_CB_PREFIX}refresh'),
                InlineKeyboardButton('📊 Bot Status', callback_data=f'{_CB_PREFIX}status'),
            ],
        ]
    )


def _fuel_menu_markup(data: list[dict], favorites: list[str] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    favorites = favorites or []
    available = _available_fuels(data)

    favorite_buttons = [
        InlineKeyboardButton(f'⭐ {fuel}', callback_data=f'{_CB_PREFIX}fuelsel:{_fuel_to_key(fuel)}')
        for fuel in favorites
        if fuel in available
    ]
    if favorite_buttons:
        rows.append(favorite_buttons[:2])

    current: list[InlineKeyboardButton] = []
    for fuel in available:
        current.append(InlineKeyboardButton(fuel, callback_data=f'{_CB_PREFIX}fuelsel:{_fuel_to_key(fuel)}'))
        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([InlineKeyboardButton('⬅️ Back to menu', callback_data=f'{_CB_PREFIX}home')])
    return InlineKeyboardMarkup(rows)


def _fuel_actions_markup(
    fuel_key: str,
    enabled_providers: tuple[str, ...] | list[str],
    is_favorite: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton('📉 Cheapest', callback_data=f'{_CB_PREFIX}fuelbest:{fuel_key}'),
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
        InlineKeyboardButton(
            '⭐ Remove from favorites' if is_favorite else '⭐ Add to favorites',
            callback_data=f'{_CB_PREFIX}favtoggle:{fuel_key}',
        )
    ])

    rows.append([
        InlineKeyboardButton('🔙 Fuel list', callback_data=f'{_CB_PREFIX}fuelmenu'),
        InlineKeyboardButton('🏠 Main menu', callback_data=f'{_CB_PREFIX}home'),
    ])

    return InlineKeyboardMarkup(rows)


async def _edit_callback_html(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    query = update.callback_query
    if query is None:
        await _reply_html(update, text, shortcuts=True)
        return
    try:
        await query.edit_message_text(text=text, parse_mode='HTML', disable_web_page_preview=True, reply_markup=reply_markup)
    except BadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            raise


async def _edit_callback_text(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    query = update.callback_query
    if query is None:
        await _reply_text(update, text, shortcuts=True)
        return
    try:
        await query.edit_message_text(text=text, disable_web_page_preview=True, reply_markup=reply_markup)
    except BadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            raise


def _extract_fuel_row(data: list[dict], fuel: str) -> dict | None:
    return next((item for item in data if item.get('fuel') == fuel), None)


def _is_favorite(context: ContextTypes.DEFAULT_TYPE, update: Update, fuel: str) -> bool:
    return fuel in _get_favorites(context, _get_chat_id(update))


def _set_mode(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, mode: str | None) -> None:
    pref = _get_chat_preference(context, chat_id)
    if mode is None:
        pref.pop('mode', None)
    else:
        pref['mode'] = mode


def _get_refresh_tracker_by_chat(context: ContextTypes.DEFAULT_TYPE) -> dict[int, datetime]:
    return context.bot_data.setdefault(_REFRESH_BY_CHAT_KEY, {})


def _get_refresh_tracker_global(context: ContextTypes.DEFAULT_TYPE) -> datetime | None:
    value = context.bot_data.get(_REFRESH_GLOBAL_KEY)
    return value if isinstance(value, datetime) else None


def _set_refresh_tracker(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, now: datetime) -> None:
    if chat_id is not None:
        _get_refresh_tracker_by_chat(context)[chat_id] = now
    context.bot_data[_REFRESH_GLOBAL_KEY] = now


def _remaining_seconds(last_run: datetime | None, cooldown: int, now: datetime) -> int:
    if last_run is None:
        return 0

    remaining = int((last_run + timedelta(seconds=cooldown) - now).total_seconds())
    return remaining if remaining > 0 else 0


def _refresh_cooldown_message(chat_remaining: int, global_remaining: int) -> str | None:
    if chat_remaining <= 0 and global_remaining <= 0:
        return None

    if chat_remaining > 0 and global_remaining > 0:
        wait_seconds = max(chat_remaining, global_remaining)
        return f'⏱️ Please wait about {wait_seconds}s, then tap Update Prices again.'

    if chat_remaining > 0:
        return f'⏱️ This chat updated recently. Please wait about {chat_remaining}s.'

    return f'⏱️ Update is temporarily busy. Please wait about {global_remaining}s.'


async def _run_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool = False) -> None:
    now = datetime.utcnow()
    chat_id = _get_chat_id(update)
    by_chat = _get_refresh_tracker_by_chat(context)
    chat_remaining = _remaining_seconds(by_chat.get(chat_id), _REFRESH_CHAT_COOLDOWN_SECONDS, now)
    global_remaining = _remaining_seconds(_get_refresh_tracker_global(context), _REFRESH_GLOBAL_COOLDOWN_SECONDS, now)
    cooldown_message = _refresh_cooldown_message(chat_remaining, global_remaining)
    if cooldown_message:
        if from_callback:
            await _edit_callback_html(update, cooldown_message, reply_markup=_shortcuts_markup())
        else:
            await _reply_text(update, cooldown_message, shortcuts=True)
        return

    _set_refresh_tracker(context, chat_id, now)

    config = _get_config(context)
    refresh_result = refresh_fuel_prices(
        config.TARGET_URL,
        enabled_sources=config.ENABLED_PROVIDERS,
    )
    data = refresh_result.data
    diffs, changed_at = _get_diff_context(config, data)

    if not refresh_result.refreshed:
        if data:
            text = _format_fuel_view(update, context, data, config.ENABLED_PROVIDERS, diffs=diffs, changed_at=changed_at)
            message = '⚠️ Could not update prices now. Showing saved data.\n\n' + text
            if from_callback:
                await _edit_callback_html(update, message, reply_markup=_shortcuts_markup())
            else:
                await _reply_html(update, message, shortcuts=True)
            return

        if from_callback:
            await _edit_callback_html(update, '⚠️ Could not update prices now. Please try again.', reply_markup=_shortcuts_markup())
        else:
            await _reply_text(update, '⚠️ Could not update prices now. Please try again.', shortcuts=True)
        return

    text = _format_fuel_view(update, context, data, config.ENABLED_PROVIDERS, diffs=diffs, changed_at=changed_at)
    message = '✅ Prices updated. ' + text
    if from_callback:
        await _edit_callback_html(update, message, reply_markup=_shortcuts_markup())
    else:
        await _reply_html(update, message, shortcuts=True)


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

    # Callback (inline button) errors: edit the existing message in-place.
    if update.callback_query is not None:
        try:
            await _edit_callback_html(
                update,
                '⚠️ Something went wrong. Tap <b>🔄 Update Prices</b> or try again.',
                reply_markup=_shortcuts_markup(),
            )
        except Exception:
            logger.exception('Failed to edit message for error notification')
        return

    # Command errors: send a reply with shortcuts attached.
    message = update.effective_message
    if message is None:
        return

    try:
        await message.reply_text(
            '⚠️ An internal error occurred. Please try again later.',
            reply_markup=_shortcuts_markup(),
        )
    except Exception:
        logger.exception('Failed to send error notification')


async def _provider_command(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str) -> None:
    config = _get_config(context)
    if provider not in config.ENABLED_PROVIDERS:
        await _reply_text(
            update,
            f'{get_brand_name(provider)} is not available right now. Please choose another provider.',
            shortcuts=True,
        )
        return

    data = _get_data(context)
    diffs, changed_at = _get_diff_context(config, data)
    text = format_provider_prices(data, provider, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    await _reply_html(update, text, shortcuts=True)


def _format_fuel_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: list[dict],
    enabled_providers: tuple[str, ...] | list[str],
    diffs: dict | None = None,
    changed_at=None,
) -> str:
    if _is_compact_mode(update, context):
        return format_compact_message(data, enabled_providers, _get_credit_message(context), diffs=diffs, changed_at=changed_at)
    return format_message(data, enabled_providers, _get_credit_message(context), diffs=diffs, changed_at=changed_at)


async def _send_fuel_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    config = _get_config(context)
    data = _get_data(context)
    diffs, changed_at = _get_diff_context(config, data)

    if args:
        text = format_lowest_price(data, args[0], config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    else:
        text = _format_fuel_view(update, context, data, config.ENABLED_PROVIDERS, diffs=diffs, changed_at=changed_at)

    await _reply_html(update, text, shortcuts=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_start_text(config.ENABLED_PROVIDERS), shortcuts=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_help_text(config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE), shortcuts=True)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_text(update, 'pong ✅ Bot is online.', shortcuts=True)


async def fuel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_fuel_view(update, context)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await _reply_text(update, 'Please add a fuel type. Example: /price diesel', shortcuts=True)
        return

    config = _get_config(context)
    fuel_query = args[0]
    data = _get_data(context)
    diffs, changed_at = _get_diff_context(config, data)
    text = format_lowest_price(data, fuel_query, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    await _reply_html(update, text, shortcuts=True)


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    chat_id = _get_chat_id(update)
    current = _get_chat_mode(update, context)

    if not args:
        await _reply_text(
            update,
            f'Current view mode: {current}. Use: /mode <compact|full|auto>',
            shortcuts=True,
        )
        return

    selected = args[0].strip().lower()
    if selected == 'auto':
        _set_mode(context, chat_id, None)
        effective = _get_chat_mode(update, context)
        await _reply_text(update, f'View mode set to auto (currently {effective}).', shortcuts=True)
        return

    if selected not in {_MODE_COMPACT, _MODE_FULL}:
        await _reply_text(update, 'Use: /mode <compact|full|auto>', shortcuts=True)
        return

    _set_mode(context, chat_id, selected)
    await _reply_text(update, f'View mode set to {selected}.', shortcuts=True)


async def favorite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    chat_id = _get_chat_id(update)
    favorites = _get_favorites(context, chat_id)
    data = _get_data(context)

    if not args or args[0].lower() == 'list':
        if not favorites:
            await _reply_text(update, 'No favorites yet. Use: /fav add <fuel>', shortcuts=True)
            return
        await _reply_text(update, 'Your favorites: ' + ', '.join(favorites), shortcuts=True)
        return

    action = args[0].lower()
    if action == 'clear':
        _set_favorites(context, chat_id, [])
        await _reply_text(update, 'Favorites cleared.', shortcuts=True)
        return

    if len(args) < 2:
        await _reply_text(update, 'Use: /fav <add|remove|list|clear> <fuel>', shortcuts=True)
        return

    fuel_name = _resolve_fuel_name(data, ' '.join(args[1:]))
    if not fuel_name:
        await _reply_text(update, 'Fuel not found. Open Choose Fuel to see available options.', shortcuts=True)
        return

    if action == 'add':
        if fuel_name not in favorites:
            favorites.append(fuel_name)
            _set_favorites(context, chat_id, favorites)
        await _reply_text(update, f'Added to favorites: {fuel_name}', shortcuts=True)
        return

    if action == 'remove':
        favorites = [fuel for fuel in favorites if fuel != fuel_name]
        _set_favorites(context, chat_id, favorites)
        await _reply_text(update, f'Removed from favorites: {fuel_name}', shortcuts=True)
        return

    await _reply_text(update, 'Use: /fav <add|remove|list|clear> <fuel>', shortcuts=True)


async def best(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    data = _get_data(context)
    diffs, changed_at = _get_diff_context(config, data)
    text = format_best_prices(data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
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
    text = format_status(get_scrape_status(config.ENABLED_PROVIDERS), config.CREDIT_MESSAGE)
    await _reply_html(update, text, shortcuts=True)


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_refresh(update, context, from_callback=False)


async def shortcuts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return

    await query.answer()
    action = query.data
    config = _get_config(context)
    data = _get_data(context)
    diffs, changed_at = _get_diff_context(config, data)

    if action == f'{_CB_PREFIX}home':
        await _edit_callback_html(update, 'Choose what you want to do:', reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}fuelmenu':
        if not data:
            await _edit_callback_html(
                update,
                '⛽ Fuel data is not available now. Tap Update Prices and try again.',
                reply_markup=_shortcuts_markup(),
            )
            return
        await _edit_callback_html(
            update,
            '⛽ <b>Select Fuel Type</b>\n\nChoose one fuel to see available actions.',
            reply_markup=_fuel_menu_markup(data, _get_favorites(context, _get_chat_id(update))),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelsel:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(
                update,
                '❌ This fuel is not available now. Open Choose Fuel and select another one.',
                reply_markup=_shortcuts_markup(),
            )
            return

        await _edit_callback_html(
            update,
            f'🛢️ <b>{fuel}</b>\n\nChoose how you want to view this fuel.',
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=_is_favorite(context, update, fuel),
            ),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelbest:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        text = format_lowest_price(data, fuel, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
        await _edit_callback_html(
            update,
            text,
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=_is_favorite(context, update, fuel),
            ),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelall:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        text = format_message([row], config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
        await _edit_callback_html(
            update,
            text,
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=_is_favorite(context, update, fuel),
            ),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelprov:'):
        parts = action.split(':', 3)
        if len(parts) != 4:
            await _edit_callback_html(update, '❌ This action is not available.', reply_markup=_shortcuts_markup())
            return

        provider = parts[2]
        fuel_key = parts[3]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        text = format_provider_prices([row], provider, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
        await _edit_callback_html(
            update,
            text,
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=_is_favorite(context, update, fuel),
            ),
        )
        return

    if action.startswith(f'{_CB_PREFIX}favtoggle:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key(data, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ This fuel is not available now.', reply_markup=_shortcuts_markup())
            return

        chat_id = _get_chat_id(update)
        favorites = _get_favorites(context, chat_id)
        if fuel in favorites:
            favorites = [item for item in favorites if item != fuel]
            note = f'Removed from favorites: {fuel}'
        else:
            favorites.append(fuel)
            note = f'Added to favorites: {fuel}'
        _set_favorites(context, chat_id, favorites)

        await _edit_callback_html(
            update,
            f'🛢️ <b>{fuel}</b>\n\n{note}\nChoose how you want to view this fuel.',
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=fuel in favorites,
            ),
        )
        return

    if action == f'{_CB_PREFIX}fuel':
        await _edit_callback_html(update, _format_fuel_view(update, context, data, config.ENABLED_PROVIDERS, diffs=diffs, changed_at=changed_at), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}best':
        await _edit_callback_html(update, format_best_prices(data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}help':
        await _edit_callback_text(update, format_help_text(config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}status':
        await _edit_callback_html(update, format_status(get_scrape_status(config.ENABLED_PROVIDERS), config.CREDIT_MESSAGE), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}refresh':
        await _run_refresh(update, context, from_callback=True)
        return

    if action == f'{_CB_PREFIX}price:95':
        await _edit_callback_html(update, format_lowest_price(data, '95', config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}price:diesel':
        await _edit_callback_html(update, format_lowest_price(data, 'diesel', config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at), reply_markup=_shortcuts_markup())
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
    app.add_handler(CommandHandler('mode', mode_command))
    app.add_handler(CommandHandler('fav', favorite_command))
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

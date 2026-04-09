import logging
import re
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from .config import Config
from .formatter import (
    format_best_prices,
    format_help_text,
    format_lowest_price,
    format_message,
    format_provider_prices,
    format_snapshot_status,
    format_start_text,
    get_brand_name,
    normalize_fuel_query,
)

logger = logging.getLogger(__name__)
_CB_PREFIX = 'act:'
_CHAT_PREFS_KEY = 'chat_preferences'
_REFRESH_BY_CHAT_KEY = 'refresh_last_by_chat'
_REFRESH_GLOBAL_KEY = 'refresh_last_global'
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


def _fuel_key_map(data: list[dict]) -> dict[str, str]:
    return {_fuel_to_key(fuel): fuel for fuel in _available_fuels(data)}


def _find_fuel_by_key_map(mapping: dict[str, str], fuel_key: str) -> str | None:
    return mapping.get(fuel_key)


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


def _get_display_data(
    context: ContextTypes.DEFAULT_TYPE,
) -> 'tuple[list[dict], dict | None, object]':
    """
    Return (prices, diffs, changed_at) sourced exclusively from S3 snapshots.

    Reads current.json for prices and changed_at, computes diffs against previous.json.
    Returns an empty tuple when S3 is unavailable or not configured.
    """
    config = _get_config(context)
    if not config.S3_BUCKET_NAME:
        return [], None, None
    try:
        from .snapshot import get_current_snapshot, get_previous_snapshot, compute_diffs
        cur = get_current_snapshot(config.S3_BUCKET_NAME, config.S3_CURRENT_KEY)
        if cur is None:
            return [], None, None
        prices = cur.get('prices', [])
        prev = get_previous_snapshot(config.S3_BUCKET_NAME, config.S3_PREVIOUS_KEY)
        diffs = compute_diffs(prices, prev.get('prices', [])) if prev else None
        changed_at_str = cur.get('changed_at')
        changed_at = datetime.fromisoformat(changed_at_str) if changed_at_str else None
        return prices, diffs, changed_at
    except Exception:
        logger.exception('Failed to load display data from S3')
        return [], None, None


def _get_reply_message(update: Update):
    message = update.effective_message
    if message is None:
        logger.warning('Skipping reply for update without effective_message: %s', update.update_id)
    return message


def _shortcuts_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('⛽ Degviela', callback_data=f'{_CB_PREFIX}fuelmenu'),
                InlineKeyboardButton('💰 Lētākais', callback_data=f'{_CB_PREFIX}best'),
            ],
            [
                InlineKeyboardButton('95', callback_data=f'{_CB_PREFIX}fuelbest:95'),
                InlineKeyboardButton('Diesel', callback_data=f'{_CB_PREFIX}fuelbest:diesel'),
                InlineKeyboardButton('LPG', callback_data=f'{_CB_PREFIX}fuelbest:lpg'),
            ],
            [
                InlineKeyboardButton('❓ Palīdzība', callback_data=f'{_CB_PREFIX}help'),
                InlineKeyboardButton('🔄 Atjaunot', callback_data=f'{_CB_PREFIX}refresh'),
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

    rows.append([InlineKeyboardButton('← Atpakaļ', callback_data=f'{_CB_PREFIX}home')])
    return InlineKeyboardMarkup(rows)


def _fuel_actions_markup(
    fuel_key: str,
    enabled_providers: tuple[str, ...] | list[str],
    is_favorite: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton('💰 Lētākais', callback_data=f'{_CB_PREFIX}fuelbest:{fuel_key}'),
            InlineKeyboardButton('⛽ Visas stacijas', callback_data=f'{_CB_PREFIX}fuelall:{fuel_key}'),
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
            '⭐ Noņemt' if is_favorite else '⭐ Saglabāt',
            callback_data=f'{_CB_PREFIX}favtoggle:{fuel_key}',
        )
    ])

    rows.append([
        InlineKeyboardButton('← Atpakaļ', callback_data=f'{_CB_PREFIX}fuelmenu'),
        InlineKeyboardButton('🏠 Sākums', callback_data=f'{_CB_PREFIX}home'),
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
        return f'⏱️ Uzgaidi {wait_seconds} sek. Mēģini vēlreiz.'

    if chat_remaining > 0:
        return f'⏱️ Uzgaidi {chat_remaining} sek. Mēģini vēlreiz.'

    return f'⏱️ Uzgaidi {global_remaining} sek. Mēģini vēlreiz.'


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

    from .snapshot import invalidate_snapshot_cache
    invalidate_snapshot_cache()

    config = _get_config(context)
    data, diffs, changed_at = _get_display_data(context)

    if not data:
        if from_callback:
            await _edit_callback_html(update, '⚠️ Dati nav pieejami. Mēģini vēlreiz pēc brīža.', reply_markup=_shortcuts_markup())
        else:
            await _reply_text(update, '⚠️ Dati nav pieejami. Mēģini vēlreiz pēc brīža.', shortcuts=True)
        return

    text = format_message(data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    if from_callback:
        await _edit_callback_html(update, text, reply_markup=_shortcuts_markup())
    else:
        await _reply_html(update, 'Mēģināts atjaunot datus.\n\n' + text, shortcuts=True)


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
                '⚠️ Radās kļūda. Spied "🔄 Atjaunot" un mēģini vēlreiz.',
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
            '⚠️ Radās kļūda. Mēģini vēlreiz pēc brīža.',
                reply_markup=_shortcuts_markup(),
            )
    except Exception:
        logger.exception('Failed to send error notification')


async def _provider_command(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str) -> None:
    config = _get_config(context)
    if provider not in config.ENABLED_PROVIDERS:
        await _reply_text(
            update,
            f'❌ Tirgotājs {get_brand_name(provider)} nav pieejams. Izvēlies citu tirgotāju.',
            shortcuts=True,
        )
        return

    data, diffs, changed_at = _get_display_data(context)
    text = format_provider_prices(data, provider, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    await _reply_html(update, text, shortcuts=True)


async def _send_fuel_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    config = _get_config(context)
    data, diffs, changed_at = _get_display_data(context)

    if args:
        text = format_lowest_price(data, args[0], config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    else:
        text = format_message(data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)

    await _reply_html(update, text, shortcuts=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_start_text(config.ENABLED_PROVIDERS), shortcuts=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    await _reply_text(update, format_help_text(config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE), shortcuts=True)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_text(update, '✅ Darbojas.', shortcuts=True)


async def fuel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_fuel_view(update, context)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await _reply_text(update, 'Norādi degvielas veidu. Mēģini, piemēram: /price diesel', shortcuts=True)
        return

    config = _get_config(context)
    fuel_query = args[0]
    data, diffs, changed_at = _get_display_data(context)
    text = format_lowest_price(data, fuel_query, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
    await _reply_html(update, text, shortcuts=True)


async def favorite_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    chat_id = _get_chat_id(update)
    favorites = _get_favorites(context, chat_id)
    config = _get_config(context)
    data, diffs, changed_at = _get_display_data(context)

    if not args or args[0].lower() == 'list':
        if not favorites:
            await _reply_text(update, 'Nav saglabātu favorītu. Pievieno: izvēlies degvielu un nospied zvaigznīti, vai izmanto /fav add 95', shortcuts=True)
            return
        fav_order = {fuel: i for i, fuel in enumerate(favorites)}
        fav_data = sorted(
            [row for row in data if row.get('fuel') in fav_order],
            key=lambda row: fav_order.get(row.get('fuel', ''), 999),
        )
        if not fav_data:
            await _reply_text(update, '⚠️ Cenu dati nav pieejami. Mēģini /refresh.', shortcuts=True)
            return
        text = format_best_prices(fav_data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
        await _reply_html(update, text, shortcuts=True)
        return

    action = args[0].lower()
    if action == 'clear':
        _set_favorites(context, chat_id, [])
        await _reply_text(update, 'Favorīti notīrīti.', shortcuts=True)
        return

    if len(args) < 2:
        await _reply_text(update, 'Norādi darbību: /fav add|remove|list|clear [degviela]', shortcuts=True)
        return

    fuel_name = _resolve_fuel_name(data, ' '.join(args[1:]))
    if not fuel_name:
        await _reply_text(update, '❌ Nevaru atrast šo degvielas veidu. Mēģini citu.', shortcuts=True)
        return

    if action == 'add':
        if fuel_name not in favorites:
            favorites.append(fuel_name)
            _set_favorites(context, chat_id, favorites)
        await _reply_text(update, f'✅ Pievienots favorītiem: {fuel_name}', shortcuts=True)
        return

    if action == 'remove':
        favorites = [fuel for fuel in favorites if fuel != fuel_name]
        _set_favorites(context, chat_id, favorites)
        await _reply_text(update, f'❌ Noņemts no favorītiem: {fuel_name}', shortcuts=True)
        return

    await _reply_text(update, 'Norādi darbību: /fav add|remove|list|clear [degviela]', shortcuts=True)


async def best(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = _get_config(context)
    data, diffs, changed_at = _get_display_data(context)
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
    snapshot = None
    if config.S3_BUCKET_NAME:
        try:
            from .snapshot import get_current_snapshot
            snapshot = get_current_snapshot(config.S3_BUCKET_NAME, config.S3_CURRENT_KEY)
        except Exception:
            logger.exception('Failed to load snapshot for status')
    text = format_snapshot_status(snapshot, config.CREDIT_MESSAGE)
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

    if action == f'{_CB_PREFIX}home':
        await _edit_callback_html(update, 'Izvēlies darbību:', reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}help':
        await _edit_callback_text(update, format_help_text(config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE), reply_markup=_shortcuts_markup())
        return

    if action == f'{_CB_PREFIX}refresh':
        await _run_refresh(update, context, from_callback=True)
        return

    data, diffs, changed_at = _get_display_data(context)
    key_map = _fuel_key_map(data)

    if action == f'{_CB_PREFIX}fuelmenu':
        if not data:
            await _edit_callback_html(
                update,
                '⚠️ Dati nav pieejami. Spied 🔄 Atjaunot, lai ielādētu cenas.',
                reply_markup=_shortcuts_markup(),
            )
            return
        await _edit_callback_html(
            update,
            'Izvēlies degvielas veidu:',
            reply_markup=_fuel_menu_markup(data, _get_favorites(context, _get_chat_id(update))),
        )
        return

    if action.startswith(f'{_CB_PREFIX}fuelsel:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key_map(key_map, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu. Mēģini citu.', reply_markup=_shortcuts_markup())
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

    if action.startswith(f'{_CB_PREFIX}fuelbest:'):
        fuel_key = action.split(':', 2)[2]
        fuel = _find_fuel_by_key_map(key_map, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
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
        fuel = _find_fuel_by_key_map(key_map, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
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
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
            return

        provider = parts[2]
        fuel_key = parts[3]
        fuel = _find_fuel_by_key_map(key_map, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
            return

        row = _extract_fuel_row(data, fuel)
        if row is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
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
        fuel = _find_fuel_by_key_map(key_map, fuel_key)
        if fuel is None:
            await _edit_callback_html(update, '❌ Nevaru atrast šo degvielas veidu šim tirgotājam. Mēģini citu.', reply_markup=_shortcuts_markup())
            return

        chat_id = _get_chat_id(update)
        favorites = _get_favorites(context, chat_id)
        if fuel in favorites:
            favorites = [item for item in favorites if item != fuel]
        else:
            favorites.append(fuel)
        _set_favorites(context, chat_id, favorites)

        text = format_lowest_price(data, fuel, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at)
        await _edit_callback_html(
            update,
            text,
            reply_markup=_fuel_actions_markup(
                fuel_key,
                config.ENABLED_PROVIDERS,
                is_favorite=fuel in favorites,
            ),
        )
        return

    if action == f'{_CB_PREFIX}best':
        await _edit_callback_html(update, format_best_prices(data, config.ENABLED_PROVIDERS, config.CREDIT_MESSAGE, diffs=diffs, changed_at=changed_at), reply_markup=_shortcuts_markup())
        return


def create_application(config: Config | None = None) -> Application:
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    cfg = config or Config()

    app = Application.builder().token(cfg.TELEGRAM_TOKEN).build()
    app.bot_data['config'] = cfg

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('fuel', fuel))
    app.add_handler(CommandHandler('price', price))
    app.add_handler(CommandHandler('fav', favorite_command))
    app.add_handler(CommandHandler('best', best))
    app.add_handler(CommandHandler('circlek', circlek))
    app.add_handler(CommandHandler('neste', neste))
    app.add_handler(CommandHandler('virsi', virsi))
    app.add_handler(CommandHandler('viada', viada))
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


from datetime import datetime
from zoneinfo import ZoneInfo


_BRAND_NAMES = {
    'circlek': 'Circle K',
    'neste': 'Neste',
    'virsi': 'Virši',
    'viada': 'Viada',
}
_SOURCE_HOSTS = {
    'circlek': 'circlek.lv',
    'neste': 'neste.lv',
    'virsi': 'virsi.lv',
    'viada': 'viada.lv',
}
_FUEL_QUERY_ALIASES = {
    '95': '95',
    '95e': '95',
    '95miles': '95',
    '95futura': '95',
    '95plus': '95 Premium',
    '95premium': '95 Premium',
    '95+': '95 Premium',
    '98': '98',
    '98e': '98',
    '98miles': '98',
    '98plus': '98',
    'diesel': 'Diesel',
    'd': 'Diesel',
    'dieselplus': 'Diesel Premium',
    'dieselpremium': 'Diesel Premium',
    'diesel+': 'Diesel Premium',
    'd+': 'Diesel Premium',
    'dd': 'Diesel',
    'dmiles': 'Diesel',
    'dmiles+': 'Diesel Premium',
    'xtl': 'XTL',
    'milesxtl': 'XTL',
    'gas': 'LPG',
    'autogas': 'LPG',
    'autogaze': 'LPG',
    'autogāze': 'LPG',
    'lpg': 'LPG',
    'cng': 'CNG',
    'e85': 'E85',
}
_HELP_ALIASES = ['95', '95+', '98', 'diesel', 'diesel+', 'xtl', 'gas', 'lpg', 'cng', 'e85']
_CREDIT = '☕ Ja noderēja, kafijai. Ja ne, nu neko: buymeacoffee.com/pizzadesk'
_DISPLAY_TIMEZONE = ZoneInfo('Europe/Riga')


def get_supported_aliases() -> list[str]:
    return list(_HELP_ALIASES)


def get_brand_name(source: str) -> str:
    return _BRAND_NAMES.get(source, source)


def format_help_text(enabled_providers: tuple[str, ...] | list[str]) -> str:
    provider_commands = ' '.join(f'/{provider}' for provider in enabled_providers)
    aliases = '|'.join(get_supported_aliases())
    enabled_names = ', '.join(get_brand_name(provider) for provider in enabled_providers)
    return (
        'Need fuel prices fast? Start here:\n'
        '1) Tap Choose Fuel\n'
        '2) Pick fuel type (95, Diesel, LPG)\n'
        '3) Choose Cheapest, All providers, or one provider\n\n'
        'Main buttons:\n'
        '- Choose Fuel: open fuel list\n'
        '- Cheapest: cheapest provider for each fuel\n'
        '- Update Prices: refresh latest prices\n'
        '- Bot Status: cache and provider health\n\n'
        'Quick commands:\n'
        '- /price diesel\n'
        '- /fuel\n'
        '- /best\n\n'
        'All commands:\n'
        '/fuel - full comparison\n'
        f'/fuel [{aliases}] - cheapest for one fuel type\n'
        f'/price [{aliases}] - cheapest for one fuel type\n'
        '/best - cheapest provider for each fuel\n'
        f'{provider_commands} - one provider\n'
        '/status - cache and provider health\n'
        '/refresh - update prices now\n'
        '/mode [compact|full|auto] - message style\n'
        '/fav [add|remove|list|clear] [fuel] - favorites\n'
        '/ping - bot health check\n\n'
        f'Enabled providers: {enabled_names}\n\n'
        '☕ Ja noderēja, kafijai. Ja ne, nu neko: buymeacoffee.com/pizzadesk\n'
    )


def format_start_text(enabled_providers: tuple[str, ...] | list[str]) -> str:
    enabled_names = ', '.join(get_brand_name(provider) for provider in enabled_providers)
    return (
        'Welcome!\n\n'
        '1) Tap Choose Fuel\n'
        '2) Pick a fuel type\n'
        '3) Choose Cheapest, All providers, or one provider\n\n'
        'You can also use Cheapest, Update Prices, and Bot Status buttons.\n\n'
        'Need help? Tap Help or send /help.\n'
        f'Enabled providers: {enabled_names}.'
    )


def normalize_fuel_query(fuel_query: str) -> str | None:
    normalized = fuel_query.strip().lower().replace(' ', '')
    return _FUEL_QUERY_ALIASES.get(normalized)


def _footer(sources: list[str] | None = None) -> str:
    source_list = sources or list(_SOURCE_HOSTS.values())
    now = datetime.now(_DISPLAY_TIMEZONE)
    return (
        f"🕒 Updated: {now.strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        f"🔗 Websites: {', '.join(source_list)}\n"
        f"{_CREDIT}"
    )


def _format_display_time(value: datetime | None) -> str:
    if value is None:
        return 'not refreshed yet'

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo('UTC'))

    return value.astimezone(_DISPLAY_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S %Z')


def _extract_prices(item: dict, providers: tuple[str, ...] | list[str] | None = None) -> list[tuple[float, str, str, str]]:
    active_providers = providers or list(_BRAND_NAMES)
    prices: list[tuple[float, str, str, str]] = []
    for station, price in item.items():
        if station == 'fuel' or station not in active_providers or not price:
            continue
        try:
            value = float(price)
        except ValueError:
            continue
        prices.append((value, get_brand_name(station), price, station))
    prices.sort(key=lambda entry: entry[0])
    return prices


def format_message(data: list[dict], enabled_providers: tuple[str, ...] | list[str] | None = None) -> str:
    if not data:
        return "⛽ Fuel prices are not available right now. Please try again in a moment.\n" + _CREDIT

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = "⛽ <b>Fuel Prices in Latvia</b>\n\n"

    for item in data:
        fuel = item.get('fuel', 'Unknown')
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue

        message += f"<b>🛢️ {fuel}</b>\n"
        for idx, (_, name, raw_price, _) in enumerate(prices):
            if idx == 0:
                message += f"<b>{name}: €{raw_price}</b> ⭐\n"
            else:
                message += f"{name}: €{raw_price}\n"
        message += "\n"

    message += _footer([_SOURCE_HOSTS[source] for source in active_providers])
    return message


def format_compact_message(data: list[dict], enabled_providers: tuple[str, ...] | list[str] | None = None) -> str:
    if not data:
        return "⛽ Fuel prices are not available right now. Please try again in a moment.\n" + _CREDIT

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = "⛽ <b>Fuel Prices (Quick View)</b>\n\n"
    found_any = False

    for item in data:
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue
        found_any = True
        best = prices[0]
        message += f"<b>{item.get('fuel', 'Unknown')}</b>: {best[1]} €{best[2]} ⭐\n"

    if not found_any:
        return "⛽ No enabled providers returned fuel prices.\n" + _CREDIT

    message += '\n' + _footer([_SOURCE_HOSTS[source] for source in active_providers])
    return message


def format_lowest_price(data: list[dict], fuel_query: str, enabled_providers: tuple[str, ...] | list[str] | None = None) -> str:
    if not data:
        return "⛽ Fuel prices are not available right now. Please try again in a moment.\n" + _CREDIT

    fuel_key = normalize_fuel_query(fuel_query)
    if not fuel_key:
        return "❓ Fuel type not recognized. Example: /price diesel\n" + _CREDIT

    item = next((row for row in data if row.get('fuel') == fuel_key), None)
    if not item:
        return f"❌ {fuel_key} is not available in the latest update.\n" + _CREDIT

    active_providers = list(enabled_providers or _BRAND_NAMES)
    prices = _extract_prices(item, active_providers)
    if not prices:
        return f"❌ No prices available for {fuel_key} right now.\n" + _CREDIT

    best = prices[0]
    return (
        f"⛽ Cheapest price for <b>{fuel_key}</b>:\n\n"
        f"<b>{best[1]}: €{best[2]}</b> ⭐\n\n"
        f"Compared providers: {', '.join(get_brand_name(provider) for provider in active_providers)}\n"
        f"🔗 Sources: {', '.join(_SOURCE_HOSTS[provider] for provider in active_providers)}\n"
        + _CREDIT
    )


def format_best_prices(data: list[dict], enabled_providers: tuple[str, ...] | list[str] | None = None) -> str:
    if not data:
        return "⛽ Fuel prices are not available right now. Please try again in a moment.\n" + _CREDIT

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = '📉 <b>Cheapest Prices by Fuel</b>\n\n'
    found_any = False
    for item in data:
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue
        found_any = True
        best = prices[0]
        message += f"<b>{item.get('fuel', 'Unknown')}</b>: {best[1]} €{best[2]} ⭐\n"

    if not found_any:
        return "⛽ No enabled providers returned fuel prices.\n" + _CREDIT

    return message + '\n' + _footer([_SOURCE_HOSTS[source] for source in active_providers])


def format_provider_prices(data: list[dict], provider: str) -> str:
    if not data:
        return "⛽ Fuel prices are not available right now. Please try again in a moment.\n" + _CREDIT

    provider_name = get_brand_name(provider)
    host = _SOURCE_HOSTS.get(provider, provider)
    message = f"⛽ <b>{provider_name} Fuel Prices</b>\n\n"
    found_any = False

    for item in data:
        price = item.get(provider)
        if not price:
            continue
        found_any = True
        message += f"<b>{item.get('fuel', 'Unknown')}</b>: €{price}\n"

    if not found_any:
        return f"❌ No prices available for {provider_name} right now.\n" + _CREDIT

    return message + '\n' + _footer([host])


def format_status(status: dict) -> str:
    enabled_sources = status.get('enabled_sources', [])
    last_refresh_attempt_at = status.get('last_refresh_attempt_at')
    last_refresh_at = status.get('last_refresh_at')
    last_refresh_error = status.get('last_refresh_error')
    cache_expires_at = status.get('cache_expires_at')
    ttl_seconds = status.get('cache_ttl_seconds')

    message = '📊 <b>Bot Status</b>\n\n'
    message += f"Available providers: {', '.join(get_brand_name(provider) for provider in enabled_sources)}\n\n"
    message += f"Data cache time: {ttl_seconds}s\n"
    message += f"Last update try: {_format_display_time(last_refresh_attempt_at)}\n"
    message += f"Last successful update: {_format_display_time(last_refresh_at)}\n\n"
    message += 'Data valid until: '
    message += _format_display_time(cache_expires_at) if cache_expires_at else 'no cache yet'
    if last_refresh_error:
        message += f"\nLast update issue: {last_refresh_error}"
    message += '\n\n'

    for source, source_status in status.get('sources', {}).items():
        provider_name = source_status.get('name', get_brand_name(source))
        if not source_status.get('enabled'):
            message += f"{provider_name}: not enabled\n"
            continue
        if source_status.get('ok'):
            message += f"{provider_name}: ok ({source_status.get('count', 0)} fuel types)\n"
        else:
            error = source_status.get('error') or 'waiting for first successful update'
            message += f"{provider_name}: issue - {error}\n"

    message += '\n' + _CREDIT
    return message

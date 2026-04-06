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
_DISPLAY_TIMEZONE = ZoneInfo('Europe/Riga')


def get_supported_aliases() -> list[str]:
    return list(_HELP_ALIASES)


def get_brand_name(source: str) -> str:
    return _BRAND_NAMES.get(source, source)


def format_price_diff(delta: float | None) -> str:
    """Return a short diff badge string, or empty string when there is no change."""
    if not delta:  # covers None and 0.0
        return ''
    if delta > 0:
        return f' ▲ {delta:.3f}'
    return f' ▼ {abs(delta):.3f}'


def _normalize_credit_message(credit_message: str | None) -> str:
    return credit_message.strip() if credit_message else ''


def _append_credit(message: str, credit_message: str | None) -> str:
    credit = _normalize_credit_message(credit_message)
    if not credit:
        return message
    return f'{message}\n\n{credit}'


def format_help_text(enabled_providers: tuple[str, ...] | list[str], credit_message: str | None = None) -> str:
    provider_commands = ' · '.join(f'/{provider}' for provider in enabled_providers)
    message = (
        'Kā lietot botu\n\n'
        '⛽ "Degviela" — izvēlies degvielas veidu un tirgotāju\n'
        '💰 "Lētākais" — apskati izdevīgākās cenas\n\n'
        'Komandas:\n'
        '/fuel — visas cenas\n'
        '/best — lētākās cenas katram degvielas veidam\n'
        '/price 95 — lētākā cena izvēlētajam degvielas veidam\n'
        f'{provider_commands} — konkrēta tirgotāja cenas\n'
        '/fav — saglabātie degvielas veidi\n'
        '/refresh — atjauno cenas\n'
        '/mode compact|full — izvēlies skata režīmu'
    )
    return _append_credit(message, credit_message)


def format_start_text(enabled_providers: tuple[str, ...] | list[str]) -> str:
    return (
        'Sveiki! 👋\n\n'
        'Spied "⛽ Degviela", lai apskatītu cenas,\n'
        'vai uzreiz — "💰 Lētākais".\n\n'
        'Palīdzība: /help'
    )


def normalize_fuel_query(fuel_query: str) -> str | None:
    normalized = fuel_query.strip().lower().replace(' ', '')
    return _FUEL_QUERY_ALIASES.get(normalized)


def _footer(
    sources: list[str] | None = None,
    credit_message: str | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    source_list = sources or list(_SOURCE_HOSTS.values())
    now = datetime.now(_DISPLAY_TIMEZONE)
    lines = [f" Pēdējais pieprasījums: {_format_display_time(now)}"]
    if changed_at is not None:
        lines.append(f"📅 Cenas atjaunotas: {_format_display_time(changed_at)}")
    lines += ['', f"🔗 {' · '.join(source_list)}"]
    credit = _normalize_credit_message(credit_message)
    if credit:
        lines.append(credit)
    return '\n'.join(lines)


def _format_display_time(value: datetime | None) -> str:
    if value is None:
        return 'nav datu'

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo('UTC'))

    local = value.astimezone(_DISPLAY_TIMEZONE)
    now = datetime.now(_DISPLAY_TIMEZONE)
    if local.date() == now.date():
        day_label = 'šodien'
    elif local.date() == (now.date()).fromordinal(now.date().toordinal() - 1):
        day_label = 'vakar'
    else:
        day_label = local.strftime('%d.%m.')

    return f"{day_label} {local.strftime('%H:%M')}"


def _format_cache_duration(ttl_seconds: int | None) -> str:
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        return 'nav zināms'

    if ttl_seconds < 60:
        return 'mazāk par 1 minūti'

    minutes = round(ttl_seconds / 60)
    if minutes < 60:
        unit = 'minūte' if minutes == 1 else 'minūtes'
        return f'aptuveni {minutes} {unit}'

    hours = minutes // 60
    remaining_minutes = minutes % 60
    hour_unit = 'stunda' if hours == 1 else 'stundas'
    if remaining_minutes == 0:
        return f'aptuveni {hours} {hour_unit}'

    minute_unit = 'minūte' if remaining_minutes == 1 else 'minūtes'
    return f'aptuveni {hours} {hour_unit} {remaining_minutes} {minute_unit}'


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


def format_message(
    data: list[dict],
    enabled_providers: tuple[str, ...] | list[str] | None = None,
    credit_message: str | None = None,
    diffs: dict | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    if not data:
        return _append_credit('⚠️ Nevaru ielādēt cenas. Mēģini vēlreiz.', credit_message)

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = "⛽ <b>Degvielas cenas</b>\n\n"

    for item in data:
        fuel = item.get('fuel', 'Nezināms')
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue

        message += f"<b>🛢️ {fuel}</b>\n"
        for idx, (_, name, raw_price, source) in enumerate(prices):
            diff_str = format_price_diff(diffs.get((source, fuel)) if diffs is not None else None)
            if idx == 0:
                message += f"<b>{name}: €{raw_price}{diff_str}</b> ⭐\n"
            else:
                message += f"{name}: €{raw_price}{diff_str}\n"
        message += "\n"

    message += _footer([_SOURCE_HOSTS[source] for source in active_providers], credit_message, changed_at=changed_at)
    return message


def format_compact_message(
    data: list[dict],
    enabled_providers: tuple[str, ...] | list[str] | None = None,
    credit_message: str | None = None,
    diffs: dict | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    if not data:
        return _append_credit('⚠️ Nevaru ielādēt cenas. Mēģini vēlreiz.', credit_message)

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = "⛽ <b>Degvielas cenas</b>\n\n"
    found_any = False

    for item in data:
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue
        found_any = True
        best = prices[0]
        fuel = item.get('fuel', 'Nezināms')
        diff_str = format_price_diff(diffs.get((best[3], fuel)) if diffs is not None else None)
        message += f"<b>{fuel}</b>: {best[1]} €{best[2]}{diff_str} ⭐\n"

    if not found_any:
        return _append_credit('⚠️ Nevaru atrast cenu datus. Mēģini vēlreiz.', credit_message)

    message += '\n' + _footer([_SOURCE_HOSTS[source] for source in active_providers], credit_message, changed_at=changed_at)
    return message


def format_lowest_price(
    data: list[dict],
    fuel_query: str,
    enabled_providers: tuple[str, ...] | list[str] | None = None,
    credit_message: str | None = None,
    diffs: dict | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    if not data:
        return _append_credit('⚠️ Nevaru ielādēt cenas. Mēģini vēlreiz.', credit_message)

    fuel_key = normalize_fuel_query(fuel_query)
    if not fuel_key:
        return _append_credit('❓ Neatpazīstu degvielas veidu. Mēģini, piemēram: /price diesel', credit_message)

    item = next((row for row in data if row.get('fuel') == fuel_key), None)
    if not item:
        return _append_credit(f'❌ Nevaru atrast degvielu {fuel_key} pie neviena tirgotāja. Mēģini citu.', credit_message)

    active_providers = list(enabled_providers or _BRAND_NAMES)
    prices = _extract_prices(item, active_providers)
    if not prices:
        return _append_credit(f'❌ Nevaru atrast cenas degvielai {fuel_key}. Mēģini citu.', credit_message)

    best = prices[0]
    diff_str = format_price_diff(diffs.get((best[3], fuel_key)) if diffs is not None else None)
    changed_line = f"\n📅 Cenas atjaunotas: {_format_display_time(changed_at)}" if changed_at is not None else ''
    return _append_credit(
        (
            f"⛽ <b>{fuel_key}</b> — lētākais\n\n"
            f"<b>{best[1]}: €{best[2]}{diff_str}</b> ⭐"
            f"{changed_line}"
        ).rstrip(),
        credit_message,
    )


def format_best_prices(
    data: list[dict],
    enabled_providers: tuple[str, ...] | list[str] | None = None,
    credit_message: str | None = None,
    diffs: dict | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    if not data:
        return _append_credit('⚠️ Nevaru ielādēt cenas. Mēģini vēlreiz.', credit_message)

    active_providers = list(enabled_providers or _BRAND_NAMES)
    message = '💰 <b>Lētākās cenas</b>\n\n'
    found_any = False
    for item in data:
        prices = _extract_prices(item, active_providers)
        if not prices:
            continue
        found_any = True
        best = prices[0]
        fuel = item.get('fuel', 'Nezināms')
        diff_str = format_price_diff(diffs.get((best[3], fuel)) if diffs is not None else None)
        message += f"<b>{fuel}</b>: {best[1]} €{best[2]}{diff_str} ⭐\n"

    if not found_any:
        return _append_credit('⚠️ Nevaru atrast cenu datus. Mēģini vēlreiz.', credit_message)

    return message + '\n' + _footer([_SOURCE_HOSTS[source] for source in active_providers], credit_message, changed_at=changed_at)


def format_provider_prices(
    data: list[dict],
    provider: str,
    credit_message: str | None = None,
    diffs: dict | None = None,
    changed_at: 'datetime | None' = None,
) -> str:
    if not data:
        return _append_credit('⚠️ Nevaru ielādēt cenas. Mēģini vēlreiz.', credit_message)

    provider_name = get_brand_name(provider)
    host = _SOURCE_HOSTS.get(provider, provider)
    message = f"⛽ <b>{provider_name}</b>\n\n"
    found_any = False

    for item in data:
        price = item.get(provider)
        if not price:
            continue
        found_any = True
        fuel = item.get('fuel', 'Nezināms')
        diff_str = format_price_diff(diffs.get((provider, fuel)) if diffs is not None else None)
        message += f"<b>{fuel}</b>: €{price}{diff_str}\n"

    if not found_any:
        return _append_credit(f'❌ Nevaru atrast cenas pie tirgotāja {provider_name}. Mēģini citu tirgotāju.', credit_message)

    return message + '\n' + _footer([host], credit_message, changed_at=changed_at)


def format_snapshot_status(snapshot: 'dict | None', credit_message: str | None = None) -> str:
    message = 'ℹ️ <b>Bota darbības statuss</b>\n\n'
    if snapshot is None:
        message += '⚠️ Dati nav pieejami. Pagaidi nākamo regulāro atjauninājumu.\n'
        return _append_credit(message.rstrip(), credit_message)

    scraped_at: 'datetime | None' = None
    changed_at: 'datetime | None' = None
    scraped_at_str = snapshot.get('scraped_at')
    changed_at_str = snapshot.get('changed_at')
    if scraped_at_str:
        try:
            scraped_at = datetime.fromisoformat(scraped_at_str)
        except Exception:
            pass
    if changed_at_str:
        try:
            changed_at = datetime.fromisoformat(changed_at_str)
        except Exception:
            pass

    price_count = len(snapshot.get('prices', []))
    message += f'📡 Pēdējais pieprasījums: {_format_display_time(scraped_at)}\n'
    message += f'📅 Cenas atjaunotas: {_format_display_time(changed_at)}\n'
    message += f'📊 Degvielas veidi: {price_count}\n'
    return _append_credit(message.rstrip(), credit_message)


def format_status(status: dict, credit_message: str | None = None) -> str:
    last_refresh_at = status.get('last_refresh_at')
    last_refresh_error = status.get('last_refresh_error')

    message = 'ℹ️ <b>Bota darbības statuss</b>\n\n'
    message += f"Pēdējais veiksmīgais atjauninājums: {_format_display_time(last_refresh_at)}\n"
    if last_refresh_error:
        message += f"⚠️ {last_refresh_error}\n"
    message += '\n'

    for source, source_status in status.get('sources', {}).items():
        provider_name = source_status.get('name', get_brand_name(source))
        if not source_status.get('enabled'):
            message += f"{provider_name}: izslēgts\n"
            continue
        if source_status.get('ok'):
            count = source_status.get('count', 0)
            message += f"{provider_name} ✅ {count} veidi\n"
        else:
            message += f"{provider_name} ⚠️ Datus neizdevās ielādēt. Mēģini /refresh.\n"

    return _append_credit(message.rstrip(), credit_message)

import re
import os
import logging
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SOURCE_URLS = {
    'circlek': 'https://www.circlek.lv/degviela-miles/degvielas-cenas',
    'neste': 'https://www.neste.lv/lv/content/degvielas-cenas',
    'virsi': 'https://www.virsi.lv/lv/privatpersonam/degviela/degvielas-un-elektrouzlades-cenas',
    'viada': 'https://www.viada.lv/zemakas-degvielas-cenas/',
}
_SOURCE_ORDER = ['circlek', 'neste', 'virsi', 'viada']
_VIADA_IMAGE_FUELS = {
    'petrol_95ecto_new': '95',
    'petrol_95ectoplus_new': '95_premium',
    'petrol_98_new': '98',
    'petrol_d_new': 'diesel',
    'petrol_d_ecto_new': 'diesel_premium',
    'gaze': 'lpg',
    'petrol_e85_new': 'e85',
}
_DISPLAY_NAMES = {
    '95': '95',
    '95_premium': '95 Premium',
    '98': '98',
    'diesel': 'Diesel',
    'diesel_premium': 'Diesel Premium',
    'xtl': 'XTL',
    'lpg': 'LPG',
    'cng': 'CNG',
    'e85': 'E85',
}
_BRAND_NAMES = {
    'circlek': 'Circle K',
    'neste': 'Neste',
    'virsi': 'Virsi',
    'viada': 'Viada',
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


_CACHE_TTL_SECONDS = _env_int('SCRAPER_CACHE_TTL_SECONDS', 1800)
_REQUEST_TIMEOUT = (
    _env_int('SCRAPER_CONNECT_TIMEOUT_SECONDS', 2),
    _env_int('SCRAPER_READ_TIMEOUT_SECONDS', 4),
)
_MAX_SCRAPE_WORKERS = _env_int('SCRAPER_MAX_WORKERS', 4)


@dataclass(frozen=True)
class RefreshResult:
    data: list[dict]
    refreshed: bool


_cached_data: list[dict] | None = None
_cache_expires_at: datetime = datetime.fromtimestamp(0)
_last_refresh_at: datetime | None = None
_last_refresh_attempt_at: datetime | None = None
_last_refresh_error: str | None = None
_last_source_status: dict[str, dict] = {
    source: {
        'enabled': True,
        'ok': False,
        'count': 0,
        'error': None,
    }
    for source in _SOURCE_ORDER
}
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.mount('http://', HTTPAdapter(pool_connections=8, pool_maxsize=8))
_HTTP_SESSION.mount('https://', HTTPAdapter(pool_connections=8, pool_maxsize=8))
_HTTP_SESSION.headers.update({'User-Agent': 'DegvielaLV-Bot/1.0 (+https://github.com/your-org/DegvielaLV_TG_Lambda)'})


def get_brand_name(source: str) -> str:
    return _BRAND_NAMES.get(source, source)


def get_enabled_sources(enabled_sources: tuple[str, ...] | list[str] | None = None) -> list[str]:
    if enabled_sources is None:
        return list(_SOURCE_ORDER)
    return [source for source in _SOURCE_ORDER if source in enabled_sources]


def _normalize_price(cell_text: str) -> str | None:
    """Normalize cell data to a canonical numeric price string."""
    if not cell_text:
        return None

    text = cell_text.strip().replace(',', '.')
    text = text.lstrip('€').strip()

    m = re.match(r'([0-9]+(?:\.[0-9]+)?)(?:\s*([+-])\s*([0-9]+(?:\.[0-9]+)?))?', text)
    if not m:
        return None

    base = float(m.group(1))
    sign = m.group(2)
    value = m.group(3)
    if sign and value:
        delta = float(value)
        base = base + delta if sign == '+' else base - delta

    # Keep 3 decimals for consistent formatting.
    return f"{base:.3f}"


def _normalize_fuel_name(fuel_text: str) -> str | None:
    if not fuel_text:
        return None

    normalized = fuel_text.strip().lower().replace('\xa0', ' ')
    normalized = re.sub(r'\s+', ' ', normalized)

    fuel_map = {
        '95': '95',
        '95e': '95',
        '95miles': '95',
        'neste futura 95': '95',
        '98': '98',
        '98e': '98',
        '98miles+': '98',
        'neste futura 98': '98',
        'dd': 'diesel',
        'dmiles': 'diesel',
        'diesel': 'diesel',
        'neste futura d': 'diesel',
        'd': 'diesel',
        'dmiles+': 'diesel_premium',
        'diesel+': 'diesel_premium',
        'neste pro diesel': 'diesel_premium',
        'miles+ xtl': 'xtl',
        'xtl': 'xtl',
        'gas/lpg': 'lpg',
        'lpg': 'lpg',
        'autogāze': 'lpg',
        'autogaze': 'lpg',
        'cng': 'cng',
        'e85': 'e85',
    }

    return fuel_map.get(normalized)


def _empty_row(fuel_key: str) -> dict:
    row = {'fuel': _DISPLAY_NAMES.get(fuel_key, fuel_key)}
    for source in _SOURCE_ORDER:
        row[source] = None
    return row


def _upsert_price(rows: dict[str, dict], fuel_key: str | None, source: str, price: str | None) -> None:
    if not fuel_key or not price:
        return

    if fuel_key not in rows:
        rows[fuel_key] = _empty_row(fuel_key)
    rows[fuel_key][source] = price


def _http_get(url: str, headers: dict | None = None) -> requests.Response:
    return _HTTP_SESSION.get(url, timeout=_REQUEST_TIMEOUT, headers=headers)


def _scrape_circlek(url: str) -> dict[str, str]:
    data: dict[str, str] = {}
    response = _http_get(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find('table')
    if not table:
        return data

    for row in table.find_all('tr')[1:]:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue
        fuel_key = _normalize_fuel_name(cells[0].get_text(strip=True))
        price = _normalize_price(cells[1].get_text(strip=True))
        if fuel_key and price:
            data[fuel_key] = price

    return data


def _scrape_neste(url: str) -> dict[str, str]:
    data: dict[str, str] = {}
    response = _http_get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find('table')
    if not table:
        return data

    for row in table.find_all('tr')[1:]:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue
        fuel_key = _normalize_fuel_name(cells[0].get_text(strip=True))
        price = _normalize_price(cells[1].get_text(strip=True))
        if fuel_key and price:
            data[fuel_key] = price

    return data


def _scrape_virsi(url: str) -> dict[str, str]:
    data: dict[str, str] = {}
    response = _http_get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')
    for card in soup.select('div.price-card'):
        price_tag = card.select_one('p.price')
        if not price_tag:
            continue

        spans = price_tag.find_all('span')
        if len(spans) < 2:
            continue

        fuel_key = _normalize_fuel_name(spans[0].get_text(strip=True))
        price = _normalize_price(spans[1].get_text(strip=True))
        if fuel_key and price:
            data[fuel_key] = price

    return data


def _scrape_viada(url: str) -> dict[str, str]:
    data: dict[str, str] = {}
    response = _http_get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find('table')
    if not table:
        return data

    for row in table.find_all('tr')[1:]:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue

        fuel_key = None
        image = cells[0].find('img') if cells else None
        if image and image.get('src'):
            image_name = image['src'].rsplit('/', 1)[-1].split('.', 1)[0].lower()
            fuel_key = _VIADA_IMAGE_FUELS.get(image_name)

        price = _normalize_price(cells[1].get_text(strip=True))
        if fuel_key and price:
            data[fuel_key] = price

    return data


def _scrape_all_sources(
    primary_url: str | None = None,
    enabled_sources: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    global _last_source_status

    source_urls = dict(_SOURCE_URLS)
    if primary_url:
        source_urls['circlek'] = primary_url

    rows: dict[str, dict] = {}
    active_sources = get_enabled_sources(enabled_sources)
    if not active_sources:
        return []

    source_scrapers = {
        'circlek': _scrape_circlek,
        'neste': _scrape_neste,
        'virsi': _scrape_virsi,
        'viada': _scrape_viada,
    }

    _last_source_status = {
        source: {
            'enabled': source in active_sources,
            'ok': False,
            'count': 0,
            'error': None,
        }
        for source in _SOURCE_ORDER
    }

    max_workers = max(1, min(_MAX_SCRAPE_WORKERS, len(active_sources)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(source_scrapers[source], source_urls[source]): source
            for source in active_sources
        }

        for future in as_completed(futures):
            source = futures[future]
            try:
                source_data = future.result()
            except requests.RequestException as exc:
                logger.error('Network error while scraping %s: %s', source, exc)
                _last_source_status[source]['error'] = str(exc)
                continue
            except Exception:
                logger.exception('Unexpected error while scraping %s', source)
                _last_source_status[source]['error'] = 'Unexpected scraping error'
                continue

            _last_source_status[source]['ok'] = True
            _last_source_status[source]['count'] = len(source_data)

            for fuel_key, price in source_data.items():
                _upsert_price(rows, fuel_key, source, price)

    return [rows[key] for key in _DISPLAY_NAMES if key in rows]


def scrape_fuel_prices(
    url: str,
    enabled_sources: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    """Fetch fuel prices from the URL and parse them into structured data."""
    try:
        return _scrape_all_sources(url, enabled_sources=enabled_sources)
    except Exception:
        logger.exception('Unexpected error while scraping')
        return []


def refresh_fuel_prices(
    url: str,
    enabled_sources: tuple[str, ...] | list[str] | None = None,
) -> RefreshResult:
    global _cached_data, _cache_expires_at, _last_refresh_at, _last_refresh_attempt_at, _last_refresh_error

    now = datetime.utcnow()
    _last_refresh_attempt_at = now

    logger.info('Refreshing fuel prices from source')
    fresh_data = scrape_fuel_prices(url, enabled_sources=enabled_sources)
    if fresh_data:
        _cached_data = fresh_data
        _last_refresh_at = now
        _last_refresh_error = None
        _cache_expires_at = now + timedelta(seconds=_CACHE_TTL_SECONDS)
        return RefreshResult(data=_cached_data, refreshed=True)

    _last_refresh_error = 'Refresh failed; keeping last known good cache'
    logger.warning(_last_refresh_error)

    if _cached_data is not None:
        return RefreshResult(data=_cached_data, refreshed=False)

    _cache_expires_at = datetime.fromtimestamp(0)
    return RefreshResult(data=[], refreshed=False)


def get_fuel_prices(
    url: str,
    force_refresh: bool = False,
    enabled_sources: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    """Return cached fuel prices for a small TTL, refresh from source if expired."""
    global _cached_data, _cache_expires_at

    now = datetime.utcnow()
    if not force_refresh and _cached_data is not None and now < _cache_expires_at:
        logger.debug('Using cached fuel prices (expires at %s)', _cache_expires_at)
        return _cached_data

    return refresh_fuel_prices(url, enabled_sources=enabled_sources).data


def get_scrape_status(enabled_sources: tuple[str, ...] | list[str] | None = None) -> dict:
    active_sources = get_enabled_sources(enabled_sources)
    return {
        'cache_ttl_seconds': _CACHE_TTL_SECONDS,
        'last_refresh_attempt_at': _last_refresh_attempt_at,
        'last_refresh_at': _last_refresh_at,
        'last_refresh_error': _last_refresh_error,
        'cache_expires_at': _cache_expires_at if _cached_data is not None else None,
        'enabled_sources': active_sources,
        'sources': {
            source: {
                **_last_source_status.get(source, {}),
                'name': get_brand_name(source),
            }
            for source in _SOURCE_ORDER
        },
    }

import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300  # 5 minutes per warm container

_cached_current: dict | None = None
_current_cache_expires_at: datetime = datetime.fromtimestamp(0, tz=timezone.utc)
_cached_previous: dict | None = None
_previous_cache_expires_at: datetime = datetime.fromtimestamp(0, tz=timezone.utc)


def _s3_client():
    import boto3  # noqa: PLC0415 — lazy import keeps boto3 optional in local dev
    return boto3.client('s3')


def _is_missing_or_unavailable_snapshot(exc: Exception) -> bool:
    """
    Return True for S3 read errors that should be treated as "snapshot unavailable".

    Cases:
    - NoSuchKey when the object does not exist.
    - AccessDenied that references s3:ListBucket, which can happen when the key
      is missing and the role cannot list the bucket.
    """
    response = getattr(exc, 'response', None)
    if not isinstance(response, dict):
        return False

    error = response.get('Error', {})
    code = str(error.get('Code', ''))
    message = str(error.get('Message', ''))

    if code == 'NoSuchKey':
        return True
    if code == 'AccessDenied' and 's3:ListBucket' in message:
        return True
    return False


def read_snapshot(bucket: str, key: str) -> dict | None:
    """Read and parse a JSON snapshot from S3. Returns None if missing or on any error."""
    try:
        client = _s3_client()
        response = client.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read())
    except Exception as exc:
        if _is_missing_or_unavailable_snapshot(exc):
            logger.info('Snapshot unavailable at s3://%s/%s; continuing without diff context', bucket, key)
            return None
        logger.exception('Failed to read snapshot s3://%s/%s', bucket, key)
        return None


def write_snapshot(bucket: str, key: str, snapshot: dict) -> bool:
    """Serialize and write a snapshot dict to S3. Returns True on success."""
    try:
        client = _s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(snapshot).encode(),
            ContentType='application/json',
        )
        return True
    except Exception:
        logger.exception('Failed to write snapshot s3://%s/%s', bucket, key)
        return False


def prices_changed(old_prices: list[dict], new_prices: list[dict]) -> bool:
    """Return True if any price value differs between the two price lists."""
    def price_map(prices: list[dict]) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        for item in prices:
            fuel = item.get('fuel')
            if not fuel:
                continue
            for key, value in item.items():
                if key != 'fuel' and value is not None:
                    result[(key, fuel)] = value
        return result

    return price_map(old_prices) != price_map(new_prices)


def compute_diffs(current: list[dict], previous: list[dict]) -> dict[tuple[str, str], float]:
    """
    Compute per-(source, fuel) price deltas: current price minus previous price.

    Returns a dict keyed by (source_key, fuel_display_name) -> delta float.
    Only entries with a non-zero delta are included.
    """
    prev_map: dict[tuple[str, str], float] = {}
    for item in previous:
        fuel = item.get('fuel')
        if not fuel:
            continue
        for key, value in item.items():
            if key != 'fuel' and value is not None:
                try:
                    prev_map[(key, fuel)] = float(value)
                except (ValueError, TypeError):
                    pass

    diffs: dict[tuple[str, str], float] = {}
    for item in current:
        fuel = item.get('fuel')
        if not fuel:
            continue
        for key, value in item.items():
            if key != 'fuel' and value is not None:
                try:
                    curr_val = float(value)
                except (ValueError, TypeError):
                    continue
                prev_val = prev_map.get((key, fuel))
                if prev_val is not None:
                    delta = round(curr_val - prev_val, 3)
                    if delta != 0.0:
                        diffs[(key, fuel)] = delta

    return diffs


def get_current_snapshot(bucket: str, key: str) -> dict | None:
    """Return current snapshot from in-memory cache, refreshing from S3 when stale."""
    global _cached_current, _current_cache_expires_at
    now = datetime.now(tz=timezone.utc)
    if _cached_current is not None and now < _current_cache_expires_at:
        return _cached_current
    snapshot = read_snapshot(bucket, key)
    _cached_current = snapshot
    _current_cache_expires_at = now + timedelta(seconds=_CACHE_TTL_SECONDS)
    return snapshot


def get_previous_snapshot(bucket: str, key: str) -> dict | None:
    """Return previous snapshot from in-memory cache, refreshing from S3 when stale."""
    global _cached_previous, _previous_cache_expires_at
    now = datetime.now(tz=timezone.utc)
    if _cached_previous is not None and now < _previous_cache_expires_at:
        return _cached_previous
    snapshot = read_snapshot(bucket, key)
    _cached_previous = snapshot
    _previous_cache_expires_at = now + timedelta(seconds=_CACHE_TTL_SECONDS)
    return snapshot


_SNAPSHOT_MAX_AGE_SECONDS = 10800  # 3 hours — fall back to live scrape beyond this


def get_snapshot_data(
    bucket: str,
    current_key: str,
    previous_key: str,
    max_age_seconds: int = _SNAPSHOT_MAX_AGE_SECONDS,
) -> 'tuple[list[dict], dict | None, datetime | None] | None':
    """
    Return (prices, diffs, changed_at) sourced entirely from S3 snapshots.

    Returns None if current.json is missing or older than max_age_seconds,
    so the caller can fall back to a live scrape.
    Diffs compare current.json prices against previous.json prices.
    """
    cur = get_current_snapshot(bucket, current_key)
    if cur is None:
        return None

    scraped_at_str = cur.get('scraped_at')
    if scraped_at_str:
        try:
            scraped_at = datetime.fromisoformat(scraped_at_str)
            age = (datetime.now(tz=timezone.utc) - scraped_at).total_seconds()
            if age > max_age_seconds:
                logger.warning('current.json is %.0f seconds old; falling back to live scrape', age)
                return None
        except Exception:
            pass

    prices = cur.get('prices', [])
    if not prices:
        return None

    changed_at_str = cur.get('changed_at')
    changed_at: datetime | None = None
    if changed_at_str:
        try:
            changed_at = datetime.fromisoformat(changed_at_str)
        except Exception:
            pass

    prev = get_previous_snapshot(bucket, previous_key)
    diffs = compute_diffs(prices, prev.get('prices', [])) if prev else None

    return prices, diffs, changed_at

# Telegram Bot Commands

This file documents all currently implemented Telegram bot commands.

## Command List

### `/start`

Shows a short introduction and usage hint.

### `/help`

Shows available commands and supported fuel aliases.

Supported aliases include:

- `95`
- `95+`
- `98`
- `diesel`
- `diesel+`
- `xtl`
- `gas`
- `lpg`
- `cng`
- `e85`

### `/ping`

Health-check command. Returns `pong`.

### `/fuel`

Returns a combined comparison table for all normalized fuel types across:

- Circle K
- Neste
- Virsi
- Viada

### `/fuel <fuel_type>`

Alias for `/price <fuel_type>`.
Returns the cheapest available match across all providers.

Supported aliases include:

- `95`
- `98`
- `diesel`
- `diesel+`
- `xtl`
- `gas`
- `lpg`
- `cng`
- `e85`

### `/price <fuel_type>`

Returns the single cheapest result for the requested normalized fuel type.

Example:

```text
/price diesel
```

### `/best`

Returns the cheapest provider for each currently available fuel type.

### `/circlek`

Returns only Circle K prices.

### `/neste`

Returns only Neste prices.

### `/virsi`

Returns only Virsi prices.

### `/viada`

Returns only Viada prices.

### `/status`

Returns cache state, enabled providers, last refresh attempt, last successful refresh, the latest refresh issue if any, and last scrape result per provider.

### `/refresh`

Forces data cache refresh and returns updated comparison output.

### `/mode <compact|full|auto>`

Sets per-chat display mode.

- `compact`: concise fuel output
- `full`: full comparison output
- `auto`: group/channel -> compact, private chat -> full

### `/fav <add|remove|list|clear> <fuel>`

Manages per-chat favorite fuels used in the inline Fuel Menu.

Examples:

```text
/fav add diesel
/fav list
```

## Output Notes

- Prices are scraped from provider websites and normalized into shared fuel categories.
- If a provider does not publish a specific fuel type, it is omitted for that fuel row.
- Provider-specific commands honor the `ENABLED_PROVIDERS` configuration.
- Messages include source attribution and support credit.
- Main responses include inline shortcut buttons for quick actions (`Fuel Menu`, `Best`, `95`, `Diesel`, `Help`, `Refresh`, `Status`).
- In groups and channels, `/fuel` without arguments returns a compact snapshot by default to reduce chat noise.
- `Fuel Menu` opens a dynamic fuel list based on currently scraped data.
- Selecting a fuel opens a second inline menu with actions: best price for that fuel, all providers for that fuel, or provider-specific view.
- Fuel menu entries are sorted in a stable fuel order and can show favorite fuels first.

## Error and Fallback Behavior

- Unknown fuel alias: returns usage guidance.
- Empty scrape result: returns temporary fetch error message.
- Refresh failure: returns warning message.

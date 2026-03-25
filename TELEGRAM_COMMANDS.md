# Telegram Bot — Command Reference

Prices are scraped from **Circle K**, **Neste**, **Virsi**, and **Viada** (Latvia).

---

## The fastest way to use the bot

Most bot messages include a row of inline buttons — no slash commands needed for normal use:

| Button | What it does |
|---|---|
| ⛽ **Fuel Menu** | Opens a fuel list → pick one → choose Best / All providers / single provider |
| 🏁 **Best** | Cheapest provider for every fuel type in one view |
| **95** / **Diesel** | Cheapest price for that fuel, instantly |
| ❓ **Help** | Shows this info inside the chat |
| 🔄 **Refresh** | Forces a data refresh (subject to cooldown) |
| 📊 **Status** | Shows cache health and last scrape result per provider |

### Fuel Menu flow

```
⛽ Fuel Menu
  └─ pick a fuel (95, Diesel, LPG, …)
       └─ 🏁 Best for this fuel   — cheapest single provider
          ⛽ All providers         — all providers side by side
          Circle K / Neste / …    — one specific provider
          ⭐ Add / Remove favorite — pin this fuel to the top of the menu
          🔙 Fuel list / 🏠 Home  — navigate back
```

Fuel list order: **95 → 95 Premium → 98 → Diesel → Diesel Premium → XTL → LPG → CNG → E85**

Favorites appear first in the list, marked with ⭐.

---

## Slash commands

Slash commands are optional shortcuts.

### Prices

| Command | Output |
|---|---|
| `/fuel` | Full price comparison for all fuel types |
| `/fuel <type>` | Cheapest provider for one fuel type |
| `/price <type>` | Same as `/fuel <type>` |
| `/best` | Cheapest provider per fuel, all fuels in one message |
| `/circlek` | All prices from Circle K |
| `/neste` | All prices from Neste |
| `/virsi` | All prices from Virsi |
| `/viada` | All prices from Viada |

**Supported fuel type aliases** (case-insensitive, spaces ignored):

| You type | Resolves to |
|---|---|
| `95`, `95e`, `95miles`, `95futura` | 95 |
| `95+`, `95plus`, `95premium` | 95 Premium |
| `98`, `98e`, `98miles`, `98plus` | 98 |
| `diesel`, `d`, `dd`, `dmiles` | Diesel |
| `diesel+`, `diesel premium`, `d+`, `dmiles+` | Diesel Premium |
| `xtl`, `milesxtl` | XTL |
| `gas`, `lpg`, `autogas`, `autogāze` | LPG |
| `cng` | CNG |
| `e85` | E85 |

Example: `/price diesel+` and `/price dieselpremium` both return the cheapest Diesel Premium price.

---

### Display mode

```
/mode compact   — concise one-line-per-fuel view
/mode full      — full comparison table with all providers
/mode auto      — compact in groups/channels, full in private chat (default)
```

Preference is saved per chat and persists until changed.

---

### Favorites

Favorites appear at the top of the Fuel Menu with a ⭐. They can also be managed from the inline button inside each fuel's action menu.

```
/fav add <fuel>      — add a fuel to favorites
/fav remove <fuel>   — remove a fuel from favorites
/fav list            — show current favorites
/fav clear           — remove all favorites
```

Example: `/fav add diesel`

---

### Cache and data

| Command | Output |
|---|---|
| `/refresh` | Force-refresh scraped data, shows updated prices |
| `/status` | Cache TTL, last refresh timestamps, per-provider scrape health |
| `/ping` | Returns `pong` — quick health check |

**Refresh cooldown:** 45 seconds per chat, 20 seconds globally. Tapping 🔄 Refresh too quickly shows a countdown message instead of triggering a redundant scrape.

**Cache TTL:** 30 minutes — aligned with provider websites which update prices approximately hourly.

---

## Notes

- If a provider does not publish a specific fuel type, it is omitted for that fuel row.
- Provider-specific commands honour the `ENABLED_PROVIDERS` deployment configuration.
- All prices are displayed in **EUR (€)**.
- Timestamps are shown in **Europe/Riga** timezone.
- Source attribution and a support link are included at the bottom of every price message.
- `/ping` returns plain `pong` without shortcut buttons.
- If a provider is disabled, provider command replies are plain text without shortcut buttons.

## Error behaviour

| Situation | What you see |
|---|---|
| Unknown fuel alias | Usage hint with supported aliases |
| No data available | Inline error with prompt to tap 🔄 Refresh |
| Refresh failed but cache exists | Warning + cached prices shown |
| Refresh failed, no cache | Warning, prompt to try again |
| Internal error during inline action | Error shown in-place, shortcuts remain visible |
| Pressing the same button twice quickly | Silently ignored — message already shows the correct content |

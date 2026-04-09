# Telegram Bot — Command Reference

Prices are scraped from **Circle K**, **Neste**, **Virsi**, and **Viada** (Latvia). All prices are in **EUR (€)** and timestamps are shown in **Europe/Riga** time.

---

## The fastest way to use the bot

Most bot messages include a row of inline buttons — no slash commands needed for normal use:

| Button | What it does |
|---|---|
| ⛽ **Degviela** | Opens a fuel list → pick one → choose Cheapest / All stations / single station |
| 💰 **Lētākais** | Cheapest provider for every fuel type in one view |
| **95** / **Diesel** / **LPG** | Cheapest price for that fuel, instantly |
| ❓ **Palīdzība** | Shows help info inside the chat |
| 🔄 **Atjaunot** | Forces a data refresh (subject to cooldown) |

### Fuel menu flow

```
⛽ Degviela
  └─ izvēlies degvielu (95, Diesel, LPG, …)
       └─ [selecting a fuel shows cheapest price immediately]
          💰 Lētākais      — return to cheapest price view
          ⛽ Visas stacijas — all providers side by side
          Circle K / Neste / … — one specific provider
          ⭐ Saglabāt / Noņemt — pin this fuel to the top of the menu
          ← Degviela / 🏠 Sākums — navigate back
```

Fuel list order: **95 → 95 Premium → 98 → Diesel → Diesel Premium → XTL → LPG → CNG → E85**

Favorites appear first in the list, marked with ⭐.

### Price change indicators

All price views show ▲/▼ indicators next to prices that have changed since the last detected price update:

```
Diesel: Circle K €1.459 ▼ 0.010 💰
```

The footer shows `📅 Mainījās: šodien 09:15` — the exact time prices last changed. This feature requires the S3 snapshot setup described in README.md.

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

### Favorites

Favorites appear at the top of the Fuel Menu with a ⭐. They can also be managed from the inline button inside each fuel's action menu.

```
/fav add <fuel>      — add a fuel to favorites
/fav remove <fuel>   — remove a fuel from favorites
/fav list            — show current prices for all saved favorites
/fav clear           — remove all favorites
```

Example: `/fav add diesel`

---

### Cache and data

| Command | Output |
|---|---|
| `/refresh` | Force-refresh scraped data, shows updated prices |

Note: `/ping` and `/status` are internal diagnostics commands and are disabled for public users by default.

**Refresh cooldown:** 45 seconds per chat, 20 seconds globally. Tapping 🔄 Atjaunot too quickly shows a countdown message instead of triggering a redundant scrape.

**S3 snapshot refresh:** When EventBridge is configured, prices are fetched from the S3 snapshot (written by the scheduled Lambda trigger) rather than scraped live on every user request. Scheduled updates support EventBridge Rule and Scheduler payload variants (including empty no-body scheduler events). The webhook Lambda falls back to a live scrape only if the snapshot is missing or older than 3 hours.

---

## Notes

- If a provider does not publish a specific fuel type, it is omitted for that fuel row.
- Provider-specific commands honour the `ENABLED_PROVIDERS` deployment configuration.
- All prices are displayed in **EUR (€)**.
- Timestamps are shown in **Europe/Riga** timezone.
- The footer credit/support text comes from the `CREDIT_MESSAGE` environment variable.
- If `CREDIT_MESSAGE` is unset, the built-in default support line is used.
- If `CREDIT_MESSAGE` is set to an empty string, the footer credit is omitted.
- If a provider is disabled, provider command replies are plain text without shortcut buttons.

## Error behaviour

| Situation | What you see |
|---|---|
| Unknown fuel alias | Usage hint with example (`/price diesel`) |
| No data available | Inline error with prompt to tap 🔄 Atjaunot |
| Refresh failed but cache exists | Warning + cached prices shown |
| Refresh failed, no cache | Warning, prompt to try again |
| Internal error during inline action | Error shown in-place, shortcuts remain visible |
| Pressing the same button twice quickly | Silently ignored — message already shows the correct content |

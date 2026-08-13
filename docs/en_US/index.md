# Hoymiles Cloud — Documentation (EN)

Jeedom plugin to monitor **Hoymiles microinverters** (HMS-xxx-WB/T) through the **S-Miles cloud**.

- **Realtime** : burst ~2-3 s (same endpoints as the official S-Miles app)
- **No local hardware** : works even if the local BLE/WiFi gateway is offline
- **Multi-inverter** : station + all inverters on the account

---

## 1. Requirements

- Jeedom ≥ 4.4 (tested on 4.6)
- An **S-Miles account** (from the S-Miles Home or S-Miles Cloud app) with your inverters already linked
- Python 3 + `venv` (installed automatically via the **Dependencies** button)

## 2. Installation

1. **Market** : `Plugins → Plugins management → Market` → search **Hoymiles Cloud** → **Install**
2. Enable : `Plugins → Energy → Hoymiles Cloud` → **Enable**
3. **Dependencies** : click the **Dependencies** button (state becomes *OK* once the Python venv is built) — or let the automatic install run

> Manual install : download the zip from GitHub, extract to `plugins/hoymilescloud/` on your Jeedom server, then enable the plugin.

## 3. Configuration

`Plugins → Energy → Hoymiles Cloud → Configuration`

| Field | Description |
|---|---|
| **S-Miles email** | Your S-Miles account identifier (e.g. email address) |
| **Password** | S-Miles account password (encrypted by Jeedom) |
| **Change threshold** | Minimum difference (W, Wh, %, value) before pushing a value to Jeedom — 1 by default |

### Steps

1. Fill in **Email** and **Password**
2. **Test connection** → should show "Connected" with the station name
3. **Sync equipment** → automatically creates:
   - the **Station** (named after your S-Miles station)
   - one device per **inverter** (named model + serial number)
4. **Start the daemon** (plugin status page) → values are pushed in realtime

## 4. Devices and commands

### Station (e.g. "Mon domicile")

| LogicalId | Name | Unit | Description |
|---|---|---|---|
| `real_power` | Instant power | W | Total AC power of the station (realtime, burst) |
| `today_eq` | Today production | Wh | Energy produced today |
| `month_eq` | Month production | Wh | Energy this month |
| `total_eq` | Total production | Wh | Cumulative energy |
| `year_eq` | Year production | Wh | Energy this year |
| `self_rate` | Self-consumption | % | Self-consumption rate |
| `co2` | CO₂ avoided | g | Avoided emissions |
| `online` | Online | binary | 1 if the station is online |
| `last_data_time` | Last data | date | Timestamp of the latest data report |

### Inverter (e.g. "HMS-1000-2WB (1610A38B34D5)")

| LogicalId | Name | Unit | Description |
|---|---|---|---|
| `pac` | AC power | W | Inverter output power |
| `p1` / `p2` / `p3` / `p4` | PV 1..4 | W | Power per PV port (2 ports on HMS-1000) |
| `connect` | Connected | binary | 1 if the inverter is responding (warn_data.connect) |
| `up1` / `up2` | PV port 1/2 voltage | V | Panel DC voltage (5-min bucket) |
| `ip1` / `ip2` | PV port 1/2 current | A | Panel DC current (5-min bucket) |
| `uac` | Grid voltage | V | AC voltage (5-min bucket) |
| `freq` | Grid frequency | Hz | AC frequency (5-min bucket) |
| `temp` | Inverter temperature | °C | Internal case temperature (5-min bucket) |
| `warn` | Alarm | binary | 1 if the inverter reports an issue (warn_data.warn) |
| `soft_ver` | Firmware version | text | Firmware version (info only) |

> Commands can be renamed, moved into your rooms, and used in **virtuals**, **scenarios**, **widgets** and **designs** like any Jeedom command.

## 5. How it works

- **Authentication** : Argon2id v3 (S-Miles Home profile, `euapi.hoymiles.com`) — same mechanism as the official app
- **Realtime** : `data/burst` endpoints (`m:0` = station, `m:3` = inverters) at the server-paced cadence (~1.5-3 s)
- **Energies/status** : `count_station_real_data` every 60 s
- **Smart push** : a value is pushed only when it changes by more than the configured threshold (keeps history lean)
- **Resilience** : after 3 burst failures, fallback to polling with exponential backoff; re-login only when the token expires; auto-supervision via cron15
- **Security** : credentials never leave your server (the daemon reads them from the encrypted Jeedom config)

## 6. FAQ / Troubleshooting

### "Connection failed" on test
- Check your S-Miles email + password
- **Anti-bruteforce cooldown** : after ~3-4 rapid login attempts, S-Miles temporarily refuses (~5-10 min). Wait and retry.

### Daemon runs but energies don't change
- The `count_station_real_data` endpoint applies a **silent rate limit** after calls that are too frequent from the same IP : the daemon logs a warning and retries on the next cycle (60 s). Realtime power is never affected.
- Check `log/hoymilescloud_daemon` (Settings → Logs) : "Slow poll: empty response" indicates the rate limit.

### Plugin page shows "No matching method"
- Clear the Jeedom cache (`Settings → System → Cache`) after a plugin update.

### Is this plugin affiliated with Hoymiles?
No — independent community project. Hoymiles / S-Miles trademarks belong to their owners.

## 7. Known limitations

- **Control** (power limit, shutdown) : not exposed in this version (read-only API). An official control API exists but is not integrated yet.
- **Cloud history** : long statistics (15 days per inverter) require the official API key (wapi.hoymiles.com) — planned for a later version.
- The S-Miles app and this plugin share the same account : concurrent sessions are tolerated.

---

*Community project, not affiliated with Hoymiles. AGPL-3.0 license.*

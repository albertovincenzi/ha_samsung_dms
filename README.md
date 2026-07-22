# Samsung DMS — Home Assistant integration

A local-polling [Home Assistant](https://www.home-assistant.io/) integration for
the **Samsung DMS2.5** (Data Management Server), the on-site controller for
Samsung DVM air-conditioning systems. Each indoor unit is exposed as a
`climate` entity — no cloud, no account, everything over the LAN.

Tested against DMS firmware `2.9.1.11`.

## Features

- Auto-discovers every unit reported by the controller and maps it to the
  right Home Assistant platform, using the room labels configured on the DMS
- **Indoor AC units → `climate`**
  - Power on/off
  - HVAC modes: cool, heat, dry, fan-only, auto
  - Fan speed: auto / low / medium / high
  - Target temperature (per-mode limits respected)
  - Room temperature readout
  - Error, filter-warning, remote-lock and schedule attributes
- **EHS / hydro units → `water_heater`** (domestic hot water)
  - On/off, supply modes (standard / power / force)
  - Tank target & current temperature (tank limits respected)
  - Away mode (the DMS "go out" flag)
- **Energy-recovery ventilators (pluserv) → `fan`**
  - On/off, fan speed (low / mid / high / turbo)
  - Ventilation mode as preset (auto / erv / normal / sleep)
- Session auto-recovery (re-login on cookie expiry)

## Installation

### HACS (custom repository)

1. HACS → Integrations → ⋮ → *Custom repositories*.
2. Add this repo, category **Integration**.
3. Install **Samsung DMS**, then restart Home Assistant.

### Manual

Copy `custom_components/samsung_dms/` into your HA `config/custom_components/`
directory and restart.

## Configuration

Settings → Devices & Services → **Add Integration** → *Samsung DMS*.

| Field | Notes |
|-------|-------|
| Host | The DMS IP, e.g. `192.168.1.5` |
| Username | Usually `admin` |
| Password | Your DMS password |
| Verify SSL | Leave **off** — the DMS ships a self-signed certificate |

## How it talks to the DMS

The DMS web UI drives an XML-over-POST API that replies with JSON. This
integration speaks the same protocol directly.

**Auth** — `GET /dms2/` mints a `JSESSIONID` cookie, then a form POST to
`/dms2/Login.jsp` with `userId`, `password`, and `securedUsername` /
`securedPassword` (the credentials with the session id appended).

**Every request** is a raw body of `"<uuid>:<xml>"` sharing this header:

```xml
<root>
  <header sa='web' da='dms' messageType='request'
          dateTime='YYYY-MM-DDTHH:MM:SS:mmm' dvmControlMode='individual'/>
  ...payload...
</root>
```

**Read state** — `POST /dms2/getMonitoring?currentPage=main` with
`<getMonitoring><all/></getMonitoring>` returns every unit's `power`, `opMode`,
`setTemp`, `roomTemp`, `fanSpeed`, swing flags and temperature limits.

**Control** — same endpoint, payload:

```xml
<setDeviceControl><controlList><control>
  <controlValue><power>on</power><operationMode>cool</operationMode></controlValue>
  <addressList><address>11.00.08</address></addressList>
</control></controlList></setDeviceControl>
```

`<controlValue>` tags: `power` (on/off), `operationMode`
(cool/heat/dry/fan/auto), `fanSpeed` (low/mid/high/auto), `setTemp`,
`airSwing_UD` / `airSwing_LR`, `remocon` (remote-control lock). Multiple
`<address>` entries apply the command to several units at once.

## Not yet implemented

- The space-heating (water-out) side of EHS units as a separate `climate`
  entity (currently only the domestic-hot-water side is exposed)
- Vertical/horizontal swing controls
- Schedules and use-restriction (remote lock) as switches

## Disclaimer

Community project, not affiliated with Samsung. Use at your own risk.

# Samsung DMS2.5 — Local API Findings & Usage Guide

**Device:** Samsung DMS2.5 (DVM AC central controller), branded **"GardaRelais"**
**Firmware:** 2.9.1.11
**Address:** `https://192.168.1.5` (HTTPS/443, self‑signed cert)
**Login:** admin account — credentials kept **out of this repo** (see your password manager / HA config).
**Scope:** Reverse‑engineered local HTTP API — the same one the DMS web UI uses. This is the basis for the `custom_components/samsung_dms` Home Assistant integration.

> This document merges what was reverse‑engineered while building the integration with a **live dump captured 2026‑07‑22** (all 30 units + 4 outdoor units read end‑to‑end, plus the authenticated web‑UI menu crawled for the full feature map). Live‑verified facts are called out as such.

---

## 1. TL;DR — what the DMS is and what you get

The DMS is a small embedded web server (Jetty/JSP) that fronts the whole DVM/VRF refrigerant network over a serial bus. Through one HTTP endpoint you can **read live state and telemetry for every unit** and **control them**:

- **~30 indoor AC units** across 3 refrigerant systems (`11.00.xx`, `12.01.xx`, `13.05.xx`) — power, mode, setpoint, room temp, fan, vanes, fault/filter flags.
- **1 EHS / hydro unit** (`13.06.00`) — domestic hot water **and** space‑heating (leaving‑water) control.
- **1 ERV / energy‑recovery ventilator** (`12.01.09`) — ventilation mode + fan speed, CO₂ and air temperatures (read‑only tempering status).
- **4 outdoor condensing units** — 3 VRF condensers (`11.00.00`, `12.01.00` "Impianto 2", `13.05.00` "Impianto 3") + 1 EHS mono (`13.06.00` "ACS Palazzo", model *EHS MONO LOWTEMP*). Full **cycle/refrigerant telemetry** plus an **internal energy‑meter estimate** (`outdoorAccumPowerMeterValue`). This is the richest and most under‑used data on the box.

Everything is one account (`admin`), one serial gateway, no cloud. If HA can talk to it, so can any script on the LAN.

### Live topology (2026‑07‑22)
28 indoor units (10 ducted, 18 wall/RAC) named by hotel room, + 1 ERV ("Recuperatore") + 1 EHS ("ACS"), across 4 refrigerant systems:

| System | Outdoor | Units |
|---|---|---|
| `11.00.xx` | 11.00.00 (unnamed) | 201, 202, Guido, Colazioni 1, 302, 304, 303, 301, Reception |
| `12.01.xx` | 12.01.00 "Impianto 2" | Colazioni 2, 101–104, 401–404, **ERV "Recuperatore"** (12.01.09) |
| `13.05.xx` | 13.05.00 "Impianto 3" | Cucina/Camera 503/505/507, 501, 502, 504, 506 |
| `13.06.xx` | 13.06.00 "ACS Palazzo" | **EHS "ACS"** (13.06.00) — DHW + space heating |

---

## 2. The password‑case gotcha (read this first)

> 🔒 **Credentials are intentionally omitted from this repo — never commit the username or password.** Supply them at runtime via environment variables (`DMS_USER` / `DMS_PASS`) or your secrets store.

The login is **case‑sensitive**, *including the first character of the password* — the correct value is not all‑lowercase. Using the wrong case returns a generic `alert("Accesso non riuscito.")` → `main/loginError.jsp`, after which every data servlet answers **401 `loginError.jsp` ("Accesso richiesto.")**. There is no "wrong password" vs "locked out" vs "session busy" distinction in the message — it's the same generic failure for all of them, which makes a wrong‑case password look like a lockout. It isn't: the DMS accepts multiple concurrent logins fine (HA + a script + a browser can all be logged in at once).

**Login success detection gotcha:** the *failure* page also contains the string `main.jsp` (inside a `goMainPage()` helper), so testing "`main.jsp` in body" gives a false positive. Test instead for the **absence** of `Accesso non riuscito` / `loginError`.

Everything below marked "live" was captured 2026‑07‑22 with the correct password: all 30 indoor/EHS/ERV units + 4 outdoor units read end‑to‑end, and the authenticated web‑UI menu crawled for the feature map in §9.

---

## 3. Transport / wire format

| Property | Value |
|---|---|
| Protocol | HTTPS on 443, self‑signed cert → **TLS verification must be off** |
| Cookies | `JSESSIONID`; for a bare‑IP host, aiohttp needs `CookieJar(unsafe=True)` |
| Request body | `"<uuid4>:<xml>"` — a UUID, a colon, then the XML document |
| Response body | **JSON** (despite the request being XML) |
| Shared XML header | `<header sa='web' da='dms' messageType='request' dateTime='YYYY-MM-DDTHH:MM:SS:mmm' dvmControlMode='individual'/>` |
| Envelope | `<?xml version='1.0' encoding='utf-8' standalone='yes'?><root>{header}{payload}</root>` |
| Invalid‑value sentinel | `-1000` (temps), `-999`/`-1000` treated as "not available" |

Reads *and* writes both hit the **same** monitoring URL.

---

## 4. Authentication (exact flow)

The client‑side RSA path is **commented out** in the device's `login.js`/inline JS ("https 지원하기 때문에 RSA 암호화 제거" — "RSA removed because HTTPS is supported"). The real scheme, straight from the page:

```
securedUsername = userId   + getSessionId()
securedPassword = password + getSessionId()
getSessionId()  = the raw JSESSIONID cookie value
```

**Flow:**
1. `GET /dms2/` → sets a `JSESSIONID` cookie.
2. `POST /dms2/Login.jsp` (form‑urlencoded) with (`$USER`/`$PASS` from your secrets, not hardcoded):
   - `userId=$USER`
   - `password=$PASS`
   - `securedUsername=$USER<JSESSIONID>`
   - `securedPassword=$PASS<JSESSIONID>`
3. **Success** → redirects to `main.jsp`. **Failure** → `alert("Accesso non riuscito.")` and `loginError.jsp`.
   - ⚠️ Do *not* test success by "`main.jsp` in body" — the failure page also contains that string (it's in a `goMainPage()` helper). Test for the *absence* of `Accesso non riuscito` / `loginError`.

Credential validation the UI enforces (mirror it to avoid silent rejects): `admin` password 6–12 chars, `[A-Za-z0-9]`. Session expiry re‑serves the login page on data calls (HTTP 200 with `Login.jsp` HTML, or a 401 `loginError.jsp` from the servlet) — re‑login and retry once.

---

## 5. Endpoints

| Endpoint | Purpose | Request payload |
|---|---|---|
| `GET /dms2/` | mint `JSESSIONID` | — |
| `POST /dms2/Login.jsp` | authenticate | form fields (§4) |
| `POST /dms2/getMonitoring?currentPage=main` | **read all indoor/EHS/ERV state** | `<getMonitoring><all/></getMonitoring>` |
| `POST /dms2/getMonitoring?currentPage=main` | **control** (same URL!) | `<setDeviceControl>…</setDeviceControl>` (§6) |
| `POST /dms2/getTreeView?currentPage=main` | device hierarchy + labels/models | `<treeInfoEx range='all'/>` |
| `POST /dms2/getControlMonitring` | **outdoor cycle/refrigerant telemetry** (note Samsung's typo — *not* "Monitoring") | `<getCycleMonitoring><outdoorList><outdoor addr='..'/></outdoorList><indoorList/></getCycleMonitoring>` |

### 5.1 `getMonitoring` response shape
```json
{ "indoorList": [ { "addr": "11.00.01", "nodeName": "...",
                    "child": [ { ...indoorDetail... } ] }, ... ] }
```
Flatten `indoorList[i].child[0]` and keep `addr`.

### 5.2 `getTreeView` response
- `treeIndoor[]` — **reliable** per‑address metadata: `name`, `subIndoorType` (`rac`/`duct`/`ehs`/…), `indoorType` (`indoor`/`ehs`/`pluserv`), `modelCode`, `version`.
- `treeOutDoor[]` — outdoor unit addresses.
- `treeViewName` — order‑dependent, **unreliable**; don't parse it for names.

### 5.3 `getControlMonitring` response
```json
{ "outdoorList": [ { ...outdoor..., "child":[ { "child":[ { ...unitDetail... } ] } ] } ],
  "commErrorList": [ {"addr": "..."} ],   // empty = no comm errors
  "indoorList": [] }
```
Descend `outdoor → child[0] → child[0]` for the compressor `unitDetail`.

---

## 6. Control surface (writable tags)

Control POSTs go to `getMonitoring` with:
```xml
<setDeviceControl><controlList><control>
  <controlValue>{one or more tags}</controlValue>
  <addressList><address>11.00.01</address> … </addressList>
</control></controlList></setDeviceControl>
```
- **Multiple `<address>`** = one command to many units (batch).
- **Multiple tags** in one `<controlValue>` = applied together (e.g. power + mode).

### 6.1 Indoor AC
| Action | Control tag(s) | Values |
|---|---|---|
| Power | `power` | `on` / `off` |
| Mode | `operationMode` | `cool` `heat` `dry` `fan` `auto` |
| Setpoint | `setTemp` | e.g. `24.0` |
| Fan | `fanSpeed` | `low` `mid` `high` `auto` (`turbo` on some) |
| Vanes | `airSwing_UD`, `airSwing_LR` | `true` / `false` (send both together) |
| Remote lock | `remocon` | `true` (enabled) / `false` (locked) |

### 6.2 EHS / hydro (`13.06.00`)
| Action | Control tag | Read‑back key |
|---|---|---|
| DHW power | `hotWaterSupplyPower` | same |
| DHW mode | `hotWaterSupplyMode` | `standard` / `power` / `force` |
| DHW setpoint | `setHotWaterSupplyTemp` | same |
| Away ("go out") | `goOut` | `on` / `off` |
| Space‑heat setpoint (leaving water) | `setWaterOutTemp` | **`waterOutSetTemp`** |
| Space‑heat power/mode | `power` / `operationMode` | `opMode` |

### 6.3 ERV / ventilation (`12.01.09`)
| Action | Control tag | Values |
|---|---|---|
| Power | `power` | `on` / `off` |
| Ventilation mode | `ventilationMode` | `auto` `erv` `normal` `sleep` |
| Ventilation fan | `ventilationFanSpeed` | `low` `mid` `high` `turbo` |

> The ERV's `opMode`/`setTemp` are **read‑only** status (they mirror the connected circuit's cool/heat tempering); its panel "mode" buttons actually send `ventilationMode`.

### 6.4 Control‑tag vs monitoring‑key mismatches (gotcha)
The value you POST is read back under a **different** key for these. This matters for optimistic UI:

| Control tag (write) | Monitoring key (read) |
|---|---|
| `operationMode` | `opMode` |
| `remocon` | `remoconEnable` |
| `setWaterOutTemp` | `waterOutSetTemp` |

All others match (`power`, `setTemp`, `fanSpeed`, `airSwing_UD/LR`, `hotWaterSupplyPower/Mode`, `setHotWaterSupplyTemp`, `goOut`, `ventilationMode`, `ventilationFanSpeed`).

**Write lag:** the DMS reflects a command a few seconds after it's issued — an immediate re‑poll returns stale state. The integration overlays an optimistic value for up to 60 s and re‑polls at +4 s and +10 s to confirm. Replicate this if you build your own controller, or you'll think commands "didn't take".

---

## 7. Data model — every field the DMS exposes

### 7.1 Indoor unit (`getMonitoring` → indoorDetail)
| Field | Meaning |
|---|---|
| `power` | `on` / `off` |
| `opMode` / `useMode` | active mode `cool`/`heat`/`dry`/`fan`/`auto` |
| `setTemp` | target °C |
| `roomTemp` | measured room °C |
| `fanSpeed` | `low`/`mid`/`high`/`auto` |
| `airSwing_UD`, `airSwing_LR` | vane state (`null` = no vane fitted) |
| `useLRSwing` | left/right vane capability (`true`/`false`) |
| `useCoolMode`, `useHeatMode` | which modes the unit allows |
| `minTempCool/Heat/Dry/Auto`, `maxTemp…` | per‑mode setpoint limits |
| `error` | fault flag (`true`/`false`) |
| `filterWarning` | filter‑cleaning due (`true`/`false`) |
| `remoconEnable` | wall remote state: `true`/`false`/`level1` |
| `isScheduled` | a DMS schedule is attached (`true`/`false`) |

### 7.2 EHS / hydro extra fields (128 fields live)
Core: `currentHotWaterSupplyTemp`, `setHotWaterSupplyTemp`, `minTempTank`, `maxTempTank`, `hotWaterSupplyPower`, `hotWaterSupplyMode`, `goOut`, `waterInTemp`, `waterOutCurrentTemp`, `waterOutSetTemp`, `waterOutHeat/CoolLowerBound`, `waterOutHeat/CoolUpperBound` (+ full `*LowerMax/Min` / `*UpperMax/Min` envelopes and `waterTankHeat*Bound`).
Live extras worth surfacing: `backupHeater`, `boosterHeater`, `thermostat1`/`thermostat2`/`dhwThermostat` (external stat inputs), `dhwValve`, `solarPumpInput` (solar thermal), `smartGrid` (**SG‑Ready** input), `controlTempType` (`waterOut`), `useWaterTankCool`, `useEHSForceMode`/`useEHSPowerMode`, `accumPowerOnTime`/`accumThermoOnTime` (runtime hours).

### 7.3 ERV extra fields (69 fields live)
`ventilationMode`, `ventilationFanSpeed`, `co2Sensor` (ppm), `ervPlusOutdoorTemp`, `evaInhaleTemp` (intake °C), `evapInTemp`/`evapOutTemp` (heat‑exchanger temps), `autoMode` (`autoCool`/…), capability bitmasks `ervOpModeAbleFunction`/`fanSpeedAbleFunction`, plus read‑only `opMode`/`setTemp` tempering status.

### 7.3b Indoor extras the integration does NOT use yet (85 fields live)
The indoor payload is far richer than the climate entity exposes. High‑value unused fields:
| Field | Meaning / use |
|---|---|
| `accumPowerOnTime`, `accumThermoOnTime` | **per‑room runtime hours** (power‑on vs actively heating/cooling) — usage & energy proxy |
| `evapInTemp`, `evapOutTemp`, `eev` | **per‑indoor coil temps + EEV step** — refrigerant health at the unit, catch a stuck valve/blocked coil per room |
| `upperTemperature`, `lowerTemperature`, `*TemperatureLimit`, `isTempLimited`, `useOpModeLimit` | **setpoint guardrails** — the range a guest's remote is allowed (e.g. 20–26 °C). Hotel‑critical |
| `useVacancyControl`, `vacancyStatus` | **vacancy control** — key‑card / occupancy‑driven setback |
| `humanSensor`, `useHumanSensor` | PIR occupancy (where the indoor unit has the sensor) |
| `autoCoolSetTemp`, `autoHeatSetTemp` | **dual setpoints** for AUTO mode (heat/cool deadband) |
| `dischargeCurrentTemp`, `dischargeCoolSetTemp`, `useDischargeSetTemp`, `dischargeTempControl` | supply‑air (discharge) temperature + its control mode (ducted units) |
| `defrostOn` | defrost cycle active |
| `peakStatus` | under peak/demand limiting right now |
| `useAutoClean`, `useSleep`, `usePurity`, `useHumidification`, `useStillAir`, `useSpi`, `useOaIntake` | per‑model feature‑capability flags |
| `fanSpeedAbleFunction` | bitmask of fan speeds the unit actually supports |
| `modelCode`, `capaCode`, `absoluteCapaCode`, `mcuInfo` | model / capacity / firmware identifiers |

### 7.4 Outdoor / VRF cycle (`getControlMonitring` → unitDetail) — the goldmine
| Field | Meaning | Unit |
|---|---|---|
| `comp1` | compressor running | bool |
| `compCurrentFrequency1` | compressor speed | Hz |
| `ct1` | compressor current | A |
| `highPressure` / `lowPressure` | gauge pressures | kgf/cm² |
| `dischargeTemp1` | compressor discharge | °C |
| `suctionTemp` | suction line | °C |
| `condOutTemp` | condenser outlet | °C |
| `outsideTemp` | ambient | °C |
| `ipm1` | inverter (IPM) module | °C |
| `accumComp1OnTime` | compressor run hours | h |
| `eev` / `eviEev` | electronic expansion valve position | steps |
| `fanStep` | outdoor fan step | — |
| `fourWayValve` | reversing‑valve state (heat/cool) | — |
| `condOutTemp`, `evaInTemp`, `topSensor1`, `twTemp1`/`twTemp2` | condenser/heat‑exchanger/tank‑water temps | °C |
| `compDesiredFrequency1` | target compressor speed | Hz |
| `operatingCapa`, `outdoorCapacity` | current load / rated capacity | — |
| `hotGasValve`, `eviBypassValve`, `liquidBypassValve`, `mainCoolingValve`, `fourWayValve` | refrigerant valve states | — |
| `modelName` | e.g. *EHS MONO LOWTEMP* | — |
| `commErrorList` | bus comm errors | — |

**Outdoor top‑level (per unit, live) — energy & capacity:**
| Field | Meaning |
|---|---|
| `outdoorAccumPowerMeterValue` | **cumulative energy** (internal estimate; e.g. `1.27e7`) |
| `outdoorOneMinPowerMeterValue` | **instantaneous power** (1‑min, e.g. `25.0`) |
| `heatingCapa`, `sumCoolingCapa`, `totalIndoorCapa` | delivered/connected capacity |
| `currentRestriction`, `ableCurrentRestriction` | demand‑limit setting |
| `operationStatus`, `outdoorUnitCount`, `outdoorMaster` | status / topology |

> ⚠️ These power values are an **internal estimate** — a dedicated external meter (SIM/PIM module) is **not installed** (`PowerMeterServlet` returns *"Nessuna SIM/PIM esistente"*). Good enough for trending, not billing‑grade.

**Derived engineer's metrics** the integration computes from the above (R410A P‑T curve), which you can reproduce:
- **Condensing / evaporating temperature** — saturation temp from high/low pressure.
- **Condenser approach** = condensing temp − ambient → **dirty‑coil / airflow indicator** (warn ≥16 K, alert ≥24 K).
- **Suction superheat** = suction − evaporating temp → floodback (low) / charge‑or‑EEV (high) hint. Coarse on VRF (mixed return gas), only extremes are actionable.
- **Discharge / IPM overheat** thresholds (discharge warn 95 °C / alert 110 °C; IPM warn 80 / alert 90).
- Health verdict `ok`/`warning`/`alert` with hysteresis (only escalates at steady compressor speed ≥25 Hz).

---

## 8. Ready‑to‑use recipes (bash/curl)

> Set `DMS_USER`/`DMS_PASS` in your environment first (§2 — mind the case). `-k` accepts the self‑signed cert; `-c/-b` persist cookies.

```bash
BASE=https://192.168.1.5
JAR=/tmp/dms.cookies
# Supply credentials from your environment — do NOT hardcode them:
#   export DMS_USER=admin DMS_PASS='...'   (mind the case!)
: "${DMS_USER:?set DMS_USER}"; : "${DMS_PASS:?set DMS_PASS}"

# 1) session cookie
curl -sk -c "$JAR" "$BASE/dms2/" -o /dev/null
SID=$(awk '/JSESSIONID/{print $7}' "$JAR")

# 2) login
curl -sk -c "$JAR" -b "$JAR" "$BASE/dms2/Login.jsp" \
  --data-urlencode "userId=$DMS_USER" \
  --data-urlencode "password=$DMS_PASS" \
  --data-urlencode "securedUsername=$DMS_USER$SID" \
  --data-urlencode "securedPassword=$DMS_PASS$SID" -o /tmp/login.html
grep -q 'Accesso non riuscito\|loginError' /tmp/login.html && echo "LOGIN FAILED" || echo "LOGIN OK"

hdr="<header sa='web' da='dms' messageType='request' dateTime='$(date +%Y-%m-%dT%H:%M:%S:000)' dvmControlMode='individual'/>"
env() { echo "$(uuidgen):<?xml version='1.0' encoding='utf-8' standalone='yes'?><root>${hdr}$1</root>"; }

# 3) read everything (indoor/EHS/ERV)
curl -sk -b "$JAR" "$BASE/dms2/getMonitoring?currentPage=main" \
  --data "$(env '<getMonitoring><all/></getMonitoring>')" | python3 -m json.tool > /tmp/monitoring.json

# 4) device tree (names/models + outdoor addrs)
curl -sk -b "$JAR" "$BASE/dms2/getTreeView?currentPage=main" \
  --data "$(env "<treeInfoEx range='all'/>")" | python3 -m json.tool > /tmp/tree.json

# 5) outdoor cycle telemetry (note the endpoint typo)
curl -sk -b "$JAR" "$BASE/dms2/getControlMonitring" \
  --data "$(env "<getCycleMonitoring><outdoorList><outdoor addr='11.00.00'/><outdoor addr='12.01.00'/><outdoor addr='13.05.00'/><outdoor addr='13.06.00'/></outdoorList><indoorList/></getCycleMonitoring>")" \
  | python3 -m json.tool > /tmp/cycle.json

# 6) CONTROL example — set 11.00.01 to cool @ 24°, medium fan (verify on a test unit first!)
curl -sk -b "$JAR" "$BASE/dms2/getMonitoring?currentPage=main" \
  --data "$(env '<setDeviceControl><controlList><control><controlValue><power>on</power><operationMode>cool</operationMode><setTemp>24.0</setTemp><fanSpeed>mid</fanSpeed></controlValue><addressList><address>11.00.01</address></addressList></control></controlList></setDeviceControl>')"
```

Python: the integration's own client at `custom_components/samsung_dms/api.py` (`SamsungDMSClient`) is a clean, reusable async implementation — import it directly for scripting (it needs `aiohttp` + a `CookieJar(unsafe=True)` and TLS off).

---

## 9. Using it "as much as possible" — ideas beyond the current integration

**Already covered by the integration:** climate (indoor + EHS space heating), water_heater (DHW), fan (ERV), remote‑lock switch, per‑unit fault/filter/schedule binary sensors, ERV CO₂/temp sensors, full outdoor telemetry + derived VRF health diagnostics.

**High‑value additions you could build straight from data already in `getMonitoring`/`getControlMonitring` (no new endpoints needed):**
1. **Per‑room energy / runtime analytics** — every indoor unit reports `accumPowerOnTime` and `accumThermoOnTime` (runtime hours); every outdoor unit reports `outdoorAccumPowerMeterValue` (cumulative kWh estimate) + `outdoorOneMinPowerMeterValue` (instant). Feed these to HA `utility_meter`/statistics for per‑room usage and per‑system consumption — no external meter required.
2. **Predictive maintenance** — condenser‑approach trend per outdoor = coil‑fouling clock; discharge/IPM temps flag failing inverters/low charge; now also **per‑indoor** `evapInTemp`/`evapOutTemp`/`eev` catch a stuck EEV or blocked coil at the individual room.
3. **Guest setpoint guardrails** — `upperTemperature`/`lowerTemperature` + `isTempLimited`/`useOpModeLimit` are already enforced per unit; expose/adjust them so guest remotes can't run rooms to 16 °C or 30 °C (the web UI page for this is `indoorUseLimit.jsp`).
4. **Occupancy / vacancy control** — `useVacancyControl`/`vacancyStatus` (+ `humanSensor` where fitted) already exist; wire them to key‑card/PMS check‑in‑out, or just batch `power=off` to a system's whole address list at checkout, and lock remotes (`remocon=false`) in vacant rooms.
5. **CO₂‑driven ventilation** — drive `ventilationFanSpeed`/`ventilationMode` on the ERV from its own `co2Sensor` reading.
6. **DHW / EHS smarts** — schedule `hotWaterSupplyMode=power/force` windows + `goOut`; surface `backupHeater`/`boosterHeater` runtime and the `smartGrid` (SG‑Ready) + `solarPumpInput` states for solar/tariff‑aware heating.
7. **Fault dashboard** — one board off `error`, `filterWarning`, `commErrorList`, and outdoor `health_status`.

### Full DMS feature map (from the authenticated web‑UI menu)
The web UI exposes much more than the 3 clean JSON endpoints — but those extra features are **form‑driven JSP pages**, not tidy APIs. If you want to automate them you'll POST to these pages (capture the exact form/XML from DevTools → Network while using each screen). What exists:

| Area | Pages | Notes |
|---|---|---|
| **Power / energy** | `poweruse/powerMeter.jsp`, `powerUseResult.jsp`, `indoorRunningTime.jsp`, `powerUseCalculation.jsp`, `energy/EnergyList.jsp` | `PowerMeterServlet?action=view` is the one real servlet — but returns *"Nessuna SIM/PIM esistente"* (no external meter module fitted). Use the cycle‑monitoring power estimate instead (§7.4). |
| **Schedules** | `schedule/ScheduleList.jsp`, `ScheduleRegistering.jsp`, `EhsScheduleRegistering.jsp`, `ScheduleHistoryViewer.jsp` | weekly/holiday programs; XML message types `watchSchedule`/`newSchedule`/`modifySchedule`/`deleteSchedule`. Units already report `isScheduled`. |
| **Error history** | `controlmonitoring/ErrorHistoryList.jsp` | full fault log (beyond the live `error` flag). |
| **Use limits** | `controlmonitoring/indoorUseLimit.jsp` | setpoint/mode guardrails (`upperTempLimit_`/`lowerTempLimit_`/`operationModeLimit_`). |
| **Vacancy** | `controlmonitoring/vacancyControl.jsp` | occupancy‑driven setback. |
| **Cycle / outdoor** | `controlmonitoring/CycleMonitoring.jsp`, `outdoorControl.jsp`, `IndoorControlLogViewer.jsp` | the cycle data is already the `getControlMonitring` JSON. |
| **Control logic** | `controllogic/controlLogicList.jsp`, `controlLogicHistory.jsp` | on‑device automation rules. |
| **Zones** | `zonemanagement/ZoneManagement.jsp`, `ahuZoneList.jsp` | grouping. |
| **System** | `systemsetting/Tracking_NASA.jsp` (bus device tracking), `AutoChangeOverSetting.jsp`, `DMSEventManagement.jsp`, `UserList.jsp`/`UserAcl.jsp`, `RMSConfiguration.jsp`, `BackupAndRestore/DMSBackupManagement.jsp` | admin/config. |
| **Graphics** | `graphics/GraphicsEditor.jsp` | floor‑plan editor. |

The AJAX plumbing is a shared `requestAjax()` helper (`getXmlHttpRequest`) in `mainUI.js`; most feature pages just `document.<form>.submit()` to their JSP with query/form params.

---

## 10. Safety notes (live hotel system)

- **Never commit or hardcode the credentials** — this repo intentionally omits them; pass them via env/secrets at runtime (§2, §8).
- **Concurrent sessions are fine** — HA, a script, and a browser can all be logged in at once; the DMS does not enforce a single seat. (The earlier "it's locked/single‑session" symptom was only a wrong‑case password.)
- **Control is real and immediate** — test any control payload on one known unit (a back‑office room), never a batch to a whole `addressList`, until verified. The remote‑lock latency test was OK'd previously; general controls have not all been exercised on live guest rooms.
- **Heat vs cool cycle roles swap** — outdoor diagnostics (approach, superheat) are cooling‑mode logic; don't read them literally in heating.

---

## 11. Source of truth in this repo

| File | What it encodes |
|---|---|
| `custom_components/samsung_dms/api.py` | login + all endpoint calls (reusable client) |
| `custom_components/samsung_dms/const.py` | enum mappings, paths, tuning constants |
| `custom_components/samsung_dms/climate.py` | indoor + EHS space‑heating control/state mapping |
| `custom_components/samsung_dms/water_heater.py` | DHW control/state |
| `custom_components/samsung_dms/fan.py` + `sensor.py` | ERV control + telemetry |
| `custom_components/samsung_dms/outdoor.py` + `vrf_health.py` | outdoor telemetry + refrigerant diagnostics |
| `custom_components/samsung_dms/binary_sensor.py` | fault/filter/schedule/maintenance flags |
| `custom_components/samsung_dms/coordinator.py` | polling, optimistic writes, health hysteresis |
</content>

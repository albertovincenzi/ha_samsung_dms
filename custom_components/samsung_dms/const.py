"""Constants for the Samsung DMS integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "samsung_dms"

# Config entry keys
CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"

# Options-flow keys
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_USERNAME = "admin"
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL_SECONDS = 30
DEFAULT_SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)
# Bounds for the user-configurable polling interval. Faster than ~10 s risks
# overloading the controller; slower than 10 min makes control feel unresponsive.
MIN_SCAN_INTERVAL_SECONDS = 10
MAX_SCAN_INTERVAL_SECONDS = 600

# How long to keep an optimistically-set value on top of poll results before
# accepting the DMS's own reported state. Two poll cycles: enough for the
# device to actuate and be reflected in monitoring, without masking a command
# that silently failed for longer than necessary.
OPTIMISTIC_TTL_SECONDS = 60

# After a control command, poll again at these offsets (seconds) so a
# DMS-confirmed value replaces the optimistic guess within a few seconds
# instead of waiting for the next regular scan. The refresh debouncer
# coalesces bursts, so these are upper bounds rather than exact fire times.
CONFIRM_REFRESH_DELAYS = (4, 10)

# The DMS speaks XML-over-POST but replies with JSON. All read *and* control
# commands hit the same monitoring endpoint.
PATH_LOGIN = "/dms2/Login.jsp"
PATH_ROOT = "/dms2/"
PATH_MONITORING = "/dms2/getMonitoring?currentPage=main"
PATH_TREEVIEW = "/dms2/getTreeView?currentPage=main"
# Outdoor "cycle monitoring" data — note the DMS's own spelling of the path.
PATH_CYCLE = "/dms2/getControlMonitring"

# --- Samsung <-> Home Assistant enum mappings -------------------------------

# Samsung operationMode value -> HA HVACMode string (kept as plain strings here
# to avoid importing HA enums into the pure-protocol layer; climate.py maps to
# the real enums).
DMS_MODE_COOL = "cool"
DMS_MODE_HEAT = "heat"
DMS_MODE_DRY = "dry"
DMS_MODE_FAN = "fan"
DMS_MODE_AUTO = "auto"

# Samsung fanSpeed <-> HA fan mode label
FAN_SPEED_TO_HA = {
    "low": "low",
    "mid": "medium",
    "high": "high",
    "auto": "auto",
    "turbo": "turbo",
}
HA_TO_FAN_SPEED = {v: k for k, v in FAN_SPEED_TO_HA.items()}

# Absolute clamp used when a unit does not report per-mode limits.
DEFAULT_MIN_TEMP = 16.0
DEFAULT_MAX_TEMP = 30.0

# --- Device classification (from tree-view ``indoorType``) ------------------
DEVICE_TYPE_INDOOR = "indoor"
DEVICE_TYPE_EHS = "ehs"  # heat pump / domestic-hot-water (water_heater)
DEVICE_TYPE_PLUSERV = "pluserv"  # energy-recovery ventilator (fan)

# --- EHS domestic hot water (DHW) -------------------------------------------
DHW_OPERATION_OFF = "off"
# Supply modes offered by the DMS DHW panel (values sent lower-cased).
DHW_MODES = ["standard", "power", "force"]
DEFAULT_TANK_MIN_TEMP = 30.0
DEFAULT_TANK_MAX_TEMP = 70.0

# --- Energy-recovery ventilator (pluserv) -----------------------------------
# Ordered slow->fast; maps to a HA fan percentage.
VENT_SPEEDS = ["low", "mid", "high", "turbo"]
# Ventilation operating modes -> HA fan preset modes.
VENT_MODES = ["auto", "erv", "normal", "sleep"]

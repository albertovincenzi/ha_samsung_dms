"""Low-level async client for the Samsung DMS2.5 local controller.

Protocol (reverse-engineered from the DMS web UI, firmware 2.9.1.11):

* HTTPS on port 443 with a self-signed certificate (verification off by default).
* Session-cookie auth: GET ``/dms2/`` mints a ``JSESSIONID`` cookie, then a
  form POST to ``/dms2/Login.jsp`` with ``userId``/``password`` plus
  ``securedUsername``/``securedPassword`` (the credentials with the session id
  appended — RSA is disabled server-side because everything runs over TLS).
* Every data/control request POSTs a raw body of ``"<uuid>:<xml>"`` and the
  server replies with JSON. Reads and writes share the monitoring endpoint.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import (
    PATH_CYCLE,
    PATH_LOGIN,
    PATH_MONITORING,
    PATH_ROOT,
    PATH_TREEVIEW,
    PATH_USELIMIT,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Shared request header injected into every XML payload.
_HEADER = (
    "<header sa='web' da='dms' messageType='request' "
    "dateTime='{dt}' dvmControlMode='individual' />"
)


class SamsungDMSError(Exception):
    """Base error for the DMS client."""


class SamsungDMSAuthError(SamsungDMSError):
    """Raised when authentication fails."""


class SamsungDMSConnectionError(SamsungDMSError):
    """Raised when the DMS cannot be reached."""


def _now() -> str:
    """Return the DMS timestamp format: ``YYYY-MM-DDTHH:MM:SS:mmm``."""
    now = datetime.now()
    return now.strftime("%Y-%m-%dT%H:%M:%S:") + f"{now.microsecond // 1000:03d}"


def _envelope(payload: str) -> str:
    """Wrap an XML payload in the ``<uuid>:<root>...`` request envelope."""
    xml = (
        "<?xml version='1.0' encoding='utf-8' standalone='yes'?>"
        "<root>" + _HEADER.format(dt=_now()) + payload + "</root>"
    )
    return f"{uuid.uuid4()}:{xml}"


def _address_list(addresses: list[str]) -> str:
    inner = "".join(f"<address>{addr}</address>" for addr in addresses)
    return f"<addressList>{inner}</addressList>"


class _UseLimitForm(HTMLParser):
    """Parse the ``indoorUseLimit.jsp`` form into ordered (name, value) pairs.

    Inputs keep their ``value``; selects resolve to their selected option (or
    the first option). Order is preserved so the form can be posted back
    verbatim with only the targeted rows changed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[list[str]] = []
        self._sel: str | None = None
        self._sel_val: str | None = None
        self._opts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "input":
            name = a.get("name")
            if not name:
                return
            input_type = (a.get("type") or "text").lower()
            if input_type in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append([name, a.get("value") or "on"])
            else:
                self.fields.append([name, a.get("value") or ""])
        elif tag == "select":
            self._sel = a.get("name")
            self._sel_val = None
            self._opts = []
        elif tag == "option" and self._sel is not None:
            value = a.get("value") or ""
            if "selected" in a:
                self._sel_val = value
            self._opts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._sel is not None:
            value = self._sel_val
            if value is None:
                value = self._opts[0] if self._opts else ""
            self.fields.append([self._sel, value])
            self._sel = None


class SamsungDMSClient:
    """Talks to a single Samsung DMS controller."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialise the client.

        ``session`` must be created with ``aiohttp.CookieJar(unsafe=True)`` so
        cookies are retained for a bare-IP host, and with TLS verification
        matching the user's ``verify_ssl`` choice.
        """
        self._base = f"https://{host.rstrip('/')}"
        self._username = username
        self._password = password
        self._session = session
        self._authenticated = False

    @property
    def base_url(self) -> str:
        """Return the controller base URL."""
        return self._base

    async def async_login(self) -> None:
        """Establish a session and authenticate.

        Raises:
            SamsungDMSAuthError: credentials rejected.
            SamsungDMSConnectionError: controller unreachable.
        """
        try:
            # Step 1: obtain a JSESSIONID cookie.
            async with self._session.get(
                self._base + PATH_ROOT, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()

            jsid = self._current_jsessionid()
            if not jsid:
                raise SamsungDMSAuthError("No session cookie returned by DMS")

            # Step 2: form login with the session id appended to credentials.
            form = {
                "userId": self._username,
                "password": self._password,
                "securedUsername": f"{self._username}{jsid}",
                "securedPassword": f"{self._password}{jsid}",
            }
            async with self._session.post(
                self._base + PATH_LOGIN, data=form, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                body = await resp.text()
        except aiohttp.ClientError as err:
            raise SamsungDMSConnectionError(str(err)) from err

        # A successful login redirects (via meta refresh) to main.jsp. The login
        # form is re-served on failure, so treat a bounce back to it as a reject.
        if "main.jsp" not in body and "Login.jsp" in body:
            raise SamsungDMSAuthError("DMS rejected the supplied credentials")

        self._authenticated = True
        _LOGGER.debug("Samsung DMS login succeeded")

    def _current_jsessionid(self) -> str | None:
        for cookie in self._session.cookie_jar:
            if cookie.key == "JSESSIONID":
                return cookie.value
        return None

    async def _post(self, path: str, body: str, *, _retry: bool = True) -> Any:
        """POST a request envelope, re-authenticating once on session loss."""
        if not self._authenticated:
            await self.async_login()

        try:
            async with self._session.post(
                self._base + path,
                data=body.encode("utf-8"),
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise SamsungDMSAuthError(f"HTTP {resp.status}")
                resp.raise_for_status()
                text = await resp.text()
        except SamsungDMSAuthError:
            if _retry:
                self._authenticated = False
                await self.async_login()
                return await self._post(path, body, _retry=False)
            raise
        except aiohttp.ClientError as err:
            raise SamsungDMSConnectionError(str(err)) from err

        # The DMS occasionally serves the login page on an expired session
        # without a 401; detect it and retry once.
        if text.lstrip().startswith("<") and "Login.jsp" in text:
            if _retry:
                self._authenticated = False
                await self.async_login()
                return await self._post(path, body, _retry=False)
            raise SamsungDMSAuthError("Session expired and re-login failed")

        try:
            import json

            return json.loads(text)
        except ValueError as err:
            raise SamsungDMSError(f"Non-JSON response from DMS: {err}") from err

    async def async_get_monitoring(self) -> list[dict[str, Any]]:
        """Return the flattened per-indoor-unit state list.

        Each item is the ``indoorDetail`` dict augmented with its ``addr``.
        """
        body = _envelope("<getMonitoring><all/></getMonitoring>")
        data = await self._post(PATH_MONITORING, body)
        result: list[dict[str, Any]] = []
        for entry in data.get("indoorList", []):
            addr = entry.get("addr")
            children = entry.get("child") or []
            detail = children[0] if children else {}
            if addr:
                merged = dict(detail)
                merged["addr"] = addr
                merged["nodeName"] = entry.get("nodeName", "indoor")
                result.append(merged)
        return result

    async def async_get_tree(self) -> dict[str, Any]:
        """Return the raw tree-view payload (device hierarchy + labels)."""
        body = _envelope("<treeInfoEx range='all' />")
        return await self._post(PATH_TREEVIEW, body)

    async def async_get_outdoor_addresses(self) -> list[str]:
        """Return the outdoor-unit addresses from the tree view."""
        tree = await self.async_get_tree()
        return [
            entry["addr"]
            for entry in tree.get("treeOutDoor", [])
            if entry.get("addr")
        ]

    async def async_get_cycle_monitoring(
        self, outdoor_addrs: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Return outdoor-unit cycle/diagnostic data keyed by address.

        Each value flattens the outdoor node with its compressor ``unitDetail``
        (pressures, temperatures, currents, IPM, run hours, etc.) and adds a
        ``commError`` flag when the DMS reports a communication error.
        """
        if not outdoor_addrs:
            return {}
        outer = "".join(f"<outdoor addr='{a}' />" for a in outdoor_addrs)
        payload = (
            "<getCycleMonitoring>"
            f"<outdoorList>{outer}</outdoorList>"
            "<indoorList></indoorList>"
            "</getCycleMonitoring>"
        )
        data = await self._post(PATH_CYCLE, _envelope(payload))

        comm_errors = {
            e.get("addr")
            for e in data.get("commErrorList", [])
            if isinstance(e, dict) and e.get("addr")
        }

        result: dict[str, dict[str, Any]] = {}
        for outdoor in data.get("outdoorList", []):
            addr = outdoor.get("addr")
            if not addr:
                continue
            merged: dict[str, Any] = {
                k: v for k, v in outdoor.items() if k != "child"
            }
            # Descend outdoor -> unit -> unitDetail for the cycle values.
            units = outdoor.get("child") or []
            unit = units[0] if units else {}
            details = unit.get("child") or []
            if details:
                merged.update(
                    {k: v for k, v in details[0].items() if k != "nodeName"}
                )
            merged["addr"] = addr
            merged["commError"] = addr in comm_errors
            result[addr] = merged
        return result

    async def _get_text(self, path: str, *, _retry: bool = True) -> str:
        """GET a page and return its text, re-authenticating once on session loss."""
        if not self._authenticated:
            await self.async_login()
        try:
            async with self._session.get(
                self._base + path, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    raise SamsungDMSAuthError(f"HTTP {resp.status}")
                resp.raise_for_status()
                text = await resp.text()
        except SamsungDMSAuthError:
            if _retry:
                self._authenticated = False
                await self.async_login()
                return await self._get_text(path, _retry=False)
            raise
        except aiohttp.ClientError as err:
            raise SamsungDMSConnectionError(str(err)) from err
        if "Login.jsp" in text and _retry:
            self._authenticated = False
            await self.async_login()
            return await self._get_text(path, _retry=False)
        return text

    async def _post_form(self, path: str, body: list[tuple[str, str]]) -> str:
        """POST a form-urlencoded body (for the HTML JSP feature pages)."""
        if not self._authenticated:
            await self.async_login()
        data = urlencode(body).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with self._session.post(
                self._base + path, data=data, headers=headers, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                return await resp.text()
        except aiohttp.ClientError as err:
            raise SamsungDMSConnectionError(str(err)) from err

    async def async_get_use_limits(self) -> dict[str, dict[str, str]]:
        """Return current guest use-limits keyed by unit address.

        Each value has ``coolLowerTemp``/``coolUpperTemp``/``heatLowerTemp``/
        ``heatUpperTemp``/``operationModeLimit`` as strings.
        """
        parser = _UseLimitForm()
        parser.feed(await self._get_text(PATH_USELIMIT))
        rows: dict[str, dict[str, str]] = {}
        index_addr: dict[str, str] = {}
        for name, value in parser.fields:
            if name.startswith("indoorId_"):
                index_addr[name.split("_", 1)[1]] = value
        wanted = (
            "coolLowerTemp",
            "coolUpperTemp",
            "heatLowerTemp",
            "heatUpperTemp",
            "operationModeLimit",
        )
        for name, value in parser.fields:
            for base in wanted:
                if name.startswith(base + "_"):
                    idx = name[len(base) + 1 :]
                    addr = index_addr.get(idx)
                    if addr:
                        rows.setdefault(addr, {})[base] = value
        return rows

    async def async_set_use_limits(
        self, changes: dict[str, dict[str, str]]
    ) -> None:
        """Apply per-address use-limit changes via a whole-form round-trip.

        ``changes`` maps a unit address to the fields to override, e.g.
        ``{"11.00.08": {"coolLowerTemp": "22.0", "coolUpperTemp": "28.0"}}``.
        Every other field on the page is echoed back unchanged, so only the
        named rows/fields are modified.
        """
        parser = _UseLimitForm()
        parser.feed(await self._get_text(PATH_USELIMIT))
        fields = parser.fields
        index_addr = {
            name.split("_", 1)[1]: value
            for name, value in fields
            if name.startswith("indoorId_")
        }
        addr_index = {addr: idx for idx, addr in index_addr.items()}
        overrides: dict[str, str] = {}
        for addr, vals in changes.items():
            idx = addr_index.get(addr)
            if idx is None:
                _LOGGER.warning("Use-limit: address %s not on the page", addr)
                continue
            for base, val in vals.items():
                overrides[f"{base}_{idx}"] = str(val)
        body = [(name, overrides.get(name, value)) for name, value in fields]
        body = [(n, "save" if n == "mode" else v) for n, v in body]
        if not any(n == "mode" for n, _ in body):
            body.append(("mode", "save"))
        await self._post_form(PATH_USELIMIT, body)

    async def async_get_indoor_metadata(self) -> dict[str, dict[str, Any]]:
        """Return per-unit metadata keyed by address.

        The ``treeIndoor`` section of the tree view is a flat list that maps
        each address to its user-assigned label plus model info — the reliable
        source for friendly names (the ``treeViewName`` tree is order-dependent
        and unsafe to parse).
        """
        tree = await self.async_get_tree()
        meta: dict[str, dict[str, Any]] = {}
        for entry in tree.get("treeIndoor", []):
            addr = entry.get("addr")
            if not addr:
                continue
            meta[addr] = {
                "name": (entry.get("name") or "").strip() or addr,
                "sub_type": entry.get("subIndoorType") or "",
                "indoor_type": entry.get("indoorType") or "indoor",
                "model_code": (entry.get("modelCode") or "").strip(),
                "version": entry.get("version") or "",
            }
        return meta

    async def async_control(
        self, addresses: list[str], control_values: dict[str, str]
    ) -> None:
        """Send a control command to one or more indoor units.

        ``control_values`` maps DMS tag -> value, e.g.
        ``{"power": "on", "operationMode": "cool"}`` or ``{"setTemp": "24.0"}``.
        All tags are applied to every address in the same command.
        """
        if not control_values:
            return
        inner = "".join(f"<{tag}>{val}</{tag}>" for tag, val in control_values.items())
        payload = (
            "<setDeviceControl><controlList><control>"
            f"<controlValue>{inner}</controlValue>"
            f"{_address_list(addresses)}"
            "</control></controlList></setDeviceControl>"
        )
        body = _envelope(payload)
        await self._post(PATH_MONITORING, body)

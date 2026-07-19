"""Client for Empower Personal Dashboard's internal (undocumented) API.

This is the same API the web dashboard at home.personalcapital.com uses.
There is no official consumer API, so every call here is defensive: fields
are read with .get(), auth failures map to SessionExpiredError, and
transient failures are retried with backoff.

Read-only by design: only data-fetch endpoints are implemented. Do not add
anything that mutates account data.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.environ.get("EMPOWER_BASE_URL", "https://home.personalcapital.com")
API_ROOT = f"{BASE_URL}/api"

# The login page embeds the initial CSRF token in an inline script.
CSRF_RE = re.compile(r"globals\.csrf='([a-f0-9-]+)'")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Empower returns spHeader error code 201 when the session is no longer
# authenticated.
AUTH_REQUIRED_ERROR_CODE = 201

MIN_REQUEST_INTERVAL_SECONDS = 1.0
RETRY_BACKOFF_SECONDS = (2, 4, 8)

SETUP_HINT = (
    "Empower session is missing or expired. "
    "Re-run `empower-mcp setup` in a terminal to re-authenticate (2FA), "
    "then retry this request."
)


def default_session_path() -> Path:
    config_dir = os.environ.get("EMPOWER_MCP_CONFIG_DIR", "~/.config/empower-mcp")
    return Path(config_dir).expanduser() / "session.json"


class EmpowerError(Exception):
    """Base error for Empower API problems."""


class SessionExpiredError(EmpowerError):
    def __init__(self, message: str = SETUP_HINT):
        super().__init__(message)


class TwoFactorRequiredError(EmpowerError):
    """Raised during setup when the account needs a 2FA challenge."""


class ApiError(EmpowerError):
    """Non-auth API failure (bad response, upstream error)."""


class EmpowerClient:
    def __init__(self, session_path: Path | None = None):
        self.session_path = session_path or default_session_path()
        self.csrf: str | None = None
        self._last_request_at = 0.0
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def load_session(self) -> bool:
        """Load cookies + CSRF from disk. Returns False if no session file."""
        try:
            raw = self.session_path.read_text()
        except FileNotFoundError:
            return False
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return False
        self.csrf = data.get("csrf")
        for name, value in (data.get("cookies") or {}).items():
            self._http.cookies.set(name, value, domain=data.get("cookie_domain", ""))
        return bool(self.csrf)

    def save_session(self) -> None:
        """Persist cookies + CSRF with 0600 perms (owner read/write only)."""
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_domain = ""
        cookies: dict[str, str] = {}
        for cookie in self._http.cookies.jar:
            cookies[cookie.name] = cookie.value or ""
            cookie_domain = cookie.domain or cookie_domain
        payload = json.dumps(
            {"csrf": self.csrf, "cookies": cookies, "cookie_domain": cookie_domain}
        )
        tmp_path = self.session_path.with_suffix(".tmp")
        fd = os.open(
            tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR
        )
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
        os.replace(tmp_path, self.session_path)
        os.chmod(self.session_path, stat.S_IRUSR | stat.S_IWUSR)

    def clear_session(self) -> None:
        self.session_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Request core
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)

    def _post(self, path: str, data: dict[str, Any] | None = None) -> httpx.Response:
        """POST a form-encoded API call with throttling and retry on 429/5xx."""
        payload = {
            "csrf": self.csrf or "",
            "apiClient": "WEB",
            "lastServerChangeId": "-1",
        }
        if data:
            payload.update(data)
        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0, *RETRY_BACKOFF_SECONDS)):
            if backoff:
                time.sleep(backoff)
            self._throttle()
            try:
                resp = self._http.post(f"{API_ROOT}{path}", data=payload)
            except httpx.TransportError as exc:
                last_exc = exc
                continue
            finally:
                self._last_request_at = time.monotonic()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = ApiError(
                    f"Empower API returned HTTP {resp.status_code} for {path}"
                )
                continue
            return resp
        raise ApiError(f"Empower API request to {path} failed after retries: {last_exc}")

    def _parse(self, resp: httpx.Response, path: str) -> dict[str, Any]:
        if resp.status_code in (401, 403):
            raise SessionExpiredError()
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ApiError(
                f"Empower API returned non-JSON response (HTTP {resp.status_code}) "
                f"for {path}"
            ) from exc
        sp_header = body.get("spHeader") or {}
        new_csrf = sp_header.get("csrf")
        if new_csrf:
            self.csrf = new_csrf
        if not sp_header.get("success", False):
            errors = sp_header.get("errors") or []
            codes = {e.get("code") for e in errors}
            if AUTH_REQUIRED_ERROR_CODE in codes:
                raise SessionExpiredError()
            messages = "; ".join(str(e.get("message", e)) for e in errors) or "unknown"
            raise ApiError(f"Empower API call {path} failed: {messages}")
        return body

    def api_call(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Authenticated read-only API call. Returns the spData payload."""
        body = self._parse(self._post(path, data), path)
        auth_level = (body.get("spHeader") or {}).get("authLevel")
        if auth_level and auth_level != "SESSION_AUTHENTICATED":
            raise SessionExpiredError()
        # CSRF rotates and cookies refresh on every call; persist so the
        # session survives server restarts.
        self.save_session()
        return body.get("spData") or {}

    # ------------------------------------------------------------------
    # Auth flow (used only by the interactive `setup` CLI)
    # ------------------------------------------------------------------

    def fetch_initial_csrf(self) -> None:
        self._throttle()
        resp = self._http.get(f"{BASE_URL}/page/login/goHome")
        self._last_request_at = time.monotonic()
        match = CSRF_RE.search(resp.text)
        if not match:
            raise ApiError(
                "Could not find CSRF token on the Empower login page. "
                "The site markup may have changed."
            )
        self.csrf = match.group(1)

    def identify_user(self, username: str) -> str:
        """Submit the email. Returns the resulting authLevel.

        'USER_REMEMBERED' means this device is trusted and no 2FA is needed.
        """
        body = self._parse(
            self._post(
                "/login/identifyUser",
                {
                    "username": username,
                    "bindDevice": "false",
                    "skipLinkAccount": "false",
                    "redirectTo": "",
                    "skipFirstUse": "",
                    "referrerId": "",
                },
            ),
            "/login/identifyUser",
        )
        return (body.get("spHeader") or {}).get("authLevel", "")

    def challenge_two_factor(self, method: str) -> None:
        """Request a 2FA code. method: 'sms' or 'email'."""
        endpoint = {
            "sms": "/credential/challengeSms",
            "email": "/credential/challengeEmail",
        }[method]
        challenge_type = {"sms": "challengeSMS", "email": "challengeEmail"}[method]
        self._parse(
            self._post(
                endpoint,
                {
                    "challengeReason": "DEVICE_AUTH",
                    "challengeMethod": "OP",
                    "challengeType": challenge_type,
                    "bindDevice": "false",
                },
            ),
            endpoint,
        )

    def authenticate_two_factor(self, method: str, code: str) -> None:
        endpoint = {
            "sms": "/credential/authenticateSms",
            "email": "/credential/authenticateEmailByCode",
        }[method]
        self._parse(
            self._post(
                endpoint,
                {
                    "challengeReason": "DEVICE_AUTH",
                    "challengeMethod": "OP",
                    "bindDevice": "false",
                    "code": code,
                },
            ),
            endpoint,
        )

    def authenticate_password(self, password: str) -> None:
        body = self._parse(
            self._post(
                "/credential/authenticatePassword",
                {
                    "bindDevice": "true",
                    "deviceName": "empower-mcp",
                    "redirectTo": "",
                    "skipFirstUse": "",
                    "skipLinkAccount": "false",
                    "referrerId": "",
                    "passwd": password,
                },
            ),
            "/credential/authenticatePassword",
        )
        auth_level = (body.get("spHeader") or {}).get("authLevel")
        if auth_level != "SESSION_AUTHENTICATED":
            raise ApiError(
                f"Password authentication did not complete (authLevel={auth_level})."
            )
        self.save_session()

    # ------------------------------------------------------------------
    # Read-only data endpoints
    # ------------------------------------------------------------------

    def get_accounts(self) -> dict[str, Any]:
        return self.api_call("/newaccount/getAccounts2")

    def get_transactions(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        sp_data = self.api_call(
            "/transaction/getUserTransactions",
            {"startDate": start_date, "endDate": end_date},
        )
        return sp_data.get("transactions") or []

    def get_categories(self) -> dict[int, str]:
        """Map of categoryId -> category name."""
        sp_data = self.api_call("/transactioncategory/getCategories")
        categories = sp_data if isinstance(sp_data, list) else sp_data.get("categories") or []
        result: dict[int, str] = {}
        for cat in categories:
            cat_id = cat.get("transactionCategoryId")
            if cat_id is not None:
                result[cat_id] = cat.get("name", "")
        return result

    def get_holdings(self, account_ids: list[int] | None = None) -> list[dict[str, Any]]:
        data: dict[str, Any] = {}
        if account_ids:
            data["userAccountIds"] = json.dumps(account_ids)
        sp_data = self.api_call("/invest/getHoldings", data)
        return sp_data.get("holdings") or []

    def get_networth_history(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        # Wrappers in the wild disagree on the interval parameter name, so
        # send both spellings; the server ignores unknown keys.
        sp_data = self.api_call(
            "/account/getHistories",
            {
                "startDate": start_date,
                "endDate": end_date,
                "interval": "DAY",
                "intervalType": "DAY",
                "types": json.dumps(["networth"]),
            },
        )
        return sp_data.get("networthHistories") or sp_data.get("histories") or []

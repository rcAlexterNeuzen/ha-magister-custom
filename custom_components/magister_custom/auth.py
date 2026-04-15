"""Magister authentication and API client.

Implements Magister's OIDC-based challenge flow:
  1. Fetch .well-known/openid-configuration from accounts.magister.net
  2. Fetch school oidc_config.js to get client_id / redirect_uri
  3. Start the auth session (gets XSRF cookie, sessionId, returnUrl, account.js)
  4. Extract authCode from account.js
  5. POST challenges: current → username → password (→ totp if MFA)
  6. Follow the final redirect to extract the access_token from the URL fragment

All network I/O is async (aiohttp).  TOTP is generated locally from the
base32-encoded secret using HMAC-SHA1 (RFC 6238).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import struct
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

_ACCOUNTS_HOST = "accounts.magister.net"
_DEFAULT_AUTHCODE = "00000000000000000000000000000000"


# ---------------------------------------------------------------------------
# TOTP helpers
# ---------------------------------------------------------------------------

def _generate_totp(secret: str, digits: int = 6, period: int = 30) -> str:
    """Generate a TOTP OTP from a base32-encoded secret (RFC 6238 / HOTP)."""
    clean = secret.upper().replace(" ", "").replace("-", "").rstrip("=")
    clean = "".join(c for c in clean if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    padding = (8 - len(clean) % 8) % 8
    key = base64.b32decode(clean + "=" * padding, casefold=True)
    counter = struct.pack(">Q", int(time.time()) // period)
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


# ---------------------------------------------------------------------------
# account.js / oidc_config.js parsing helpers
# ---------------------------------------------------------------------------

def _extract_authcode(js: str) -> str:
    """Extract the authCode from an account-XXXXX.js bundle.

    The bundle contains an expression like:
        (n=["aabbcc","..."],["3","1","0",...].map(...)
    where the authcode is built by indexing the first array with the
    second array's values.
    """
    m = re.search(r'\(\w=\["([0-9a-f",]+?)"\],\["([0-9",]+?)"\]\.map', js)
    if m:
        codes = m.group(1).split('","')
        try:
            idxes = [int(i) for i in m.group(2).split('","')]
            return "".join(codes[i] for i in idxes)
        except (IndexError, ValueError):
            pass
    _LOGGER.debug("Could not extract authcode from account.js; using default")
    return _DEFAULT_AUTHCODE


def _extract_oidc_config(js: str, school_host: str) -> dict[str, Any]:
    """Parse the school's oidc_config.js property bag into a Python dict."""
    cfg: dict[str, Any] = {}
    for line in re.split(r"[\r\n]+", js):
        m = re.match(r"\s*(\w+)\s*:\s*(.*?),?\s*$", line)
        if not m:
            continue
        key, raw = m.groups()
        # Replace 'window.location.hostname' placeholder with actual host
        raw = re.sub(r"' \+ window\.location\.hostname", f"{school_host}'", raw)
        raw = re.sub(r"' \+ '", "", raw)
        if raw == "false":
            cfg[key] = False
        elif raw == "true":
            cfg[key] = True
        elif m2 := re.match(r"'(.*)',?$", raw):
            cfg[key] = m2.group(1)
    return cfg


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _jwt_expiry(token: str) -> datetime | None:
    """Decode a JWT payload and return its exp timestamp, or None."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if exp := payload.get("exp"):
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MagisterAuthError(Exception):
    """Raised when authentication fails for any reason."""


class MagisterTOTPRequired(MagisterAuthError):
    """Raised when 2FA is required but no TOTP secret was provided."""


class MagisterTOTPFailed(MagisterAuthError):
    """Raised when the TOTP/softtoken challenge itself is rejected."""


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class MagisterClient:
    """Async client for the Magister school information system.

    Usage pattern:
        async with aiohttp.ClientSession() as auth_session:
            await client.authenticate(auth_session)
        # API calls with any session (Bearer token, no cookies needed):
        data = await client.api_get(api_session, "account")
    """

    def __init__(
        self,
        school: str,
        username: str,
        password: str,
        totp_secret: str | None = None,
    ) -> None:
        self.school = school
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.school_host = f"{school}.magister.net"
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_authenticated(self) -> bool:
        """Return True when we hold a token that is valid for ≥5 more minutes."""
        if not self._access_token:
            return False
        if self._token_expires is None:
            return True
        return self._token_expires > datetime.now(tz=timezone.utc) + timedelta(minutes=5)

    def invalidate_token(self) -> None:
        """Force re-authentication on next call."""
        self._access_token = None
        self._token_expires = None

    async def authenticate(self, session: aiohttp.ClientSession) -> None:
        """Run the full Magister OIDC challenge flow.

        `session` must have its own CookieJar so that the XSRF cookie is
        captured.  Create a dedicated session for authentication:

            async with aiohttp.ClientSession() as auth_session:
                await client.authenticate(auth_session)
        """
        accounts_url = f"https://{_ACCOUNTS_HOST}"
        school_url = f"https://{self.school_host}"

        # 1. OIDC discovery
        openid_cfg: dict = await self._get_json(
            session, f"{accounts_url}/.well-known/openid-configuration"
        )
        auth_endpoint: str = openid_cfg["authorization_endpoint"]

        # 2. School OIDC config
        raw_js = await self._get_bytes(session, f"{school_url}/oidc_config.js")
        oidc_cfg = _extract_oidc_config(
            raw_js.decode("utf-8", errors="replace"), self.school_host
        )

        params = {
            "client_id": oidc_cfg.get("client_id", ""),
            "redirect_uri": oidc_cfg.get("redirect_uri", ""),
            "response_type": oidc_cfg.get("response_type", "token id_token"),
            "scope": "openid profile",
            "state": "11111111111111111111111111111111",
            "nonce": "11111111111111111111111111111111",
            "acr_values": oidc_cfg.get("acr_values", ""),
        }

        # 3. Start auth session – follows redirects, sets XSRF-TOKEN cookie,
        #    lands on the challenge page whose URL has ?sessionId=...&returnUrl=...
        auth_url = auth_endpoint + "?" + urllib.parse.urlencode(params)
        _LOGGER.debug("[Magister auth] step 3: fetching auth URL for %s", self.school_host)
        session_url, html = await self._follow_get(session, auth_url)
        _LOGGER.debug("[Magister auth] step 3: session URL = %s", session_url)

        # Extract XSRF token from cookie jar
        # filter_cookies returns SimpleCookie; values may be Morsel or str depending on version
        xsrf_token = ""
        try:
            cookies = session.cookie_jar.filter_cookies(URL(accounts_url))
            raw = cookies.get("XSRF-TOKEN")
            if raw is not None:
                xsrf_token = raw.value if hasattr(raw, "value") else str(raw)
        except Exception as err:
            _LOGGER.debug("[Magister auth] Could not read XSRF-TOKEN cookie: %s", err)
        _LOGGER.debug("[Magister auth] XSRF token present: %s", bool(xsrf_token))

        # Extract sessionId + returnUrl from the challenge page URL
        parsed = urllib.parse.urlparse(session_url)
        qs = urllib.parse.parse_qs(parsed.query)
        session_id = (qs.get("sessionId") or [None])[0]
        return_url = (qs.get("returnUrl") or [None])[0]
        _LOGGER.debug(
            "[Magister auth] sessionId=%s returnUrl=%s",
            bool(session_id),
            bool(return_url),
        )

        if not session_id:
            raise MagisterAuthError(
                f"Could not extract sessionId from URL: {session_url!r}. "
                "The school may use SSO/SAML which requires browser login."
            )

        # 4. Extract authCode from account-XXXXX.js
        authcode = _DEFAULT_AUTHCODE
        if m := re.search(r"js/account-\w+\.js", html):
            account_js_url = f"{accounts_url}/{m.group(0)}"
            try:
                js_bytes = await self._get_bytes(session, account_js_url)
                authcode = _extract_authcode(js_bytes.decode("utf-8", errors="replace"))
                _LOGGER.debug("[Magister auth] authcode extracted from account.js")
            except Exception as err:
                _LOGGER.warning("Failed to load account.js (%s); using default authcode", err)

        # 5. Challenge flow
        extra_headers: dict[str, str] = {}
        if xsrf_token:
            extra_headers["X-XSRF-TOKEN"] = xsrf_token

        payload: dict[str, Any] = {
            "sessionId": session_id,
            "returnUrl": return_url,
            "authCode": authcode,
        }

        # 5a. current
        _LOGGER.debug("[Magister auth] step 5a: challenges/current")
        await self._post_json(
            session, f"{accounts_url}/challenges/current", payload, extra_headers
        )

        # 5b. username
        _LOGGER.debug("[Magister auth] step 5b: challenges/username")
        payload["username"] = self.username
        r_user = await self._post_json(
            session, f"{accounts_url}/challenges/username", payload, extra_headers
        )
        if r_user.get("error"):
            raise MagisterAuthError(
                f"Username challenge error: {r_user['error']}. "
                "Check your username (some schools use email address format)."
            )

        # 5c. password
        _LOGGER.debug("[Magister auth] step 5c: challenges/password")
        payload["password"] = self.password
        r = await self._post_json(
            session, f"{accounts_url}/challenges/password", payload, extra_headers
        )
        _LOGGER.debug(
            "[Magister auth] password response: redirectURL=%s action=%s error=%s",
            bool(r.get("redirectURL")),
            r.get("action"),
            r.get("error"),
        )

        if r.get("error"):
            raise MagisterAuthError(f"Password challenge error: {r['error']}")

        # 5d. Optional 2FA challenge
        if not r.get("redirectURL"):
            action = r.get("action", "")
            _LOGGER.debug("[Magister auth] step 5d: 2FA action=%r", action)
            if action in ("totp", "softtoken"):
                r = await self._handle_mfa(
                    session, action, payload, extra_headers, accounts_url
                )
            else:
                raise MagisterAuthError(
                    f"Unexpected challenge response (action={action!r}): {r}"
                )

        # 6. Extract access token from final redirect
        redirect_url = accounts_url + r["redirectURL"]
        token = await self._extract_token(session, redirect_url)
        self._access_token = token
        self._token_expires = _jwt_expiry(token)
        _LOGGER.debug("Magister authenticated; token expires %s", self._token_expires)

    async def api_get(
        self,
        session: aiohttp.ClientSession,
        *path: Any,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Authenticated GET to the school API.

        Raises MagisterAuthError on 401 (caller should re-authenticate).
        """
        if not self._access_token:
            raise MagisterAuthError("Not authenticated")
        url = f"https://{self.school_host}/api/" + "/".join(str(p) for p in path)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        async with session.get(url, headers=headers, params=params) as resp:
            if resp.status == 401:
                self.invalidate_token()
                raise MagisterAuthError("Access token expired (HTTP 401)")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_mfa(
        self,
        session: aiohttp.ClientSession,
        action: str,
        payload: dict,
        headers: dict,
        accounts_url: str,
    ) -> dict:
        """Submit TOTP / soft-token challenge and return the response."""
        if not self.totp_secret:
            raise MagisterTOTPRequired(
                f"2FA ({action}) is required but no TOTP secret is configured"
            )
        otp = _generate_totp(self.totp_secret)
        otp_payload = dict(payload)
        if action == "softtoken":
            otp_payload["code"] = otp
            endpoint = "soft-token"
        else:
            otp_payload["otp"] = otp
            endpoint = action  # "totp"
        r = await self._post_json(
            session, f"{accounts_url}/challenges/{endpoint}", otp_payload, headers
        )
        if not r.get("redirectURL") or r.get("error"):
            raise MagisterTOTPFailed(
                f"2FA challenge failed (action={action}): {r.get('error', 'no redirectURL')}"
            )
        return r

    async def _extract_token(
        self, session: aiohttp.ClientSession, url: str
    ) -> str:
        """Follow redirects manually and extract access_token from the URL fragment.

        Magister's OIDC implicit flow embeds the token in the Location header's
        fragment, e.g.:
          302  Location: https://school.magister.net/oidc/callback#access_token=xxx&...
        """
        current = url
        for _ in range(10):
            async with session.get(current, allow_redirects=False) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if "#" in location:
                        fragment = location.split("#", 1)[1]
                        params = urllib.parse.parse_qs(fragment)
                        if "access_token" in params:
                            return params["access_token"][0]
                    # Keep following
                    if location.startswith("/"):
                        p = urllib.parse.urlparse(current)
                        current = f"{p.scheme}://{p.netloc}{location}"
                    elif location:
                        current = location
                    else:
                        break
                elif resp.status == 200:
                    # Token might already be in the URL we constructed
                    if "#" in current:
                        fragment = current.split("#", 1)[1]
                        params = urllib.parse.parse_qs(fragment)
                        if "access_token" in params:
                            return params["access_token"][0]
                    raise MagisterAuthError(
                        "Reached final callback page without finding access_token"
                    )
                else:
                    raise MagisterAuthError(
                        f"HTTP {resp.status} while retrieving access token from {current}"
                    )
        raise MagisterAuthError("Too many redirects while retrieving access token")

    async def _get_json(
        self, session: aiohttp.ClientSession, url: str
    ) -> dict:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _get_bytes(
        self, session: aiohttp.ClientSession, url: str
    ) -> bytes:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def _follow_get(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str, str]:
        """GET `url` following all redirects; return (final_url, body_text)."""
        async with session.get(url, allow_redirects=True) as resp:
            resp.raise_for_status()
            body = await resp.read()
            return str(resp.url), body.decode("utf-8", errors="replace")

    async def _post_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        data: dict,
        extra_headers: dict | None = None,
    ) -> dict:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        async with session.post(url, json=data, headers=headers) as resp:
            try:
                result = await resp.json(content_type=None)
                return result if isinstance(result, dict) else {}
            except Exception:
                resp.raise_for_status()
                return {}

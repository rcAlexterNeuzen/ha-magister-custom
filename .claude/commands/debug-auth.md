---
description: Diagnose and fix Magister authentication issues. Optionally pass a log snippet or error message as argument.
---

Diagnose a Magister authentication problem.

$ARGUMENTS

## Diagnostic checklist

Work through these in order and stop at the first match.

### 1. Config flow won't load (MFA prompt never appears)
- Check `config_flow.py` imports: must use `from homeassistant.config_entries import ConfigFlowResult`, not `FlowResult` from `homeassistant.data_entry_flow` (removed in HA 2024.4+).
- Check all method return types use `ConfigFlowResult`.

### 2. Token expires every ~60 minutes and triggers manual re-auth
- `coordinator.py` `_reauthenticate()` must always call `_reset_auth_session()` before `try_silent_reauthenticate()` — stale cookies from a previous challenge flow break silent re-auth.
- `_async_update_data()` must check `is_authenticated()` **before** calling `_fetch_all()`, not after catching a 401.
- `_fetch_all()` must raise `MagisterAuthError("Not authenticated")` instead of calling `authenticate()` itself.

### 3. Silent re-auth always fails (server session expired)
- Silent re-auth works only while the server-side OIDC session is valid (typically 4–24 h after last login).
- If silent re-auth fails every cycle, the server session might be expiring too quickly — check if the school uses SSO/SAML (not supported).
- Fallback: store the base32 TOTP secret in the integration settings so the full challenge flow can complete automatically.

### 4. TOTP code rejected (`MagisterTOTPFailed`)
- The stored secret must be the **base32 seed** (from app setup), not a 6-digit code.
- Clock skew: `_generate_totp()` in `auth.py` tries offsets 0, -1, +1 (±30 s window). If the system clock is off by more than 60 s, TOTP will always fail.
- The `action` field in the password challenge response must be `"totp"` or `"softtoken"`. If Magister returns a different action string, `_handle_mfa()` won't catch it — check the debug log line `[Magister auth] step 5d: 2FA action=...`.

### 5. `authcode` extraction failure
- `_extract_authcode()` in `auth.py` uses a regex against the `account-XXXXX.js` bundle. If Magister updated the bundle format, the regex may silently fall back to the default `"00000000000000000000000000000000"`, causing the challenge to fail.
- Enable debug logging (`logger: magister_custom: debug` in HA) and look for `[Magister auth] authcode extracted from account.js` vs `using default authcode`.

### 6. School uses SSO / SAML
- `authenticate()` raises `MagisterAuthError: Could not extract sessionId` — the school redirects to an external IdP instead of the Magister challenge page.
- These schools cannot be used with this integration; manual browser login is required.

## Checking HA logs

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.magister_custom: debug
```

Then restart HA and look for lines starting with `[Magister auth]` in **Settings → System → Logs**.

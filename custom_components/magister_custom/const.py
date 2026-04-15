"""Constants for the Magister integration."""

DOMAIN = "magister_custom"

# Config keys
CONF_SCHOOL = "school"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_TOTP_SECRET = "totp_secret"

# Magister API
MAGISTER_ACCOUNTS_HOST = "accounts.magister.net"
DEFAULT_AUTHCODE = "00000000000000000000000000000000"

# Update interval (minutes)
SCAN_INTERVAL_MINUTES = 15

# Platforms
PLATFORMS = ["sensor", "calendar"]

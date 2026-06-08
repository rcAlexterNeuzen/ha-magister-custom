---
description: Bump the integration version, update all required files, and prepare for release. Pass the new version number as argument (e.g. /bump-version 1.0.11).
---

Bump the ha-magister-custom integration to version **$ARGUMENTS** following the mandatory rules from `.github/copilot-instructions.md`.

Do all of the following in order:

1. **manifest.json** — set `"version"` to `$ARGUMENTS`.

2. **README.md** — insert a new changelog section at the top of the `## Changelog` block:
   ```
   ### v$ARGUMENTS

   - <describe what changed>
   ```
   Ask me what changed if I haven't told you yet. Keep existing entries intact below.

3. **hacs.json** — update `"homeassistant"` only if this release requires a newer minimum HA version; otherwise leave it unchanged.

4. **lovelace_dashboard.yaml** — if any sensor attributes were added, renamed, or removed in this version, update the relevant markdown card templates. If nothing changed in the data model, leave the file untouched.

5. Confirm all four files are consistent and summarise what was changed.

The GitHub Actions workflow in `.github/workflows/release.yml` will automatically create the release tag and extract the README changelog as release notes when this is pushed to main — no manual tag or release needed.

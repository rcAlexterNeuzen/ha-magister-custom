# Magister — Home Assistant Custom Integration

Integreert **Magister** schoolinformatie in Home Assistant. Toont het rooster als kalender en biedt sensoren voor cijfers, huiswerk en roosterwijzigingen.

Werkt met **ouder- én leerlingaccounts** en ondersteunt **MFA (tweestapsverificatie)** — inclusief accounts waarbij je de base32-sleutel niet hebt, door de 6-cijferige code in te voeren bij het inloggen.

---

## Wat doet het?

### Sensoren (per leerling)

| Entity | Status | Attributen |
|--------|--------|------------|
| `sensor.magister_<naam>` | Aantal lessen vandaag | Naam, lessen vandaag, huiswerk, wijzigingen, laatste cijfer, volgende afspraak, **uitval_vandaag** (lijst van uitgevallen lessen vandaag) |
| `sensor.magister_<naam>_next_appointment` | Datum/tijd volgende les | Vak, locatie, type, start, einde |
| `sensor.magister_<naam>_grades` | Meest recente cijfer | Laatste 10 cijfers met vak, omschrijving, weging en datum |
| `sensor.magister_<naam>_homework` | Aantal huiswerkopdrachten | Lijst van huiswerk (vak, start, omschrijving) |
| `sensor.magister_<naam>_schedule_changes` | Aantal roosterwijzigingen | Lijst van wijzigingen (vak, start, einde, locatie) |

### Kalender

| Entity | Beschrijving |
|--------|-------------|
| `calendar.magister_<naam>_rooster` | Volledig rooster in de HA Agenda-kaart — lessen, huiswerk en uitval zichtbaar |

---

## Installatie

### Stap 1 — Kopieer de bestanden

Kopieer de map `magister_custom` naar je Home Assistant configuratiemap:

```
/config/custom_components/magister_custom/
├── __init__.py
├── auth.py
├── calendar.py
├── config_flow.py
├── const.py
├── coordinator.py
├── manifest.json
├── sensor.py
└── strings.json
```

### Stap 2 — Herstart Home Assistant

### Stap 3 — Voeg de integratie toe

1. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen**
2. Zoek naar **Magister**
3. Vul je gegevens in (zie hieronder)

---

## Configuratie

| Veld | Verplicht | Uitleg |
|------|-----------|--------|
| **Schoolnaam** | Ja | Het subdomein van je school, bijv. `ovozaanstad` voor `ovozaanstad.magister.net`. Spaties en de volledige URL worden automatisch verwerkt. |
| **Gebruikersnaam** | Ja | Je Magister-gebruikersnaam |
| **Wachtwoord** | Ja | Je Magister-wachtwoord |
| **TOTP-geheim** | Nee | Alleen invullen als je de base32-sleutel hebt uit je authenticator-app (ziet eruit als `JBSWY3DPEHPK3PXP`). Laat leeg als je dit niet hebt. |

### MFA (tweestapsverificatie)

Als je account beveiligd is met MFA en je **geen** base32-sleutel hebt:

1. Laat het TOTP-geheim-veld **leeg**
2. Klik op **Verzenden**
3. Er verschijnt automatisch een tweede scherm: **"MFA-verificatie"**
4. Open je authenticator-app (bijv. Google Authenticator of Microsoft Authenticator)
5. Voer de **huidige 6-cijferige code** in — doe dit snel, de code is 30 seconden geldig

> **Let op:** wanneer de sessie later verloopt (typisch na enkele uren/dagen), toont Home Assistant een melding *"Opnieuw authenticeren vereist"*. Klik daarop en voer je wachtwoord en een nieuwe 6-cijferige code in.

Als je wél de base32-sleutel hebt, vul die in bij **TOTP-geheim** en logt de integratie volledig automatisch opnieuw in zonder tussenkomst.

---

## Entiteiten

Na de installatie worden voor **elke leerling** de volgende entiteiten aangemaakt (waarbij `<naam>` de voor- en achternaam is):

```
sensor.magister_<naam>
sensor.magister_<naam>_next_appointment
sensor.magister_<naam>_grades
sensor.magister_<naam>_homework
sensor.magister_<naam>_schedule_changes
calendar.magister_<naam>_rooster
```

Bij een **ouderaccount** worden entiteiten aangemaakt voor elk gekoppeld kind.  
Bij een **leerlingaccount** worden entiteiten aangemaakt voor de ingelogde leerling zelf.

---

## Meegeleverde bestanden

| Bestand | Beschrijving |
|---------|-------------|
| `custom_components/magister_custom/` | De integratie zelf |
| `lovelace_dashboard.yaml` | Kant-en-klaar Lovelace dashboard |
| `ha-automations/magister_notifications.yaml` | Notificatie-automatiseringen |

---

## Automatiseringen

De automatiseringen staan kant-en-klaar in `ha-automations/magister_notifications.yaml`.

### Beschikbare automatiseringen

| Automatisering | Trigger | Beschrijving |
|---|---|---|
| **Nieuw cijfer** | State change grades sensor | Melding met cijfer, vak, weging en omschrijving. Groen 🟢 bij voldoende, rood 🔴 bij onvoldoende. |
| **Uitval in roosterwijzigingen** | State change schedule_changes sensor | Melding wanneer een wijziging "uitval" bevat in vak of omschrijving. |
| **Ochtendscheck uitval 08:00** | Tijdtrigger 08:00 | Controleert of een les vanaf 08:30 als uitgevallen is gemarkeerd (`uitval_vandaag` attribuut). |

### Installeren

Voeg toe aan `configuration.yaml`:

```yaml
automation: !include_dir_merge_list automations/
```

Kopieer vervolgens `ha-automations/magister_notifications.yaml` naar je `automations/` map.

Of plak de inhoud rechtstreeks in je bestaande `automations.yaml`.

> De automatiseringen gebruiken `notify.mobile_app_iphone16plus` — pas dit aan naar je eigen notify-service.

---

## Lovelace dashboard

Het bestand `lovelace_dashboard.yaml` bevat een kant-en-klaar dashboard met de volgende kaarten:

| Kaart | Inhoud |
|-------|--------|
| **Vandaag** | Lessen, huiswerkaantal, wijzigingen, laatste cijfer |
| **Volgende les** | Vak, locatie, tijdstip |
| **Aankomend huiswerk** | Huiswerk de komende 14 dagen, gesorteerd op datum |
| **Cijfers afgelopen week** | Cijfers van de laatste 7 dagen met 🟢/🔴 indicator |
| **Recente cijfers (laatste 10)** | Overzicht van de 10 meest recente cijfers |
| **Roosterwijzigingen** | Uitval en wijzigingen |
| **Roosterkalender** | HA kalenderweergave |

### Toevoegen aan Home Assistant

1. Ga naar **Instellingen → Dashboards → Dashboard toevoegen**
2. Kies **Leeg dashboard** en open het in YAML-modus (drie puntjes → YAML bewerken)
3. Plak de inhoud van `lovelace_dashboard.yaml`

> De entiteitnamen in het dashboard zijn afgestemd op de leerling `lieke_neuzen`. Pas de slug aan als je een andere leerling gebruikt.

---

## Database-optimalisatie

De sensoren kunnen veel data bevatten. Voeg dit toe aan `configuration.yaml` om databasegroei te beperken:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.magister_*
```

Of selectief:

```yaml
recorder:
  exclude:
    entities:
      - sensor.magister_jan_grades
      - sensor.magister_jan_homework
```

---

## Problemen oplossen

**`cannot_connect`** — Controleer de schoolnaam. Probeer het subdomein zonder spaties, bijv. `ovozaanstad`. Je kunt ook de volledige URL invullen: `https://ovozaanstad.magister.net`.

**`invalid_auth`** — Gebruikersnaam of wachtwoord onjuist. Probeer eerst in te loggen via de browser op `https://<school>.magister.net`.

**`totp_failed`** — De 6-cijferige code was verlopen. Voer de code in zodra hij verschijnt; hij is maar 30 seconden geldig.

**Geen entities zichtbaar** — Herstart Home Assistant en controleer **Instellingen → Apparaten & Diensten** of de integratie actief is.

**Logs bekijken** — Voeg het volgende toe aan `configuration.yaml` voor gedetailleerde logging:

```yaml
logger:
  logs:
    custom_components.magister_custom: debug
```

Ga daarna naar **Ontwikkelaarstools → Logboek** en zoek op `magister`.

---

## Disclaimer

Deze integratie is niet officieel geassocieerd met Schoolmaster BV / Magister. Gebruik op eigen risico. Zorg dat je voldoet aan de gebruiksvoorwaarden van Magister.

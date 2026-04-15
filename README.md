# Magister — Home Assistant Custom Integration

Integreert **Magister** schoolinformatie in Home Assistant. Toont het rooster als kalender en biedt sensoren voor cijfers, huiswerk en roosterwijzigingen.

Werkt met **ouder- én leerlingaccounts** en ondersteunt **MFA (tweestapsverificatie)** — inclusief accounts waarbij je de base32-sleutel niet hebt, door de 6-cijferige code in te voeren bij het inloggen.

---

## Wat doet het?

### Sensoren (per leerling)

| Entity | Status | Attributen |
|--------|--------|------------|
| `sensor.magister_<naam>` | Aantal lessen vandaag | Naam, lessen vandaag, huiswerk, wijzigingen, laatste cijfer, volgende afspraak |
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

## Automatiseringen

### Melding bij nieuw cijfer

```yaml
automation:
  - alias: "Nieuw Magister-cijfer"
    trigger:
      - platform: state
        entity_id: sensor.magister_jan_grades
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state != trigger.from_state.state }}"
    action:
      - service: notify.mobile_app_telefoon
        data:
          title: "Nieuw cijfer voor {{ state_attr('sensor.magister_jan_grades', 'cijfers')[0].subject }}"
          message: "{{ states('sensor.magister_jan_grades') }}"
```

### Herinnering bij huiswerk

```yaml
automation:
  - alias: "Huiswerk herinnering"
    trigger:
      - platform: time
        at: "18:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.magister_jan_homework
        above: 0
    action:
      - service: notify.mobile_app_telefoon
        data:
          message: >
            Nog {{ states('sensor.magister_jan_homework') }} huiswerk items.
            Eerst: {{ state_attr('sensor.magister_jan_homework', 'huiswerk')[0].subject }}
```

### Melding bij uitval

```yaml
automation:
  - alias: "Roosterwijziging Magister"
    trigger:
      - platform: state
        entity_id: sensor.magister_jan_schedule_changes
    condition:
      - condition: numeric_state
        entity_id: sensor.magister_jan_schedule_changes
        above: 0
    action:
      - service: notify.mobile_app_telefoon
        data:
          message: "Er is een roosterwijziging voor Jan."
```

---

## Lovelace-kaart

Voeg snel het rooster toe aan je dashboard:

```yaml
type: calendar
entities:
  - calendar.magister_jan_rooster
```

Cijfers en huiswerk als entiteitenkaart:

```yaml
type: entities
title: Magister Jan
entities:
  - sensor.magister_jan
  - sensor.magister_jan_next_appointment
  - sensor.magister_jan_grades
  - sensor.magister_jan_homework
  - sensor.magister_jan_schedule_changes
```

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

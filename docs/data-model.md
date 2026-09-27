# Dátový model – fáza 1 (návrh na odsúhlasenie)

Stav: návrh (2026-09-27). Pokrýva fázu 1 (administrácia). Tabuľky pre eCP, platby a portál pribudnú
v ďalších fázach.

Konvencie:
- Primárne kľúče sú UUID (neprezrádzajú počet členov ani poradie).
- Stĺpce s koncovkou `_enc` sú šifrované (AES-GCM, `ess/security/crypto.py`). Databáza vidí len nečitateľné bajty.
- Stĺpce s koncovkou `_bidx` sú blind indexy (HMAC) na presné vyhľadanie.
- Každá tabuľka má `created_at`, `updated_at`; každá zmena ide do `audit_log`.
- História sa nemaže: zmena stavu = ukončenie platného záznamu (`valid_to`) + nový záznam.

## Skupiny

**`clubs`** – skupiny SSS (jaskyniarske aj oblastné skupiny sa v IS nerozlišujú, líšia sa len názvom).
Nie sú to osobné údaje, ukladajú sa čitateľne.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `name` | text | celý názov, jedinečný |
| `short_name` | text | skratka na preukaz |
| `is_unaffiliated` | bool | predvolený klub **„SSS – nezaradení“** pre členov bez skupiny (práve jeden, viď nižšie) |
| `uses_candidates` | bool | skupina používa čakateľský status |
| `active` | bool | zaniknutá skupina sa nemaže, len deaktivuje |

Klub **„SSS – nezaradení“**:
- vytvorí ho migrácia; nedá sa zmazať ani deaktivovať,
- nemá vlastného predsedu – spravuje ho poverená osoba (rola `staff`) alebo systémový administrátor,
- jeho členovia nemajú rovnaké práva ako členovia skupín (napr. nemajú zástupcu na valnom
  zhromaždení); systém ho preto nepočíta medzi skupiny pri predsedníctve a podobných prehľadoch.

## Členovia

**`members`** – identita člena. Osobné údaje sú šifrované.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `first_name_enc`, `last_name_enc` | bytes | |
| `title_before_enc`, `title_after_enc` | bytes | tituly (Ing., PhD.) – viď otázka 3 |
| `birth_date_enc` | bytes | voliteľné pri importe; bez neho sa nedá požiadať o eCP |
| `email_enc` | bytes | voliteľné pri importe; bez neho sa nedá požiadať o eCP |
| `address_enc` | bytes | bydlisko, voliteľné |
| `phone_enc` | bytes | voliteľné (kontakt predsedu na overovacej stránke) |
| `lookup_bidx` | bytes | HMAC(meno, priezvisko, rok narodenia) – vyhľadanie pri žiadosti o eCP |
| `email_bidx` | bytes | HMAC(e-mail) – kontrola, že e-mail nepoužíva iný člen |
| `reduced_fee` | bool | zľavnené členské (R13) |
| `expelled_at`, `expelled_reason` | date, text | vylúčenie zo SSS; potom sa nedá vytvoriť žiadne členstvo |

Dôsledok šifrovania: databáza nevie zoradiť ani vyhľadať podľa mena. Zoznamy sa preto dešifrujú
a zoraďujú v aplikácii. Pri približne 1 000 členoch to nie je problém.

## Členstvá v skupinách

**`memberships`** – člen × skupina × obdobie.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `member_id`, `club_id` | uuid | |
| `status` | enum | `candidate`, `pending_activation`, `member`, `suspended`, `terminated` |
| `is_primary` | bool | |
| `valid_from`, `valid_to` | date | `valid_to` prázdne = platný záznam |
| `created_by`, `activated_by`, `activated_at` | | kto zadal, kto a kedy aktivoval |
| `note` | text | bez osobných údajov |

Pravidlá (kontroluje aplikácia a tam, kde sa dá, aj databáza):
- Člen má najviac **jedno platné členstvo v danej skupine**.
- Člen s aspoň jedným platným členstvom má **práve jedno primárne**.
- Vylúčenému členovi sa nedá vytvoriť ani obnoviť členstvo.
- Nezaradený člen má členstvo v klube „SSS – nezaradení“.
- Predseda skupiny môže vytvoriť `candidate` a `pending_activation`. Stav `member` nastavuje používateľ
  s administratívnym prístupom (`staff` alebo `system_admin`) (R14).

## Organizačná štruktúra

Organizačná štruktúra eviduje funkcie v SSS. **Nedáva prístup do administrácie IS**: ten je oddelený,
viď sekcia Administratívny prístup.

**`org_positions`** – číselník funkcií (napĺňa migrácia):
`sss_chair` (predseda SSS), `sss_vice_chair` (podpredseda), `board_member` (člen výboru),
`audit_chair` a `audit_member` (predseda a člen kontrolnej komisie), `club_chair` (predseda skupiny,
viazaný na skupinu; nie pre klub „SSS – nezaradení“).

**`position_holders`** – kto zastáva funkciu a kedy.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `position_code` | text | odkaz na `org_positions` |
| `member_id` | uuid | držiteľ musí byť člen SSS |
| `club_id` | uuid | len pri `club_chair` |
| `valid_from`, `valid_to` | date | volebné obdobie |

- V jednom čase môže byť len jeden predseda SSS a jeden predseda v každej skupine. Zadanie nového
  predsedu automaticky ukončí funkciu predchádzajúceho.
- Predsedníctvo sa neukladá, zostaví sa z platných funkcií.
- Z funkcie sa odvodzuje jediné oprávnenie: **predseda skupiny spravuje na portáli svoju skupinu**
  (prihlásenie cez eCP). Po voľbách v skupine to teda platí automaticky.
- Funkcie slúžia aj na zobrazenie kontaktov (predseda skupiny a predseda SSS na overovacej stránke).
- Budúcnosť (približne o 3,5 roka): dočasná rola **delegát** – osoba poverená skupinou na účasť
  a hlasovanie na valnom zhromaždení. Slovo „delegát“ sa preto inde v IS nepoužíva.

## Administratívny prístup

Prístup do administrácie IS **nie je viazaný na členstvo, eCP ani funkciu**. Prihlasuje sa Google účtom
a udeľuje ho systémový administrátor. Poverená osoba nemusí byť členom SSS (často je to platená osoba).
Nový predseda SSS dostane prístup až vtedy, keď mu ho udelí systémový administrátor.

**`admin_users`** – Google účty s prístupom do administrácie.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `display_name_enc` | bytes | meno na zobrazenie v administrácii |
| `google_email_bidx` | bytes | HMAC(e-mail), na vyhľadanie pri prihlásení |
| `google_email_enc` | bytes | na zobrazenie v zozname používateľov |
| `role` | enum | `system_admin` / `staff` |
| `active` | bool | odobratie prístupu = deaktivácia (história v audite zostáva) |
| `granted_by`, `granted_at` | | kto a kedy prístup udelil |

Roly:
- **`system_admin` – systémový administrátor:** všetko, vrátane udeľovania a odoberania prístupov
  a systémových nastavení. Dvaja hlavní systémoví administrátori sú v premennej `ESS_SUPER_ADMIN_EMAILS`
  a z aplikácie sa odobrať nedajú.
- **`staff` – poverená osoba:** evidencia členov a skupín, aktivácia členov, opravy údajov, klub
  „SSS – nezaradení“, spracovanie žiadostí o eCP, nahrávanie bankových výpisov. Nemôže spravovať
  prístupy ani systémové nastavenia.

| Oprávnenie | Kto ho má |
|---|---|
| Prístupy do administrácie, systémové nastavenia | `system_admin` |
| Evidencia členov a skupín, aktivácia členov, klub „SSS – nezaradení“ | `staff`, `system_admin` |
| Správa vlastnej skupiny na portáli | predseda skupiny (z funkcie `club_chair`) |

## Certifikáty

**`certificate_types`** – číselník (SRT1, SRT2, záchranár, hasič, …), dá sa rozširovať v administrácii.

**`member_certificates`** – `member_id`, `certificate_type_id`, `valid_from`, `valid_to`, `note`.

## Nastavenia a dokumenty

**`settings`** – kľúč/hodnota: `fee_amount` (15.00), `reduced_fee_amount`, `reduced_fee_age` (60/62),
`fee_currency` (EUR). Zmena sa zapisuje do auditu.

**`documents`** – `title`, `url`, `valid_until` (voliteľné), `sort_order`.

## Otázky na odsúhlasenie

1. ~~Prihlásenie predsedu SSS a poverených osôb~~ – vyriešené: administratívny prístup je oddelený
   od organizačnej štruktúry (Google účet, udeľuje systémový administrátor).
2. **Evidenčné číslo člena.** Majú členovia SSS dnes číslo (napríklad číslo papierového preukazu),
   ktoré treba zachovať a zobraziť na eCP? Ak nie, systém pridelí nové poradové číslo.
3. **Tituly** (Ing., PhD.) – evidovať a zobraziť ich na eCP a kartičke?
4. **Telefón** – evidovať? Hodil by sa ako kontakt na predsedu skupiny na overovacej stránke.
5. **Overovacia stránka** (otázka z plánu): zobraziť len meno, fotku a skupinu?
6. **Povýšenie čakateľa na člena** (otázka z plánu): má tiež čakať na aktiváciu používateľom
   s administratívnym prístupom? (návrh: áno)
7. **Pozastavené členstvo** – môže ho predseda skupiny obnoviť sám, alebo to znova vyžaduje aktiváciu?

# Dátový model – fáza 1 (návrh na odsúhlasenie)

Stav: implementované (migrácie `0002`–`0005`, 2026-09-28). Pokrýva fázu 1 (administrácia). Tabuľky pre eCP, platby a portál pribudnú
v ďalších fázach.

Konvencie:
- Primárne kľúče sú UUID (neprezrádzajú počet členov ani poradie).
- Stĺpce s koncovkou `_enc` sú šifrované (AES-GCM, `ess/security/crypto.py`). Databáza vidí len nečitateľné bajty.
- Stĺpce s koncovkou `_bidx` sú blind indexy (HMAC) na presné vyhľadanie.
- Každá tabuľka má `created_at`, `updated_at`; každá zmena ide do `audit_log`.
- História sa nemaže: zmena stavu = ukončenie platného záznamu (`valid_to`) + nový záznam.
- `valid_to` je **prvý deň, keď záznam už neplatí** (pri zmene v ten istý deň: starý `valid_to` = nový `valid_from`).

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
- nemá vlastného predsedu – spravuje ho administrátor,
- jeho členovia nemajú rovnaké práva ako členovia skupín (napr. nemajú zástupcu na valnom
  zhromaždení); systém ho preto nepočíta medzi skupiny pri predsedníctve a podobných prehľadoch.

## Členovia

**`members`** – identita člena. Osobné údaje sú šifrované.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `first_name_enc`, `last_name_enc` | bytes | |
| `title_before_enc`, `title_after_enc` | bytes | tituly (Ing., PhD.) – zobrazujú sa na eCP a kartičke |
| `card_number_enc`, `card_number_bidx` | bytes | číslo papierového preukazu, voliteľné, dopĺňa sa ručne; jedinečné |
| `member_since` | date | člen SSS od (pri importe z papierovej evidencie ručne); zobrazuje sa pri overení |
| `birth_date_enc` | bytes | voliteľné pri importe; bez neho sa nedá požiadať o eCP |
| `email_enc` | bytes | voliteľné pri importe; bez neho sa nedá požiadať o eCP; **nie je jedinečný** (manželia) |
| `address_enc` | bytes | bydlisko, voliteľné |
| `phone_enc` | bytes | voliteľné; telefón predsedu skupiny a predsedu SSS sa zobrazuje na overovacej stránke |
| `lookup_bidx` | bytes | HMAC(meno, priezvisko, rok narodenia) – vyhľadanie pri žiadosti o eCP |
| `email_bidx` | bytes | HMAC(e-mail) – nie jedinečný; zobrazenie, kto e-mail zdieľa; člena nikdy neidentifikuje sám |
| `reduced_fee` | bool | zľavnené členské (R13) |
| `expelled_at`, `expelled_reason` | date, text | vylúčenie zo SSS; potom sa nedá vytvoriť žiadne členstvo |
| `sss_ended_at`, `sss_ended_note` | date, text | členstvo v SSS ukončené rozhodnutím predsedníctva (nie vylúčenie – dá sa obnoviť) |

Dôsledok šifrovania: databáza nevie zoradiť ani vyhľadať podľa mena. Zoznamy sa preto dešifrujú
a zoraďujú v aplikácii. Pri približne 1 000 členoch to nie je problém.

## Členstvá v skupinách

**`memberships`** – člen × skupina × obdobie.

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `member_id`, `club_id` | uuid | |
| `status` | enum | `candidate`, `pending_activation`, `member`, `suspended` |
| `is_primary` | bool | |
| `valid_from`, `valid_to` | date | `valid_to` prázdne = platný záznam |
| `end_reason` | enum | pri ukončenom zázname: `status_change`, `terminated` (ukončenie členstva), `expelled` |
| `created_by`, `activated_by`, `activated_at` | | kto zadal, kto a kedy aktivoval |
| `note` | text | bez osobných údajov |

Pravidlá (kontroluje aplikácia a tam, kde sa dá, aj databáza):
- Člen má najviac **jedno platné členstvo v danej skupine**.
- Člen s aspoň jedným platným členstvom má **práve jedno primárne**.
- Vylúčenému členovi sa nedá vytvoriť ani obnoviť členstvo.
- Nezaradený člen má členstvo v klube „SSS – nezaradení“.
- Povýšenie čakateľa na člena tiež prechádza cez `pending_activation`.
- Predseda skupiny môže vytvoriť `candidate` a `pending_activation`. Stav `member` nastavuje administrátor
  (R14).
- Ak sa ukončí primárne členstvo, primárnym sa automaticky stane najstaršie zostávajúce. Primárnu skupinu
  inak mení administrátor.

Povolené zmeny stavu:

| Z → Do | Kto |
|---|---|
| čakateľ → navrhnutý člen (`pending_activation`) | predseda skupiny, administrátor |
| navrhnutý člen → čakateľ (stiahnutie návrhu) | predseda skupiny, administrátor |
| čakateľ / navrhnutý člen → člen (aktivácia) | administrátor |
| člen → pozastavený | predseda skupiny, administrátor |
| pozastavený → člen (obnovenie) | predseda skupiny, administrátor |
| ukončenie členstva v skupine | predseda skupiny, administrátor |
| vylúčenie zo SSS (na základe rozhodnutia valného zhromaždenia) | administrátor |

Vylúčenie ukončí všetky členstvá a funkcie člena; vylúčenému sa už nedá vytvoriť ani obnoviť členstvo.

## Členstvo v SSS

Členstvo v SSS sa neukladá samostatne, odvodzuje sa zo skupín:

| Stav | Kedy |
|---|---|
| člen SSS | má aspoň jedno platné členstvo v skupine (aj v „SSS – nezaradení“) |
| čaká na rozhodnutie | ukončil členstvo v poslednej skupine; administrátor vidí zoznam takýchto členov |
| členstvo v SSS ukončené | predsedníctvo rozhodlo (napr. už nechce byť jaskyniarom); **dá sa obnoviť** |
| vylúčený | rozhodnutie valného zhromaždenia; **nedá sa obnoviť** |

- Ukončenie členstva v skupine (na žiadosť člena alebo vylúčenie zo skupiny) platí **len pre skupinu**.
- O tom, či zaniká aj členstvo v SSS, rozhodne predseda SSS alebo predsedníctvo; do IS to zapíše administrátor.
- Ak sa člen obráti na predsedníctvo, administrátor ho zaradí do „SSS – nezaradení“ – aj vtedy, keď už
  mal členstvo v SSS ukončené. Pri novom členstve sa ukončenie zruší (história zostáva v audite).

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
  (prihlásenie cez eCP).
- **Zmenu predsedu skupiny zadáva len administrátor**, až po doručení dokumentov (zvyčajne z výročnej
  schôdze skupiny). Dovtedy má oprávnenia starý predseda. Zmena sa týka len danej skupiny a dá sa vrátiť.
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
| `role` | enum | `system_admin` / `admin` |
| `active` | bool | odobratie prístupu = deaktivácia (história v audite zostáva) |
| `granted_by`, `granted_at` | | kto a kedy prístup udelil |

Roly:
- **`system_admin` – systémový administrátor:** všetko, vrátane udeľovania a odoberania prístupov
  a systémových nastavení. Dvaja hlavní systémoví administrátori sú v premennej `ESS_SUPER_ADMIN_EMAILS`
  a z aplikácie sa odobrať nedajú.
- **`admin` – administrátor** (jednotný názov pre predsedu SSS alebo poverenú osobu s povolením na
  zmeny v IS; nemusí byť členom SSS): evidencia členov a skupín, aktivácia členov, opravy údajov, klub
  „SSS – nezaradení“, spracovanie žiadostí o eCP, nahrávanie bankových výpisov. Nemôže spravovať
  prístupy ani systémové nastavenia.

| Oprávnenie | Kto ho má |
|---|---|
| Prístupy do administrácie, systémové nastavenia | `system_admin` |
| Evidencia členov a skupín, aktivácia členov, klub „SSS – nezaradení“ | `admin`, `system_admin` |
| Zmena funkcií (predsedovia skupín, orgány SSS) | `admin`, `system_admin` |
| Správa vlastnej skupiny na portáli | predseda skupiny (z funkcie `club_chair`) |

## Požiadavky

Všetko, čo čaká na administrátora, je v jednom zozname **„Požiadavky“** (tabuľka `tasks`). Požiadavky
vznikajú a uzatvárajú sa automaticky v tej istej transakcii ako zmena, ktorej sa týkajú – zoznam preto
vždy zodpovedá dátam, aj keď administrátor vybaví vec inde (napr. aktivuje člena v jeho detaile).

| Stĺpec | Typ | Poznámka |
|---|---|---|
| `id` | uuid | |
| `task_type` | text | typ požiadavky (viď nižšie); text namiesto DB enumu, aby sa dali pridávať nové typy |
| `status` | text | `open`, `done`, `rejected`, `cancelled` (vec sa medzitým zmenila, napr. vylúčenie) |
| `member_id`, `membership_id`, `club_id` | uuid | čoho sa požiadavka týka |
| `context` | jsonb | doplňujúce údaje bez osobných údajov, napr. `{"from_status": "candidate"}` |
| `requested_by`, `created_at` | | kto a kedy požiadavku vyvolal (napr. predseda skupiny) |
| `resolved_by`, `resolved_at`, `resolution`, `resolution_note` | | kto, kedy a ako ju vybavil (napr. dôvod zamietnutia) |

Typy požiadaviek:

| Typ | Vzniká | Akcie |
|---|---|---|
| Aktivácia člena (`member_activation`) | predseda navrhne nového člena alebo povýšenie čakateľa | aktivovať / zamietnuť s dôvodom (čakateľ zostane čakateľom, návrh nového člena sa ukončí) |
| Rozhodnutie o členstve v SSS (`sss_decision`) | člen ukončil členstvo vo všetkých skupinách | zaradiť do „SSS – nezaradení“ / ukončiť členstvo v SSS |
| Vydanie eCP (fáza 2) | žiadosť o eCP | schváliť / zamietnuť (napr. nevyhovujúca fotka) |

V jednom čase môže byť otvorená najviac jedna aktivácia na členstvo a jedno rozhodnutie na člena.

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
2. ~~Evidenčné číslo~~ – voliteľné pole `card_number` (číslo papierového preukazu), dopĺňa sa ručne.
3. ~~Tituly~~ – áno, evidujú sa a zobrazujú na eCP a kartičke.
4. ~~Telefón~~ – áno, pri overení člena je žiaduci.
5. ~~Overovacia stránka~~ – vyriešené, viď `docs/PLAN.md` sekcia 5a (jednorazový QR).
6. ~~Povýšenie čakateľa na člena~~ – áno, vyžaduje aktiváciu administrátorom (doklady zvyčajne po
   výročnej schôdzi skupiny).
7. ~~Pozastavené členstvo~~ – obnoví ho predseda skupiny sám; vylúčiť zo SSS môže len administrátor na
   základe rozhodnutia valného zhromaždenia.

## Vyriešené otázky z implementácie

1. Ukončenie členstva v skupine platí len pre skupinu; o členstve v SSS rozhoduje predsedníctvo
   (viď sekcia Členstvo v SSS).
2. Zľavnené členské: 7,00 € (`reduced_fee_amount`).
3. Vek pre zľavu: 62 rokov (`reduced_fee_age`).

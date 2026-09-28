# Dátový model – fáza 2: eCP a kartička (návrh na odsúhlasenie)

Stav: návrh. Nadväzuje na `docs/data-model.md` (rovnaké konvencie: UUID, `_enc` šifrované, `_bidx` blind index,
audit, história sa nemaže). Pravidlá: R18, R22–R26 v `docs/PLAN.md`.

## Tokeny v odkazoch

`one_time_tokens` – jednorazové odkazy v e-mailoch (overenie e-mailu, doplnenie fotky nového člena).

| Stĺpec | Význam |
|---|---|
| `token_hash` | SHA-256 tokenu; samotný token je len v odkaze, v DB nie je |
| `purpose` | `email_verify`, `ecp_photo` |
| `application_id` | ku ktorej žiadosti patrí |
| `expires_at`, `used_at` | platnosť (napr. 24 h) a použitie (raz) |

## Žiadosti o eCP

`ecp_applications` – jedna tabuľka pre obe cesty:
- **verejná žiadosť** (`source = public`) existujúceho člena (R22),
- **nový člen od predsedu** (`source = club_chair`, R23) – po aktivácii dostane e-mail s odkazom na fotku.

| Stĺpec | Význam |
|---|---|
| `source` | `public` / `club_chair` |
| `status` | `email_pending` → `photo_pending` → `submitted` → `approved` / `rejected`; ďalej `expired`, `cancelled` |
| `member_id` | vyplní sa po presnej zhode s evidenciou (pri `club_chair` hneď) |
| `first_name_enc`, `last_name_enc`, `birth_date_enc`, `email_enc`, `card_number_enc`, `member_since_enc`, `club_id` | údaje zo žiadosti (šifrované); chýbajúce údaje sa do člena uložia až po schválení |
| `photo_original` | názov originálu v buckete (aby mohol administrátor fotku orezať znova); po rozhodnutí sa zmaže |
| `photo_cropped` | názov orezanej fotky (64 náhodných znakov) |
| `wants_wallet`, `wants_card` | eCP v Google Wallet a/alebo PDF kartička |
| `reject_reason` | dôvod zamietnutia (text pre žiadateľa, bez osobných údajov) |
| `email_verified_at`, `submitted_at`, `decided_at`, `decided_by` | priebeh |

Počas stavu `submitted` je otvorená požiadavka **„Vydanie eCP“** (`tasks`, typ `ecp_issue`).
Administrátor v nej vidí fotku, môže ju znova orezať z originálu, schváliť alebo zamietnuť s dôvodom.

**Ochrana pred zisťovaním členov:** po odoslaní formulára sa vždy zobrazí rovnaká správa („ak údaje
zodpovedajú evidencii, príde vám e-mail; ak nepríde do 15 minút, kontaktujte predsedu skupiny“).
E-mail sa pošle len vtedy, keď e-mail zodpovedá členovi v evidencii. Tak sa nedá zistiť, kto je členom,
ani posielať e-maily na cudzie adresy. Počet žiadostí je obmedzený (na IP adresu a na e-mail za deň).

## Súhlasy

`consents` – člen, druh (`gdpr_ecp`, `notifications`), verzia textu, kedy, zdroj (žiadosť alebo papierová
prihláška u predsedu). Odvolanie = nový záznam, nič sa nemaže.

## Vydané eCP

`ecp_passes` – eCP v Google Wallet.

| Stĺpec | Význam |
|---|---|
| `member_id` | najviac jeden neukončený eCP na člena |
| `wallet_object_id` | `3388000000022877308.<náhodné id>` – bez osobných údajov |
| `state` | `active`, `inactive` (pozastavenie), `revoked` (vylúčenie / odchod zo SSS, R25) |
| `photo` | názov fotky v buckete; pri `revoked` sa fotka zmaže |
| `application_id`, `issued_at`, `revoked_at` | pôvod a priebeh |

## Kartička SSS

`sss_cards` – PDF kartička na jeden kalendárny rok.

| Stĺpec | Význam |
|---|---|
| `member_id`, `year` | pre koho a na ktorý rok (najviac jedna platná na člena a rok) |
| `code_hash` | SHA-256 kódu z QR kartičky |
| `issued_at`, `issued_by`, `revoked_at` | kto a kedy ju vydal (žiadosť, administrátor, predseda) |

## QR a overovanie (R18)

`verification_tokens` – tokeny v QR eCP.

| Stĺpec | Význam |
|---|---|
| `pass_id` | ku ktorému eCP patrí |
| `token_hash` | SHA-256 tokenu |
| `created_at`, `first_used_at` | po prvom použití platí token ešte 15 minút, potom sa vydá nový QR |

Denný limit nových QR na eCP je v nastaveniach. Token zrušeného eCP vedie na výstražnú stránku (R25).
Kartička má jediný kód na rok (`sss_cards.code_hash`); ten sa nemení.

## Otázky na odsúhlasenie

1. Porovnáva sa v žiadosti **celý dátum narodenia**, alebo len rok? Návrh: celý dátum (je aj na preukaze).
2. Platnosť odkazu v e-maile: 24 hodín. Nedokončená žiadosť sa po 14 dňoch označí ako `expired`.

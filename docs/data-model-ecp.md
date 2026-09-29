# Dátový model – fáza 2: eCP a kartička

Stav: tabuľky implementované (migrácia `0008`, 2026-09-28), služby a obrazovky pribúdajú. Nadväzuje na `docs/data-model.md` (rovnaké konvencie: UUID, `_enc` šifrované, `_bidx` blind index,
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
Hotové (krok 1): formulár `/ecp/apply`, presná zhoda (`ess/services/ecp_applications.py`), e-mail s odkazom
`/ecp/email/<token>`, prepadnutie nedokončených žiadostí. Nová žiadosť nahradí nedokončenú.
Hotové (krok 2): `/ecp/apply/photo` – fotka s orezom v prehliadači (`ess/static/crop.js`, pomer 220:300,
bez JavaScriptu automatický výrez), súhlasy (verzia textu `2026-1`), voľba kartičky → stav `submitted`
a požiadavka „Vydanie eCP“. Originál (`originals/`) a portrét 440×600 (`photos/`) majú 64-znakové náhodné názvy.
Hotové (krok 3): posúdenie `/admin/ecp-applications/<id>` (porovnanie s evidenciou, nový výrez fotky, zamietnutie
s dôvodom a e-mailom, schválenie). Schválenie doplní chýbajúce číslo preukazu a „člen od“, vytvorí `ecp_passes`,
QR token a objekt v Google Wallet (`ess/wallet.py`) a pošle e-mail s tlačidlom „Pridať do Peňaženky Google“.
Hotové (krok 4): overovacia stránka `/v/<token>` (`ess/services/ecp_verification.py`) – výsledok (člen / pozastavené /
nie je člen / kód použitý / neplatný), fotka, meno, bydlisko, skupina, člen od, kontakty na predsedu skupiny a SSS,
platné dokumenty; stránka sa neukladá do cache ani neindexuje. Jednorazový QR: prvé naskenovanie vydá nový token
a aktualizuje QR v Google Wallet; ak to nejde (denný limit, chyba Wallet), token sa nespotrebuje.
Hotové (krok 5, R25): stav eCP sa prepočíta automaticky pri každej zmene člena alebo členstva
(`ess/services/ecp_state.py`, udalosti SQLAlchemy) a po uložení sa odošle do Google Wallet (aktívny / neaktívny;
zrušený pri vylúčení = EXPIRED bez osobných údajov a fotky). Neodoslaná zmena sa skúsi pri ďalšej akcii administrátora;
v detaile člena je stav eCP.
Zostáva: stav členského (fáza 3), kartička PDF, cesta nového člena (R23).
E-mail sa pošle len vtedy, keď e-mail zodpovedá členovi v evidencii. Tak sa nedá zistiť, kto je členom,
ani posielať e-maily na cudzie adresy. Počet žiadostí je obmedzený na 3 za deň na e-mail (obmedzenie podľa IP adresy zatiaľ nie je) a formulár má
skryté pole proti robotom.

## Súhlasy

`consents` – člen, druh (`gdpr_ecp`, `notifications`), verzia textu, kedy, zdroj (žiadosť alebo papierová
prihláška u predsedu). Odvolanie = nový záznam, nič sa nemaže.

## Vydané eCP

`ecp_passes` – eCP v Google Wallet.

| Stĺpec | Význam |
|---|---|
| `member_id` | najviac jeden neukončený eCP na člena |
| `wallet_object_id` | `3388000000022877308.<náhodné id>` – bez osobných údajov |
| `state` | `active` (aj keď člen nie je v žiadnej skupine a čaká na rozhodnutie, R30), `inactive` (pozastavený vo všetkých skupinách alebo ukončené členstvo v SSS – obnoviteľné), `revoked` (vylúčenie, natrvalo, R25) |
| `wallet_state` | posledný stav odoslaný do Google Wallet (migrácia `0010`); rozdiel = čaká na odoslanie |
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

## Nastavenia (menia systémoví administrátori v Nastaveniach)

| Kľúč | Predvolené | Význam |
|---|---|---|
| `ecp_link_valid_hours` | 24 | platnosť jednorazového odkazu v e-maile (hodín) |
| `ecp_application_expiry_days` | 14 | nedokončená žiadosť prepadne (dní) |
| `ecp_qr_grace_minutes` | 15 | použitý QR token platí ešte (minút) |
| `ecp_qr_daily_limit` | 10 | najviac nových QR na eCP za deň |

## Rozhodnuté

- V žiadosti sa porovnáva **celý dátum narodenia**.
- Lehoty sú nastaviteľné (tabuľka vyššie).
- Počas stavu `submitted` je otvorená najviac jedna požiadavka `ecp_issue` na člena.

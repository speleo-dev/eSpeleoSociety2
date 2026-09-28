# Šablóny eCP z pôvodného projektu (referencia)

Súbory sú prevzaté bez zmeny z pôvodného projektu (`eSpeleoSociety-Original/config`). Slúžia ako návrh
vzhľadu eCP pre fázu 2. Nová implementácia ich prepíše do vlastného kódu (`ess/wallet/`) a pokryje testami.

| Súbor | Obsah |
|---|---|
| `wallet_object_template.json` | Google Wallet generic object – rozloženie preukazu |
| `wallet_layout_config.json` | starší variant rozloženia (textové moduly, odkazy, certifikáty) |
| `wallet_object_template.properties` | ktoré časti objektu sa posielajú pri vytvorení (`initial`) a pri aktualizácii (`update`) |
| `wallet_email_template.html` | e-mail s tlačidlom „Pridať do Peňaženky Google“ |

## Mapovanie premenných na nový dátový model

| Premenná | Nový zdroj | Poznámka |
|---|---|---|
| `{pass_object_id}` | `<issuer_id>.<náhodné id eCP>` | nesmie obsahovať osobné údaje |
| `{pass_class_id}` | `<issuer_id>.<class>` | existujúca trieda z Pay & Wallet Console |
| `{member_name}` | titul + meno + priezvisko | dešifrované na serveri |
| `{club.name}` | primárna skupina | |
| `{member.member_since}` | `members.member_since` | |
| `{member.public_id}` / `{member.id}` | `members.card_number` | číslo preukazu (návrh) |
| `{member.birth_date}` | dátum narodenia | |
| `{valid_until}` | koniec roka zaplateného členského | |
| `{check_url}` | overovacia stránka s jednorazovým tokenom (R18) | po overení sa objekt aktualizuje |
| `{photo_url}` | fotka tváre | verejná URL s náhodným 64-znakovým názvom |
| `{sticker_url}` | hero obrázok (napr. ročná známka) | |
| `{payment_link}`, `{issue_year}` | PAYMe odkaz s referenciou | fáza 3 |
| `{certificate.*}` | certifikáty člena | v pôvodnom projekte vypnuté (`disabled`) |

## Rozhodnuté (R24 v `docs/PLAN.md`)

- Issuer `3388000000022877308`, trieda `member`.
- Identifikačné číslo = číslo preukazu. Fotky cez verejnú URL s náhodným 64-znakovým názvom.
- Obrázky SSS sa presunú do bucketu nového projektu. Certifikáty vypnuté. QR sa posiela aj pri aktualizácii.

## Zostáva

- Prístup servisného účtu nového projektu v Pay & Wallet Console (`docs/gcp-setup.md`, krok 14).
- Texty bez diakritiky („Platba clenskeho“) opraviť.
- E-mail: v novej verzii Jinja2 s escapovaním namiesto `$premenných`.

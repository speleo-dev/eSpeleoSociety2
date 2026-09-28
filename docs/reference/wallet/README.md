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
| `{photo_url}` | fotka tváre | Google si obrázok musí vedieť stiahnuť – pozri otvorené otázky |
| `{sticker_url}` | hero obrázok (napr. ročná známka) | |
| `{payment_link}`, `{issue_year}` | PAYMe odkaz s referenciou | fáza 3 |
| `{certificate.*}` | certifikáty člena | v pôvodnom projekte vypnuté (`disabled`) |

## Otvorené otázky

- Issuer ID `3388000000022877308`, trieda `member` → Class ID `3388000000022877308.member`
  (premenné `ESS_WALLET_ISSUER_ID`, `ESS_WALLET_CLASS_SUFFIX`). Ešte treba prístup servisného účtu
  z nového GCP projektu.
- **Fotka:** Google Wallet sťahuje obrázky z verejnej URL. Neverejný bucket s krátkodobou podpísanou URL
  nemusí stačiť (Google môže obrázok stiahnuť neskôr znova). Treba overiť na teste.
- **Obrázky SSS** (`sss_sk_bucket` v starom projekte): ponechať, alebo presunúť do bucketu nového projektu.
- Texty bez diakritiky („Platba clenskeho“) opraviť.
- E-mail: v novej verzii Jinja2 s escapovaním namiesto `$premenných`.

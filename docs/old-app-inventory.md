# Pôvodná aplikácia – nastavenia a funkcie (inventúra)

Prehľad zo starého repozitára `speleo-dev/eSpeleoSociety` (stav `0b5baba`), aby sa pri prepise nič nestratilo.
Stĺpec **Nová verzia**: ✔ hotové, `F2`–`F6` fáza z `docs/PLAN.md`, ❓ treba rozhodnúť, ✖ nepreberá sa.

Poznámka: v starej aplikácii sa viaceré nastavenia dali uložiť, ale kód ich nepoužíval (Google Wallet
volania boli len náčrt, platobné odkazy sa negenerovali, notifikácie sa neposielali).

## Nastavenia

| Pôvodné nastavenie | Význam | Nová verzia |
|---|---|---|
| krajina, jazyk (`preferred_country`, `preferred_language`) | predvolená krajina v adresách, jazyk UI | ❓ krajina pri adrese; UI je po slovensky, EN neskôr |
| mena, členské, zľavnené členské | výška členského | ✔ (15 € / 7 €, vek 62) |
| platnosť členstva (mesiac/deň), obdobie obnovy (dni) | nikdy nepoužité | ❓ pozri otázku 1 |
| rok vydania | vždy aktuálny rok | ✔ kalendárny rok (R25) |
| IBAN, názov účtu | príjemca platby, kontrola IBAN vo výpise | F3 |
| generátor platobného odkazu (PAYME v1.2 / v2.0) | formát odkazu | F3 (PAYMe, R7) |
| preddefinované certifikáty | výber pri pridaní certifikátu | ✔ typy certifikátov |
| **ročná známka (sticker)**: šablóna 256×256 PNG, farba textu, pozadie, vygenerovať, nasadiť | obrázok s rokom (náhodný odtieň); v šablóne eCP je to `heroImage` | F2 – nastavenie vzhľadu eCP |
| Wallet: prípona triedy, URL overenia, doména JWT | nepoužité | ✔ R24 (issuer, trieda `member`, URL z `ESS_PUBLIC_BASE_URL`) |
| tajomstvá (DB, GCS, SMTP, FTP, podpisový kľúč Ed25519, `crypt_key`) šifrované PIN-om | desktop | ✔ Secret Manager; FTP a Ed25519 ✖ (R16) |
| rozloženie stĺpcov tabuliek | desktop | ✖ (neskôr úprava vzhľadu) |
| napevno: odkaz na výnimku MŽP SR, farby `#0b4a46`/`#d5a93f`, limity fotiek | | dokumenty ✔; farby a limity F2 |

## Funkcie

| Oblasť | Pôvodne | Nová verzia |
|---|---|---|
| Skupiny | názov, **adresa (ulica, mesto, PSČ, krajina), e-mail, telefón, web, dátum založenia**, verejné meno predsedu, logo | ✔ názov, kód, logo, predseda; ❓ kontaktné údaje (otázka 2) |
| Import skupín | stiahnutie zoznamu zo sss.sk | ✔ CSV import |
| Členovia | stav, rola, titul, meno, dátum narodenia, **adresa po častiach**, telefón, e-mail, zľava, viac skupín s primárnou | ✔ (adresa jedno pole – otázka 3) |
| Ikonky stavu | člen, pozastavený, čakateľ, hosť, predseda, zľava, nezaplatené, eCP | ✔ |
| Vyhľadávanie | bez diakritiky, podľa mena | ✔ |
| Hromadné akcie | „zaplatené“ pre vybraných, znova poslať eCP e-mailom | F3 / F2 |
| Portrét | detekcia tváre (OpenCV), orez 220:300, tvár 62 % výšky, min. 240×240, max. 900×1200 | F2 (R26: orez; detekcia neskôr) |
| Vydanie eCP priamo adminom | e-mail, fotka, GDPR, notifikácie, certifikáty (max 5) | F2 (cez žiadosť / R23) |
| Žiadosti o eCP | zoznam, schváliť / zamietnuť (zmaže fotku) | F2 (požiadavka „Vydanie eCP“); **e-mail pri zamietnutí** F2 |
| Karta JPG/PDF 1011×638 | fotka, meno, skupina, stav, číslo, platnosť, QR | F2 – kartička SSS (R16: len rok a „člen SSS“) |
| Overovacia stránka | statické HTML na FTP/GCS | F2 – dynamická stránka (sekcia 5a) |
| Podpísaný QR (Ed25519) | offline overenie | ✖ (R16) |
| E-mail „eCP vydaný“ | text + HTML, tlačidlo Wallet, prílohy | F2 (šablóna od Lad'a) |
| E-maily neskôr | zamietnutie, potvrdenie platby, platobný odkaz | F2 / F3 |
| Notifikácie | text, začiatok, platnosť (1–180 dní); nikdy neodoslané | F4 (Google Wallet správy) |
| Platby | camt.053 výpis, kontrola IBAN, párovanie podľa sumy (presne / menej / viac / neznáma referencia) | F3 |
| Reporty | prázdne; plánované štatistiky členov, platieb, eCP, história importov, audit | ❓ neskôr (F6) |
| Audit | záznam každej zmeny, citlivé údaje zamaskované | ✔ |
| API pre portál | REST s JWT | ✖ (stránky generované serverom) |

## Otázky

1. **Obdobie obnovy:** stará aplikácia mala „obdobie obnovy (dni)“ – nepoužité. Navrhujem: X dní pred koncom roka
   (nastavenie, napr. 60) sa v eCP a na portáli objaví platobný odkaz na **nasledujúci** rok.
2. **Kontaktné údaje skupiny** (adresa, e-mail, telefón, web, dátum založenia): pridať? Overovacia stránka zatiaľ
   ukazuje kontakt na predsedu skupiny.
3. **Adresa člena:** teraz jedno textové pole. Rozdeliť na ulicu, mesto, PSČ a krajinu (ako pôvodne)?

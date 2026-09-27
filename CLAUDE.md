# eSpeleoSociety (eSS) – nová verzia

Informačný systém Slovenskej speleologickej spoločnosti (SSS). Nahrádza papierovú a excelovú evidenciu
členov a vydáva elektronický jaskyniarsky preukaz (eCP) do Google Wallet a náhradnú PDF kartičku SSS.

Podrobný plán, rozhodnutia a otvorené otázky: [docs/PLAN.md](docs/PLAN.md). Pred väčšou zmenou ho prečítaj.

## Jazyk a konvencie

- Komunikácia s autorom (Lad'o) a všetka dokumentácia: **slovenčina**.
- Kód, názvy (premenné, funkcie, tabuľky, stĺpce, API endpointy), komentáre, commit správy: **angličtina**.
- Používateľské rozhranie: slovenčina, texty cez prekladové súbory (neskôr aj EN).
- Odpovede a zmeny drž jednoduché, ale presné. Radšej malé, overiteľné kroky ako veľké prepisy.

## Doména (slovník)

- **SSS** – národné združenie. Orgány: predseda, výbor, predsedníctvo (predseda + výbor + predsedovia
  všetkých skupín), kontrolná komisia. Všetci členovia orgánov sú členmi SSS.
- **Skupina (club)** – jaskyniarska skupina (JS) alebo oblastná skupina (OS); samostatné občianske
  združenie v rámci SSS. Má predsedu.
- **Predvolený klub „SSS“** – sem patria nezaradení členovia.
- **Stav členstva v skupine** – `candidate` (čakateľ, nie plnohodnotný člen), `member`, `suspended`
  (neaktívny, pozastavené), `expelled` (vylúčený – hrubé porušenie kódexu, **nesmie sa znova stať
  členom SSS**), ukončené členstvo.
- **Predseda skupiny** je rola člena v skupine, nie samostatný stav; predseda je členom predsedníctva.
- **Viacnásobné členstvo** – člen môže byť vo viacerých skupinách, práve **jedna je primárna**.
- **História členstiev** sa nikdy nemaže; zmeny stavu sa ukladajú s dátumom platnosti.
- **Zľavnené členské** – jeden príznak člena. Automaticky od roku X+1 pre člena, ktorý v roku X dosiahne
  vek z parametra; inak ručne (napr. ZTP).
- **Aktivácia člena** – nového člena (nie čakateľa) zadaného predsedom skupiny musí aktivovať predseda SSS
  alebo poverená osoba.
- **Organizačná štruktúra** – funkcie (predseda SSS, výbor, kontrolná komisia, predsedovia skupín,
  poverené osoby) s obdobím platnosti. Oprávnenia v systéme sa odvodzujú z platných funkcií.
- **Dokumenty** – názov, platnosť, odkaz; zobrazujú sa na portáli a na overovacej stránke.
- **Certifikáty** – schopnosti člena: SRT1, SRT2, záchranár, hasič a ďalšie (s platnosťou).
- **eCP** – elektronický jaskyniarsky preukaz v Google Wallet: preukaz, platobná linka na členské,
  notifikácie, vstup na portál, odkaz do národnej databázy jaskýň. QR vedie na online overovaciu
  stránku (offline overenie sa nerieši).
- **Kartička SSS** – PDF na vytlačenie pre členov bez smartfónu; rovnaký QR ako eCP.
- **Platobná referencia** – nečitateľný jedinečný kód; mapuje sa na člena alebo skupinu členov (hromadná
  platba predsedu) a rok. Každý rok nová.

## Roly a prístup

| Rola | Prístup |
|---|---|
| Verejnosť | žiadosť o eCP, overovacia stránka eCP/kartičky |
| Člen (s eCP) | len čítanie: novinky, vlastná identita, dokumenty, zaplatené členské, hlásenie vstupu do jaskyne, odkaz na národnú databázu jaskýň |
| Predseda skupiny | + členovia vlastnej skupiny, pridanie čakateľa/člena, pozastavenie/ukončenie, hromadná platba |
| Administrátor | všetko: vydávanie eCP, vzhľad eCP a kartičky, nastavenia, import, audit |

Člen nemá na portál prístup, kým nemá schválený eCP. Člen a predseda sa prihlasujú cez eCP
(+ overenie e-mailu, potom passkey). Admin sa prihlasuje Google účtom: dvaja hlavní admini sú
v konfigurácii servera, ďalších adminov a poverené osoby pridávajú v aplikácii.

## Architektúra (cieľ)

- Jedna webová aplikácia (admin, predseda, člen) s responzívnym UI pre mobil aj desktop.
  **Desktopový klient sa už nevyvíja.**
- Iba server pristupuje k databáze, Google Cloud a podpisovým kľúčom. Prehliadač nikdy nedostane tajomstvá.
- Stack: Python, FastAPI, stránky generované serverom (Jinja2 + HTMX), PostgreSQL.
- Hosting: Google Cloud Run (kontajner). Databáza: PostgreSQL 14 na WebSupporte (`eSpeleoSoc2`),
  pripojenie cez SSL. Počet DB dotazov na požiadavku drž nízky (DB je cez internet).
- Fotky tvárí: Google Cloud Storage (neverejný bucket, prístup cez krátkodobé podpísané URL).
- Platby: bez platobnej brány; PAYMe odkaz (parameter `PI` = referencia platiteľa), párovanie
  z nahratého bankového výpisu. Referencia je náhodný alfanumerický kód bez vnútorného významu.
- Verejné dokumenty sú len odkazy v nastaveniach, nie dáta v DB.
- E-mail systému `ess@sss.sk`, doména `sss.sk`.
- Rozpočet je 0 €: pri každej službe over bezplatný limit pri ~1 000 členoch.

## Bezpečnostné pravidlá (povinné)

- Žiadne tajomstvá, tokeny ani `.env` v repozitári. Konfigurácia len cez premenné prostredia / Secret Manager.
- Osobné údaje (GDPR) sú v DB **šifrované na úrovni aplikácie**; kľúč je mimo DB. Vyhľadávanie cez
  blind index (HMAC), nie cez čitateľný text.
- Osobné údaje nikdy do logov, chybových hlášok ani URL.
- Každá zmena dát sa zapisuje do auditného logu (kto, kedy, čo) v rovnakej transakcii.
- Autorizácia sa kontroluje na serveri pri každej požiadavke (predseda vidí len svoju skupinu).
- Admin: Google prihlásenie (OIDC, len `openid email profile`), prístup len pre e-maily evidované ako admin.
- Tokeny v odkazoch sú jednorazové a krátkodobé; statický odkaz z eCP sám o sebe nie je dôkaz identity.
- Zmena DB schémy len cez migrácie; migrácia nesmie mazať históriu členstiev.

## Pôvodný projekt (referencia)

Starý repozitár `speleo-dev/eSpeleoSociety` (PyQt desktop + priamy prístup do DB) slúži len ako
referencia. Kód z neho **nekopíruj naslepo** – prevezmi logiku, prepíš ju čisto a pokry testami.
Užitočné moduly:

- `wallet_pass.py` – Google Wallet generic object + JWT „Save to Wallet“ (Apple Wallet sa nerieši)
- `ecp_card.py` – generovanie PDF kartičky
- `face_detection.py`, `dialogs/portrait_crop_dialog.py` – detekcia a orez tváre
- `sepa_processing.py`, `banking/` – párovanie platieb, Payme platobné linky
- `tools/import_sss_clubs.py` – import skupín
- `database/schema.sql`, `docs/technical-manual.md`, `popis_aplikacie.md` – pôvodný dátový model a procesy

Dáta v starej DB sú len testovacie – nemigrujú sa. Na vývoj používaj generátor fiktívnych
testovacích dát; nikdy nepracuj s reálnymi osobnými údajmi mimo produkcie.

## Spôsob práce

- Pred implementáciou fázy si prečítaj jej časť v `docs/PLAN.md`; nejasnosti sa pýtaj, nehádaj.
- Každá funkcia má testy; testy nesmú potrebovať produkčné tajomstvá ani sieť.
- Rozhodnutia, ktoré menia architektúru, zapíš do `docs/PLAN.md` (sekcia Rozhodnutia).
- Príkazy (inštalácia, spustenie, testy, migrácie) doplň sem, keď vznikne kostra projektu.

## Príkazy

_Doplní sa po vytvorení kostry projektu (fáza 0). Nastavenie Google Cloud: `docs/gcp-setup.md`._

# eSpeleoSociety (eSS) – nová verzia

Informačný systém Slovenskej speleologickej spoločnosti (SSS). Nahrádza papierovú a excelovú evidenciu
členov a vydáva elektronický jaskyniarsky preukaz (eCP) do Google Wallet a náhradnú PDF kartičku SSS.

Podrobný plán, rozhodnutia a otvorené otázky: [docs/PLAN.md](docs/PLAN.md). Pred väčšou zmenou ho prečítaj.
Inventúra nastavení a funkcií pôvodnej aplikácie: [docs/old-app-inventory.md](docs/old-app-inventory.md).

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
- **Klub „SSS – nezaradení“** – predvolený klub pre členov bez skupiny; spravuje ho administrátor; jeho členovia nemajú zástupcu na valnom zhromaždení. JS a OS sa v IS nerozlišujú.
- **Stav členstva v skupine** – `candidate` (čakateľ, nie plnohodnotný člen), `member`, `suspended`
  (neaktívny, pozastavené), `expelled` (vylúčený – hrubé porušenie kódexu, **nesmie sa znova stať
  členom SSS**), ukončené členstvo.
- **Členstvo v SSS** sa odvodzuje zo skupín. Ukončenie členstva v skupine platí len pre skupinu; ak člen
  nemá žiadnu skupinu, ostáva členom SSS (eCP platí), kým administrátor nerozhodne (ukončenie členstva
  v SSS – obnoviteľné, alebo presun do „SSS – nezaradení“). Vylúčiť zo SSS môže len administrátor; je nevratné.
  Členské sa platí ručne na výročných schôdzach skupín; IS nikoho nevyraďuje automaticky podľa platieb (R30).
- **Predseda skupiny** je rola člena v skupine, nie samostatný stav; predseda je členom predsedníctva.
  Správu skupiny môže preniesť na **zástupcu** (člen s primárnou skupinou); kto smie spravovať skupinu, určuje
  `access.managed_club_ids` (R37).
- **Viacnásobné členstvo** – člen môže byť vo viacerých skupinách, práve **jedna je primárna**.
- **História členstiev** sa nikdy nemaže; zmeny stavu sa ukladajú s dátumom platnosti.
- **Zľavnené členské** – jeden príznak člena. Automaticky od roku X+1 pre člena, ktorý v roku X dosiahne
  vek z parametra; inak ručne (napr. ZTP).
- **Aktivácia člena** – nového člena (nie čakateľa) zadaného predsedom skupiny musí aktivovať administrátor.
- **Organizačná štruktúra** – funkcie (predseda SSS, výbor, kontrolná komisia, predsedovia skupín)
  s obdobím platnosti. Z funkcie sa odvodzuje len správa vlastnej skupiny predsedom skupiny.
- **Administratívny prístup je oddelený od organizačnej štruktúry** – nie je viazaný na členstvo, eCP ani
  funkciu. Roly: **administrátor** (`admin` – predseda SSS alebo poverená osoba s povolením na zmeny v IS;
  nemusí byť členom SSS) a **systémový administrátor** (`system_admin`). Udeľuje ich systémový administrátor.
- **Zmena predsedu skupiny** – zadáva ju len administrátor, až po doručení dokumentov (zvyčajne z výročnej
  schôdze skupiny). Dovtedy má oprávnenia starý predseda.
- **Požiadavky** – jeden zoznam všetkého, čo čaká na administrátora (aktivácia člena, rozhodnutie o členstve
  v SSS, neskôr vydanie eCP). V kóde `tasks`; otvárajú a zatvárajú ich služby v tej istej transakcii ako zmenu.
- **Delegát** – vyhradené slovo pre budúcu rolu na valnom zhromaždení; inak ho v IS nepoužívaj.
- **Dokumenty** – názov, platnosť, odkaz; zobrazujú sa na portáli a na overovacej stránke.
- **Certifikáty** – schopnosti člena: SRT1, SRT2, záchranár, hasič a ďalšie (s platnosťou).
- **eCP** – elektronický jaskyniarsky preukaz v Google Wallet: preukaz, platobná linka na členské,
  notifikácie, vstup na portál, odkaz do národnej databázy jaskýň. QR vedie na online overovaciu
  stránku (offline overenie sa nerieši). QR je jednorazový – po overení sa pregeneruje (denný limit).
- **Kartička SSS** – PDF na vytlačenie pre členov bez smartfónu; vydáva sa na jeden rok, má vlastný kód.
  Overenie ukáže len „Člen Slovenskej speleologickej spoločnosti“ a „Členské zaplatené na rok XXXX“.
- **Platobná referencia** – nečitateľný jedinečný kód; mapuje sa na člena alebo skupinu členov (hromadná
  platba predsedu) a rok. Každý rok nová.

## Roly a prístup

| Rola | Prístup |
|---|---|
| Verejnosť | žiadosť o eCP, overovacia stránka eCP/kartičky |
| Člen (s eCP) | len čítanie: vlastná identita, dokumenty, zaplatené členské, hlásenie vstupu do jaskyne, odkaz na národnú databázu jaskýň |
| Predseda skupiny | + členovia vlastnej skupiny, pridanie čakateľa/člena, pozastavenie/ukončenie, hromadná platba |
| Zástupca predsedu | práva predsedu namiesto neho, kým ho predseda neodvolá (R37); predseda vtedy len číta |
| Administrátor (`admin`) | evidencia členov a skupín, aktivácia členov, žiadosti o eCP, bankové výpisy |
| Systémový administrátor (`system_admin`) | všetko vrátane prístupov, vzhľadu eCP a kartičky a nastavení |

Člen nemá na portál prístup, kým nemá schválený eCP. Člen a predseda sa prihlasujú cez eCP
(+ overenie e-mailu, potom passkey). Administratívny prístup = Google účet: dvaja hlavní systémoví
administrátori sú v konfigurácii servera, ďalších systémových administrátorov a administrátorov pridáva systémový
administrátor v aplikácii.

## Architektúra (cieľ)

- Jedna webová aplikácia (admin, predseda, člen) s responzívnym UI pre mobil aj desktop.
  **Desktopový klient sa už nevyvíja.**
- Iba server pristupuje k databáze, Google Cloud a podpisovým kľúčom. Prehliadač nikdy nedostane tajomstvá.
- Stack: Python, FastAPI, stránky generované serverom (Jinja2 + HTMX), PostgreSQL.
- Hosting: Google Cloud Run (kontajner). Databáza: PostgreSQL 14 na WebSupporte (`eSpeleoSoc2`),
  pripojenie cez SSL. Počet DB dotazov na požiadavku drž nízky (DB je cez internet).
- Fotky tvárí: Google Cloud Storage; objekty čitateľné len cez neuhádnuteľný náhodný 64-znakový názov
  (Google Wallet si ich musí vedieť stiahnuť), bez verejného zoznamu objektov (R24).
- Google Wallet: issuer `3388000000022877308`, trieda `member` (R24).
- Platby: bez platobnej brány; PAYMe odkaz (parameter `PI` = referencia platiteľa), párovanie
  z nahratého bankového výpisu. Referencia je náhodný alfanumerický kód bez vnútorného významu.
- Dokumenty: tabuľka (názov, platnosť, odkaz), samotné súbory sú mimo eSS.
- E-mail systému `ess@sss.sk`, doména `sss.sk`.
- Rozpočet je 0 €: pri každej službe over bezplatný limit pri ~1 000 členoch.

## Bezpečnostné pravidlá (povinné)

- Žiadne tajomstvá, tokeny ani `.env` v repozitári. Konfigurácia len cez premenné prostredia / Secret Manager.
- Osobné údaje (GDPR) sú v DB **šifrované na úrovni aplikácie**; kľúč je mimo DB. Vyhľadávanie cez
  blind index (HMAC), nie cez čitateľný text.
- Osobné údaje nikdy do logov, chybových hlášok ani URL.
- E-mail nie je jedinečný (manželia ho zdieľajú) – člena nikdy neidentifikuj len podľa e-mailu.
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

Nastavenie Google Cloud: `docs/gcp-setup.md`. Nasadenie na Cloud Run (v Cloud Shell): `./deploy.sh`
(s migráciami `./deploy.sh migrate`); projekt `espeleosociety` je v skripte napevno.

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # inštalácia
.venv/bin/python -m ess.tools.generate_keys                  # nové šifrovacie kľúče (len do Secret Manager / .env)
.venv/bin/uvicorn ess.main:app --reload                      # lokálny server (http://127.0.0.1:8000)
.venv/bin/pytest -q                                          # testy (DB testy sa bez DB preskočia)
ESS_DATABASE_URL=... .venv/bin/alembic upgrade head          # migrácie DB
.venv/bin/alembic revision -m "popis"                         # nová migrácia (autogenerate len ako návrh, vždy skontrolovať)
.venv/bin/python -m ess.tools.seed_test_data                  # fiktívne testovacie dáta do PRÁZDNEJ dev DB (skupiny sú skutočné)
.venv/bin/python -m ess.tools.load_clubs                      # skupiny SSS a ich logá (ess/data/clubs), aj do produkcie
```

DB testy: `ESS_TEST_DATABASE_URL` (prázdna testovacia DB, testy ju mažú!) a `ESS_DB_SSLMODE=disable` pre
lokálnu DB bez SSL. Nikdy nenastavuj `ESS_TEST_DATABASE_URL` na produkčnú databázu.

## Štruktúra

- `ess/main.py` – FastAPI aplikácia; `ess/config.py` – konfigurácia (premenné `ESS_*`)
- `ess/db.py` – pool spojení, `Base` pre modely; `ess/audit.py` – auditný log
- `ess/security/crypto.py` – šifrovanie osobných údajov (AES-GCM, kontext ako AAD) a blind index (HMAC);
  `ess/security/pii.py` – prístup ku kľúčom z konfigurácie
- `ess/storage.py` – úložisko obrázkov (GCS, náhodné názvy; `MemoryMediaStore` pre testy); `ess/images.py` –
  kontrola a prevod nahratých obrázkov (Pillow, len rastrové formáty, bez EXIF); `ess/mail.py` – odosielanie
  e-mailov cez SMTP (`MemoryMailer` pre testy; adresy nikdy do logov); `ess/wallet.py` – Google Wallet
  (objekt preukazu, odkaz „Pridať do Peňaženky Google“ podpísaný cez IAM bez kľúča; `MemoryWalletClient` pre testy);
  `ess/cards.py` – PDF kartička SSS (reportlab, písmo DejaVu v `static/fonts`); `ess/banking/` – parsery bankových
  výpisov (camt.053, XML cez defusedxml)
- `ess/models.py` – ORM modely (`docs/data-model.md`, fáza 2: `docs/data-model-ecp.md`, fáza 3: `docs/data-model-payments.md`, fáza 4: `docs/data-model-portal.md`)
- `ess/services/` – biznis pravidlá a oprávnenia (`access.py` – kto čo smie; `members`, `memberships`,
  `positions`, `admin_access`, `settings`, `tasks` – požiadavky, `clubs`, `delegations` – zastupovanie predsedu, R37, `certificates`, `documents`,
  `importing` – CSV import, návod `docs/import.md`; `ecp_applications` – žiadosti o eCP, `ecp_issuance` – schválenie a vydanie eCP, `ecp_verification` – overovacia stránka a jednorazový QR, `ecp_state` – stav eCP podľa členstva, R25; `ecp_content` – „Platný do“ a ročná známka v eCP po zaplatení; `outbox` – e-maily odoslané až po commite; `sss_cards` – kartička SSS, R31; `payments` – členské, platobné referencie, PAYMe odkaz, hromadná platba, R35/R36; `bank_statements` – spracovanie výpisu a Požiadavky k platbám; `portal_auth` – prihlásenie člena na portál, R38; `portal` – čo vidí člen na portáli; `ecp_notifications` – notifikácie do eCP, R41). Zmeny dát rob len cez služby – kontrolujú oprávnenia a zapisujú audit.
- `ess/services/directory.py` – čítanie pre obrazovky (zoznamy s dešifrovanými menami, málo DB dotazov)
- `ess/web/` – webová vrstva: `auth.py` (Google prihlásenie, session, CSRF), `common.py` (spoločné pomocné
  funkcie), `admin.py` (prehľad, zoznamy, požiadavky), `admin_members.py` (formuláre a akcie nad členom),
  `admin_org.py` (skupiny, organizácia, prístupy, nastavenia, dokumenty), `admin_ecp.py` (posúdenie žiadostí
  o eCP), `admin_payments.py` (členské, platobné odkazy, hromadná platba, bankové výpisy), `mailing.py` (e-maily zo šablón `templates/email/`), `public.py` (verejné stránky –
  žiadosť o eCP; vlastná CSRF kontrola), `portal.py` (portál člena – prihlásenie z eCP, cookie `ess_member`), `templates.py` (Jinja2, slovenské
  popisy a chybové hlášky). Každý POST formulár musí mať `csrf_token`. Konkrétne cesty (`/members/new`)
  registruj pred parametrizovanými (`/members/{id}`).
- `ess/templates/` – Jinja2 šablóny; `migrations/` – Alembic migrácie
- `spikes/` – jednorazové technické testy (nie súčasť aplikácie)

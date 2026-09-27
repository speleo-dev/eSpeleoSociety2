# eSpeleoSociety – plán dokončenia

Stav: odsúhlasené rozhodnutia (2026-09-27). Autor zadania: Lad'o.

## 1. Prečo projekt vzniká

SSS nemá žiadny informačný systém – evidencia je na papieri, vo Wordoch a Exceloch a sekretariát prakticky
nefunguje. Papierový jaskyniarsky preukaz má formát zo 70.–80. rokov a do terénu ho takmer nikto nenosí,
smartfón však má každý. Ročné známky do papierového preukazu sa k členom dostávajú aj 2–3 mesiace.
Cieľom je digitalizovať správu SSS a nahradiť preukaz elektronickým.

## 2. Ciele

**Praktické**
- eCP v Google Wallet: preukaz pre sprístupnené jaskyne, zľavy a legitimovanie v teréne (štátne
  organizácie, poľovníci).
- Overenie: kontrolór naskenuje QR z eCP → overovacia stránka portálu SSS (viď sekcia 5). Bez signálu
  sa overuje tam, kde signál je – offline overenie sa nerieši.
- Kartička SSS (PDF) pre členov bez smartfónu – rovnaký QR a rovnaká overovacia stránka.
- Platba členského bežným prevodom cez PAYMe odkaz v eCP a automatické párovanie z bankového výpisu.
- Notifikácie cez eCP (nové platobné obdobie, Speleomíting, Jaskyniarsky týždeň, novinky).
- Portál pre členov, predsedov skupín a administrátorov; automatizácia práce sekretariátu.
- eCP ako „kľúč“ do národnej databázy jaskýň (budúcnosť – druhý projekt je v štádiu analýzy).
- Doplnkovo: hlásenie vstupu do jaskyne (časopriestorová stopa).

**Technologické**
- Žiadny priamy prístup klienta do DB – iba server.
- Webová aplikácia použiteľná na mobile aj desktope, bez inštalácie.
- GDPR údaje v DB nečitateľné (šifrované).
- Prevádzka za 0 € (DB na WebSupporte, bezplatné limity Google Cloud).

## 3. Rozhodnutia

- **R1** – Nový repozitár `speleo-dev/eSpeleoSociety2`, prakticky nový IS. Starý projekt je len referencia.
- **R2** – Iba webová aplikácia; desktopový klient sa ďalej nevyvíja.
- **R3** – Hosting: **Python (FastAPI) na Google Cloud Run**, DB PostgreSQL 14 na WebSupporte
  (databáza `eSpeleoSoc2`). Podmienka: technický test vo fáze 0 (šifrované SSL spojenie, oneskorenie).
- **R4** – Frontend: stránky generované serverom (Jinja2 + HTMX), responzívne.
- **R5** – Prihlásenie člena (aj predsedu): odkaz z eCP → pri prvom prihlásení na zariadení potvrdenie cez
  overený e-mail → passkey na telefóne → ďalšie prihlásenia na jeden klik. Kódy jednorazové, krátkodobé.
- **R6** – Prihlásenie administrátora: **Google účet** (OpenID Connect, rozsahy len `openid email profile`).
  Dvaja hlavní admini sú zadaní v konfigurácii servera (nedajú sa odobrať z aplikácie). Ďalších adminov
  a poverené osoby pridávajú hlavní admini v aplikácii podľa e-mailu Google účtu. Odporúčanie: zapnuté
  dvojfaktorové overenie na Google účtoch adminov.
- **R7** – Bez platobnej brány. Platba bežným prevodom cez **PAYMe odkaz** (slovenský štandard PaymentLink,
  parameter `PI` = referencia platiteľa). Bankový výpis (súbor z internetbankingu) nahráva poverená osoba
  alebo predseda SSS; referencia platiteľa je vo výpise.
- **R8** – Apple Wallet sa teraz nerieši.
- **R9** – Stará DB sa nemigruje. Vytvorí sa generátor testovacích dát.
- **R10** – Hlásenie vstupu do jaskyne je doplnková funkcia na 2–3 kliky. Po uplynutí času príde predsedovi
  skupiny e-mail; ďalší postup rieši predseda. Žiadna automatická eskalácia na záchranárov.
- **R11** – Dokumenty (stanovy, rozhodnutia, výnimky a povolenia SSS) sú samostatná tabuľka: názov,
  dátum platnosti, odkaz. Zobrazujú sa na portáli aj na overovacej stránke; po uplynutí platnosti sa skryjú.
  Kto spravuje ktorú lokalitu, rieši NDBJ (národná databáza jaskýň), nie eSS.
- **R13** – Zľavnené členské je **jeden príznak** člena (bez rozlíšenia ZTP/dôchodca). Automaticky sa nastaví
  členovi, ktorý v roku X dosiahne vek daný parametrom – zľava platí od roku X+1. Ručne ho môže nastaviť
  admin/poverená osoba (napr. ZTP).
- **R14** – Nový člen (nie čakateľ) zadaný predsedom skupiny nie je aktívny hneď; čaká na **aktiváciu
  predsedom SSS alebo poverenou osobou**. Čakateľa predseda skupiny pridáva priamo.
- **R15** – Organizačná štruktúra SSS je v dátovom modeli (predseda SSS, výbor, kontrolná komisia,
  predsedovia skupín). Po voľbách sa zadajú nové funkcie s dátumom a oprávnenia v systéme sa priradia
  a odoberú automaticky podľa funkcie.
- **R16** – Offline podpisovaný QR sa nerobí. QR v eCP aj na kartičke je odkaz na overovaciu stránku
  s nečitateľným a neuhádnuteľným tokenom.
- **R12** – E-mail systému: `ess@sss.sk`, doména `sss.sk` (aplikácia napr. na `ess.sss.sk`).

## 4. Architektúra

```
Google Wallet ─┐
Prehliadač ────┼─► Webová aplikácia (Cloud Run, FastAPI) ─► PostgreSQL eSpeleoSoc2 (WebSupport, SSL)
(člen/predseda/│        ├─► Google Cloud Storage (fotky, neverejný bucket)
 admin/overenie)        ├─► Google Wallet API (preukazy, notifikácie)
                        ├─► Google prihlásenie (admini)
                        └─► SMTP ess@sss.sk
   tajomstvá: Google Secret Manager → premenné prostredia Cloud Run
```

- Jedna aplikácia, oddelené časti: `public` (žiadosť, overenie), `member`, `chair`, `admin`.
- Šifrovanie osobných údajov na úrovni aplikácie (AES-GCM), kľúč v Secret Manageri, nie v DB.
  Vyhľadávanie cez blind index (HMAC).
- Audit každej zmeny v rovnakej transakcii ako zmena.

## 5. Pravidlá členstva a členského

- Členské za **kalendárny rok** (1. 1. – 31. 12.), platí sa raz ročne.
- Parametre v nastaveniach: **výška členského** (teraz 15 €), **zľavnené členské**, **vek pre zľavu**
  (60 alebo 62 – parameter).
- Zľavnené členské: jeden príznak člena (R13). Automatické nastavenie podľa veku beží pri otvorení nového
  roka členského; ručné nastavenie (napr. ZTP) robí admin alebo poverená osoba.
- **Čakateľ neplatí** a nie je plnohodnotným členom; niektoré skupiny čakateľský status nepoužívajú
  (nastavenie skupiny).
- Nový člen zadaný predsedom skupiny čaká na aktiváciu predsedom SSS alebo poverenou osobou (R14).
  Návrh: rovnako aj povýšenie čakateľa na člena.
- Nezaradení členovia patria do predvoleného klubu „SSS“.

## 5a. Overovacia stránka (po naskenovaní QR)

- Výrazne: **„Člen Slovenskej speleologickej spoločnosti – jaskyniar“** (alebo výrazné upozornenie, ak
  členstvo nie je platné).
- Osobné údaje člena: meno, fotka, skupina. Návrh: len minimum potrebné na overenie totožnosti
  (stránku uvidí každý, kto naskenuje QR).
- Stav zaplatenia členského na aktuálny rok.
- Kontakty: predseda skupiny, predseda SSS (podľa aktuálnej organizačnej štruktúry).
- Zoznam platných dokumentov (R11).

## 6. Dátový model (náčrt)

- `members` – identita (šifrované osobné údaje + blind indexy), dátum narodenia, e-mail,
  príznak **`reduced_fee`** (zľavnené členské), stav vo vzťahu k SSS (aj `expelled`). Skutočne vyrubená
  suma sa ukladá pri členskom za daný rok, takže história zostáva zachovaná.
- `clubs` – JS/OS, predvolený klub „SSS“, nastavenie „používa čakateľov“.
- `memberships` – člen × skupina, stav (`candidate`, `pending_activation`, `member`, `suspended`,
  `terminated`, `expelled`), `is_primary`, `valid_from`, `valid_to`, kto a kedy aktivoval. História sa nemaže.
- **Organizačná štruktúra:**
  - `org_positions` – funkcie: predseda SSS, podpredseda, člen výboru, predseda/člen kontrolnej komisie,
    predseda skupiny (viazaný na skupinu), poverená osoba.
  - `position_holders` – kto zastáva funkciu, `valid_from`, `valid_to` (volebné obdobie). Po voľbách sa
    zadajú noví držitelia; starým sa funkcia ukončí dátumom.
  - Oprávnenia v systéme sa **odvodzujú z platných funkcií** (napr. predseda SSS a poverená osoba môžu
    aktivovať členov, predseda skupiny spravuje svoju skupinu). Predsedníctvo = predseda SSS + výbor +
    predsedovia skupín (odvodené, nie ukladané).
- `fees` – členské za rok: člen, rok, vyrubená suma, či bola zľavnená, stav (nezaplatené/zaplatené).
- `payment_references` – referencia platiteľa → rok + jeden alebo viac členov (hromadná platba predsedu).
  Referencia je **náhodný kód bez vnútorného významu** (napr. 12 znakov z abecedy A–Z a 2–7, bez
  zameniteľných znakov). Rok ani člen sa z nej nedajú odvodiť ani uhádnuť. Význam existuje iba v tejto
  tabuľke. Každý rok nové referencie. Len alfanumerické znaky, dĺžka v limite PAYMe/SEPA (overiť vo fáze 3).
- `bank_statements`, `payments` – nahraté výpisy, jednotlivé platby a výsledok párovania.
- `certificates` – typ (SRT1, SRT2, záchranár, hasič, …), platnosť.
- `ecp_requests`, `ecp_cards` – žiadosti a vydané preukazy (Wallet objekt, QR, PDF kartička).
- `consents` – GDPR a notifikácie, s dátumom a verziou textu.
- `news` – novinky (rovnaký obsah ako notifikácie eCP).
- `documents` – názov, dátum platnosti, odkaz (R11).
- `cave_trips` – hlásenie vstupu do jaskyne.
- `admin_users` (Google e-maily adminov), `passkeys`, `sessions`, `one_time_tokens`, `audit_log`.

## 7. Dáta

- Reálne dáta sú v zlom stave (papier, Word, Excel). Niekto ich musí zjednotiť do **jedného zoznamu podľa
  šablóny** (vytvoríme vo fáze 1): meno, priezvisko, skupina, voliteľne bydlisko, e-mail, dátum narodenia.
- Import prijme aj člena bez dátumu narodenia alebo e-mailu, ale taký člen **nemôže požiadať o eCP**, kým
  mu údaje nedoplní predseda skupiny alebo poverená osoba.
- Pre vývoj: generátor fiktívnych testovacích dát (slovenské mená, skupiny, členstvá, história, platby).

## 8. Fázy

Každá fáza končí funkčným, otestovaným a nasadeným stavom.

### Fáza 0 – Základ
- Google Cloud projekt, rozpočtové upozornenie, Cloud Run (návod: `docs/gcp-setup.md`).
- Technický test: Cloud Run → WebSupport PostgreSQL cez SSL, zmerať oneskorenie.
- Kostra projektu (FastAPI), CI (testy pri každom pushi), migrácie DB, konfigurácia cez premenné prostredia.
- Šifrovacia vrstva pre osobné údaje + blind index, auditný log.
- Generátor testovacích dát.

**Výsledky technického testu (2026-09-27) – úspešný, R3 platí:**
- Spojenie Cloud Run (europe-west3) → `eSpeleoSoc2` funguje, PostgreSQL 14.13.
- Úsek Cloud Run → WebSupport je šifrovaný (TLS). WebSupport má pred DB proxy; úsek proxy → PostgreSQL
  je vnútri ich privátnej siete a nešifrovaný (mimo našej kontroly, akceptované).
- Otvorenie spojenia ~180 ms, dotaz ~18 ms (medián), max. ~39 ms.
- Dôsledky: pool spojení, najviac niekoľko DB dotazov na stránku.

### Fáza 1 – Administrácia
- Prihlásenie admina cez Google účet; hlavní admini z konfigurácie, ďalší admini a poverené osoby v aplikácii.
- Skupiny, členovia, členstvá s históriou, primárna skupina, zľavnené členské, certifikáty.
- Organizačná štruktúra a funkcie s obdobím; oprávnenia odvodené z funkcií.
- Aktivácia nových členov (predseda SSS / poverená osoba).
- Šablóna a import zjednoteného zoznamu členov.
- Kontroly: vylúčený sa nesmie znova stať členom, práve jedna primárna skupina.

### Fáza 2 – eCP a kartička
- Verejná žiadosť: meno, priezvisko, rok narodenia, skupina, e-mail (povinné) → overenie e-mailu
  („klikni sem“) → vyhľadanie člena. **Pokračovať sa dá len pri presnej zhode všetkých údajov.**
  Ak IS nemá dátum narodenia alebo e-mail, alebo sa e-mail nezhoduje, žiadosť sa zastaví s pokynom
  kontaktovať predsedu skupiny alebo poverenú osobu SSS → fotka tváre + súhlasy (GDPR, notifikácie)
  + voľba PDF kartičky.
- Obrazovka spracovania žiadostí: schváliť / zamietnuť s dôvodom (napr. nevyhovujúca fotka).
- Vydanie: Google Wallet preukaz, PDF kartička, e-mail s odkazmi.
- Overovacia stránka (sekcia 5a) a správa dokumentov.
- Nastavenia vzhľadu eCP a kartičky.

### Fáza 3 – Platby
- Ročné referencie, PAYMe odkaz v eCP a na portáli.
- Nahratie bankového výpisu, automatické párovanie podľa referencie, ručné dopárovanie.
- Prehľad zaplateného členského.

### Fáza 4 – Portál člena
- Prihlásenie cez eCP (R5).
- Novinky, vlastné údaje, odkazy na dokumenty, zaplatené členské.
- Odosielanie notifikácií do eCP z administrácie.
- Hlásenie vstupu do jaskyne: kde, kto, plánovaný návrat → pripomienka členovi → e-mail predsedovi skupiny.

### Fáza 5 – Portál predsedu
- Zoznam členov skupiny, pridanie čakateľa, návrh nového člena (čaká na aktiváciu), pozastavenie, ukončenie.
- Hromadná platba: výber členov → PAYMe odkaz/QR s jednou referenciou → po spárovaní záznam platby
  pre každého vybraného člena.

### Fáza 6 – Rozšírenia
- Prepojenie s národnou databázou jaskýň.
- Apple Wallet (ak bude rozpočet).

## 9. Riziká
- **Spojenie Cloud Run → WebSupport DB** – DB musí byť dostupná z internetu; ochrana: SSL, silné heslo,
  samostatný DB používateľ s minimálnymi právami. Ak test neprejde, návrat k rozhodnutiu o hostingu.
- **Náklady Google Cloud** – bezplatný limit Cloud Run je veľký, ale prenos dát z Google do WebSupportu
  (egress) mimo Severnej Ameriky nie je v bezplatnom limite – pri našom objeme ide rádovo o centy.
  Nastaviť rozpočtové upozornenie.
- **Limit notifikácií Google Wallet** na preukaz za deň – vhodné na novinky, nie na urgentné správy.
- **Kvalita dát** – zjednotenie zoznamu členov je mimo vývoja a môže trvať dlho.
- **Jeden vývojár** – držať rozsah fáz malý.

## 10. Otvorené otázky
1. Presné pravidlá pripomienky pri hlásení vstupu do jaskyne (kedy pripomenúť členovi, kedy e-mail predsedovi).
2. Podporuje WebSupport PostgreSQL šifrované (SSL) pripojenie a obmedzenie podľa IP? (overí test vo fáze 0)
3. V akom formáte exportuje banka SSS výpis (CSV, XML camt.053, …)? Treba vzorový výpis.
4. Gmail druhého hlavného admina (zadá sa do konfigurácie, nie do repozitára).
5. Aké osobné údaje presne zobraziť na overovacej stránke (návrh: meno, fotka, skupina)?
6. Potrebuje aj povýšenie čakateľa na člena aktiváciu predsedom SSS / poverenou osobou? (návrh: áno)

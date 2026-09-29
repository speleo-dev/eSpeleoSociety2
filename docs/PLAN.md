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
  Dvaja hlavní systémoví administrátori sú zadaní v konfigurácii servera (nedajú sa odobrať z aplikácie).
  Ďalších systémových administrátorov a administrátorov pridáva systémový administrátor v aplikácii podľa
  e-mailu Google účtu. Odporúčanie: zapnuté dvojfaktorové overenie na týchto Google účtoch.
- **R17** – **Administratívny prístup je oddelený od organizačnej štruktúry.** Nie je viazaný na členstvo,
  eCP ani funkciu; udeľuje ho systémový administrátor. Roly: `system_admin` (systémový administrátor)
  a `admin` (**administrátor** – jednotný názov pre predsedu SSS alebo poverenú osobu s povolením na zmeny
  v IS; nemusí byť členom SSS). Nový predseda SSS dostane prístup až po udelení.
  Jediné oprávnenie odvodené z funkcie: predseda skupiny spravuje svoju skupinu na portáli. Zmenu predsedu
  skupiny zadáva len administrátor po doručení dokumentov (zvyčajne z výročnej schôdze); dovtedy má
  oprávnenia starý predseda.
  Slovo „delegát“ je vyhradené pre budúcu rolu na valnom zhromaždení.
- **R7** – Bez platobnej brány. Platba bežným prevodom cez **PAYMe odkaz** (slovenský štandard PaymentLink,
  parameter `PI` = referencia platiteľa). Bankový výpis (súbor z internetbankingu) nahráva administrátor; referencia platiteľa je vo výpise.
- **R8** – Apple Wallet sa teraz nerieši.
- **R9** – Stará DB sa nemigruje. Vytvorí sa generátor testovacích dát.
- **R10** – Hlásenie vstupu do jaskyne je doplnková funkcia na 2–3 kliky. Po uplynutí času príde predsedovi
  skupiny e-mail; ďalší postup rieši predseda. Žiadna automatická eskalácia na záchranárov.
- **R11** – Dokumenty (stanovy, rozhodnutia, výnimky a povolenia SSS) sú samostatná tabuľka: názov,
  dátum platnosti, odkaz. Zobrazujú sa na portáli aj na overovacej stránke; po uplynutí platnosti sa skryjú.
  Kto spravuje ktorú lokalitu, rieši NDBJ (národná databáza jaskýň), nie eSS.
- **R13** – Zľavnené členské je **jeden príznak** člena (bez rozlíšenia ZTP/dôchodca). Automaticky sa nastaví
  členovi, ktorý v roku X dosiahne vek daný parametrom – zľava platí od roku X+1. Ručne ho môže nastaviť
  administrátor (napr. ZTP).
- **R14** – Nový člen (nie čakateľ) zadaný predsedom skupiny nie je aktívny hneď; čaká na **aktiváciu
  administrátorom**.
  Čakateľa predseda skupiny pridáva priamo.
- **R15** – Organizačná štruktúra SSS je v dátovom modeli (predseda SSS, výbor, kontrolná komisia,
  predsedovia skupín). Po voľbách sa zadajú nové funkcie s dátumom a oprávnenia v systéme sa priradia
  a odoberú automaticky podľa funkcie.
- **R16** – Offline podpisovaný QR sa nerobí. QR v eCP aj na kartičke je odkaz na overovaciu stránku
  s nečitateľným a neuhádnuteľným tokenom.
- **R19** – Ukončenie členstva v skupine platí len pre skupinu. Ak člen nemá žiadnu skupinu, čaká na
  rozhodnutie predsedníctva: členstvo v SSS zanikne (dá sa neskôr obnoviť), alebo sa presunie do
  „SSS – nezaradení“. Zapisuje administrátor. Vylúčenie (valné zhromaždenie) je nevratné.
- **R21** – E-mail **nie je jedinečný** (manželia často zdieľajú jeden). Člena nikdy neidentifikujeme len podľa
  e-mailu; v detaile člena sa zobrazí, s kým e-mail zdieľa.
- **R22** – Žiadosť o eCP dopĺňa chýbajúce údaje: **číslo preukazu je povinné**; ak IS nemá „člen SSS od“,
  žiadateľ ho musí zadať. Chýbajúce údaje sa uložia po schválení žiadosti administrátorom.
- **R23** – **Nový člen** nejde cez verejnú žiadosť. Predseda skupiny ho zadá podľa papierovej prihlášky
  (obsahuje súhlas GDPR) a rovno zaškrtne „vydať eCP“. Administrátor pri aktivácii doplní číslo papierového
  preukazu, ak bol vydaný (hotové). Verejná žiadosť o eCP je pre existujúcich členov.
- **R20** – Všetko, čo čaká na administrátora (aktivácie, rozhodnutia o členstve v SSS, neskôr žiadosti
  o eCP), je v jednom zozname **„Požiadavky“** s popisom a tlačidlami v každom riadku (tabuľka `tasks`).
- **R18** – QR v eCP je **jednorazový**: po overení sa token zneplatní a eCP v Google Wallet dostane nový QR.
  Denný limit overení na člena. Podrobnosti v sekcii 5a.
- **R12** – E-mail systému: `ess@sss.sk`, doména `sss.sk` (aplikácia napr. na `ess.sss.sk`).
- **R24** – eCP používa existujúci Google Wallet issuer `3388000000022877308` a triedu `member`
  (`3388000000022877308.member`). ID nie sú tajné (predvolené v `ess/config.py`, premenné `ESS_WALLET_ISSUER_ID`, `ESS_WALLET_CLASS`);
  tajný je len kľúč servisného účtu. Návrh vzhľadu: `docs/reference/wallet/`.
  - „Identifikačné číslo“ na preukaze = **číslo preukazu** (`card_number`).
  - **Fotky tvárí** musí vedieť stiahnuť Google Wallet, preto sú objekty čitateľné cez verejnú URL
    s **náhodným 64-znakovým názvom** (neuhádnuteľný). Bucket nemá verejný zoznam objektov.
    Pri výmene fotky dostane nová fotka nový názov a stará sa zmaže.
  - Obrázky SSS (logá, tlačidlo Wallet) sa presunú zo starého `sss_sk_bucket` do bucketu nového projektu.
  - Certifikáty na preukaze zatiaľ vypnuté. QR sa posiela aj pri aktualizácii objektu (R18).
- **R25** – Pravidlá eCP:
  - eCP dostane len člen so stavom `member` aspoň v jednej skupine; **čakateľ nie**.
  - eCP sa vydá aj **bez zaplateného členského**; overovacia stránka ukáže, či je členské na aktuálny rok
    zaplatené. „Platný do“ = koniec posledného zaplateného roka (do fázy 3 sa neukazuje).
  - Pozastavenie vo všetkých skupinách: eCP sa v Google Wallet prepne na neaktívny, po obnovení sa aktivuje.
  - **Vylúčenie: eCP sa zruší úplne** (objekt v Google Wallet sa zneplatní a odstránia sa z neho údaje;
    API objekty nemaže). Jeho tokeny ďalej vedú na overovaciu stránku s upozornením, že nejde o člena SSS.
  - **Ukončenie členstva v SSS administrátorom** (obnoviteľné): eCP je neaktívny; po obnovení člena
    sa sám znova aktivuje, bez novej žiadosti.
- **R26** – Fotku pri žiadosti oreže žiadateľ v prehliadači; **administrátor ju pri schvaľovaní môže orezať
  znova** z originálu (originál sa po rozhodnutí zmaže). Automatická kontrola tváre príde neskôr.
  E-mail `ess@sss.sk` sa posiela cez SMTP WebSupportu (heslo v Secret Manager).
  PDF kartička: žiadateľ si ju zvolí v žiadosti (príde e-mailom); členovi bez e-mailu ju vytlačí
  administrátor alebo predseda skupiny z detailu člena. Návrh tabuliek: `docs/data-model-ecp.md`.
- **R27** – **Obdobie obnovy:** `renewal_window_days` dní pred koncom roka (nastavenie, predvolene 60) sa v eCP
  a na portáli objaví platobný odkaz na **nasledujúci** rok (fáza 3).
- **R28** – Adresa člena je po častiach (ulica a číslo, PSČ, obec, krajina – ISO kód, predvolene SK), kvôli čistým
  dátam. Skupina má kontaktné údaje: adresu, e-mail, telefón, web a dátum založenia (migrácia `0009`).
  Inventúra pôvodnej aplikácie: `docs/old-app-inventory.md`.
- **R29** – **Dočasne sa e-maily posielajú cez Gmail** `speleo.cassovia@gmail.com` (heslo aplikácie
  v `ess-smtp-gmail-password`). Schránka `ess@sss.sk` na WebSupporte má obmedzenie prihlásenia podľa krajín;
  Cloud Run (Nemecko) a Cloud Shell sa neprihlásia. Treba požiadať správcu domény `sss.sk` o povolenie
  (Nemecko) a potom prepnúť späť (`docs/gcp-setup.md`, krok 16).
- **R30** – **Klub rozhoduje len za seba, o členstve v SSS rozhoduje administrátor.**
  - Členské sa dnes platí ručne: na výročných schôdzach skupín (január – február) sa vyberá členské do skupiny
    aj do SSS. Platby do skupín IS nerieši.
  - Kto nezaplatí, o tom rozhoduje skupina na výročnej schôdzi (zvyčajne až po roku, nie je to pravidlo) –
    **IS nič nevyraďuje automaticky** podľa platieb.
  - Člen môže nezaplatiť do skupiny, ale zaplatiť do SSS. Predseda skupiny ukončí členstvo len vo svojej skupine.
  - Keď člen nie je v žiadnej skupine, **ostáva členom SSS a jeho eCP platí**, kým administrátor nerozhodne
    (zaradiť do „SSS – nezaradení“ alebo ukončiť členstvo v SSS – požiadavka „Rozhodnutie o členstve v SSS“).
  - Vylúčiť zo SSS môže len administrátor (predseda SSS).
- **R31** – **Kartičku SSS** (PDF, rozmer platobnej karty na A4 s rámčekom na vystrihnutie) vydáva administrátor
  v detaile člena na zvolený rok – po overení, že členské do SSS na ten rok je zaplatené (do fázy 3 ručne).
  Stiahne sa na tlač alebo pošle e-mailom (pravidlá opätovného vydania: R32). Overenie `/k/<kód>` ukáže len „Člen Slovenskej speleologickej spoločnosti“ a
  „Členské zaplatené na rok XXXX“ (kartička na iný rok = upozornenie). Voľba kartičky v žiadosti o eCP je
  pre administrátora len informácia.
- **R32** – **Na každý rok jedna kartička.** Vydáva ju len administrátor (predseda skupiny nie). Tú istú kartičku
  (rovnaký QR) možno stiahnuť alebo poslať znova. Druhú na ten istý rok možno vydať len ako **náhradu** s dôvodom
  *stratená / ukradnutá / poškodená*: pôvodná okamžite prestane platiť a jej overenie ukáže „nahlásená ako
  stratená/ukradnutá“ (resp. „nahradená novou“). Kód kartičky je v DB šifrovaný (kvôli opätovnému stiahnutiu)
  a vyhľadáva sa podľa odtlačku (migrácia `0011`).
- **R33** – **Vydávanie kartičky SSS (upresnenie R31/R32):**
  - Prvú kartičku vydá **ručne a raz** predseda skupiny (alebo administrátor) – pri pridaní člena alebo keď sa
    člen stane členom SSS (povýšenie z čakateľa, obnovenie členstva). Na **tento rok**, na **nasledujúci** len
    v období platby členského (`renewal_window_days` pred koncom roka, R27).
  - Na daný rok sa kartička vydá len raz (aj nahradená sa počíta). **Náhradu** vydáva len administrátor s dôvodom.
  - Člen s kartičkou má uložený **formát (PDF alebo PNG)**. Na **ďalšie roky** mu kartička príde **e-mailom
    automaticky**, keď sa jeho členské označí ako zaplatené (fáza 3 – rozloží sa to podľa spracovania výpisov,
    žiadne hromadné rozosielanie).

## 4. Architektúra

```
Google Wallet ─┐
Prehliadač ────┼─► Webová aplikácia (Cloud Run, FastAPI) ─► PostgreSQL eSpeleoSoc2 (WebSupport, SSL)
(člen/predseda/│        ├─► Google Cloud Storage (fotky, náhodné názvy)  
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
- Parametre v nastaveniach: **výška členského** (teraz 15 €), **zľavnené členské** (teraz 7 €),
  **vek pre zľavu** (62 rokov).
- Zľavnené členské: jeden príznak člena (R13). Automatické nastavenie podľa veku beží pri otvorení nového
  roka členského; ručné nastavenie (napr. ZTP) robí administrátor.
- **Čakateľ neplatí** a nie je plnohodnotným členom; niektoré skupiny čakateľský status nepoužívajú
  (nastavenie skupiny).
- Nový člen zadaný predsedom skupiny čaká na aktiváciu administrátorom (R14).
  Návrh: rovnako aj povýšenie čakateľa na člena.
- Nezaradení členovia patria do predvoleného klubu „SSS – nezaradení“ (spravuje ho administrátor; jeho členovia nemajú zástupcu na valnom zhromaždení).

## 5a. Overovacia stránka (po naskenovaní QR)

- Výrazne: **„Člen Slovenskej speleologickej spoločnosti – jaskyniar“** (alebo výrazné upozornenie, ak
  členstvo nie je platné).
- To isté ako na preukaze: celé meno s titulmi, fotka, adresa bydliska, skupina, člen SSS od,
  stav členského na aktuálny rok.
- Kontakty: predseda skupiny a predseda SSS (meno, telefón) podľa aktuálnej organizačnej štruktúry.
- Zoznam platných dokumentov (R11).

**Jednorazový QR v eCP (R18):**
- QR v eCP obsahuje odkaz s náhodným tokenom. Po overení sa token zneplatní, vygeneruje sa nový
  a eCP v Google Wallet sa aktualizuje (nový QR).
- Odfotený QR sa dá použiť najviac raz a fotka na overovacej stránke držiteľa usvedčí.
- Denný limit overení na člena (hodnota sa určí podľa limitov Google Wallet API).
- Ochranná lehota: použitý token platí ešte krátko (napr. 15 min). Dôvody: niektoré čítačky QR
  otvoria odkaz samy na náhľad (a token by „minuli“ skôr než kontrolór) a telefón člena bez signálu
  dostane nový QR až po pripojení.
- **Kartička SSS (PDF)** má vlastný kód (iný ako eCP), vydáva sa vždy na jeden kalendárny rok a kód platí
  len pre daný rok. Overovacia stránka kartičky zobrazí len: **„Člen Slovenskej speleologickej spoločnosti“**
  a **„Členské zaplatené na rok XXXX“** – žiadne ďalšie údaje.
- Súhlas s GDPR pri žiadosti o eCP musí výslovne uvádzať, že údaje (vrátane adresy) sa zobrazia
  kontrolórovi po naskenovaní QR.

## 6. Dátový model (náčrt)

- `members` – identita (šifrované osobné údaje + blind indexy), dátum narodenia, e-mail,
  príznak **`reduced_fee`** (zľavnené členské), stav vo vzťahu k SSS (aj `expelled`). Skutočne vyrubená
  suma sa ukladá pri členskom za daný rok, takže história zostáva zachovaná.
- `clubs` – skupiny (JS a OS sa nerozlišujú), predvolený klub „SSS – nezaradení“, nastavenie „používa čakateľov“.
- `memberships` – člen × skupina, stav (`candidate`, `pending_activation`, `member`, `suspended`,
  `terminated`, `expelled`), `is_primary`, `valid_from`, `valid_to`, kto a kedy aktivoval. História sa nemaže.
- **Organizačná štruktúra:**
  - `org_positions` – funkcie: predseda SSS, podpredseda, člen výboru, predseda/člen kontrolnej komisie,
    predseda skupiny (viazaný na skupinu).
  - `position_holders` – kto zastáva funkciu, `valid_from`, `valid_to` (volebné obdobie). Po voľbách sa
    zadajú noví držitelia; starým sa funkcia ukončí dátumom.
  - Z funkcie sa odvodzuje len správa vlastnej skupiny predsedom skupiny; administratívny prístup je
    oddelený (R17). Predsedníctvo = predseda SSS + výbor + predsedovia skupín (odvodené, nie ukladané).
- `admin_users` – Google účty s administratívnym prístupom, rola `system_admin` / `admin` (R17).
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
- `passkeys`, `sessions`, `one_time_tokens`, `audit_log`.

## 7. Dáta

- Reálne dáta sú v zlom stave (papier, Word, Excel). Niekto ich musí zjednotiť do **jedného zoznamu podľa
  šablóny** (vytvoríme vo fáze 1): meno, priezvisko, skupina, voliteľne bydlisko, e-mail, dátum narodenia.
- Import prijme aj člena bez dátumu narodenia alebo e-mailu, ale taký člen **nemôže požiadať o eCP**, kým
  mu údaje nedoplní predseda skupiny alebo administrátor.
- Pre vývoj: generátor fiktívnych testovacích dát (slovenské mená, skupiny, členstvá, história, platby).

## 8. Fázy

Každá fáza končí funkčným, otestovaným a nasadeným stavom.

### Fáza 0 – Základ ✅ (dokončená 2026-09-27)
- Google Cloud projekt, rozpočtové upozornenie, Cloud Run (návod: `docs/gcp-setup.md`).
- Technický test: Cloud Run → WebSupport PostgreSQL cez SSL, zmerať oneskorenie.
- Kostra projektu (FastAPI), CI (testy pri každom pushi), migrácie DB, konfigurácia cez premenné prostredia.
- Šifrovacia vrstva pre osobné údaje + blind index, auditný log.
- Aplikácia nasadená na Cloud Run (`ess`, europe-west3), `/readyz` vidí DB `eSpeleoSoc2`.
- Generátor testovacích dát presunutý do fázy 1 (potrebuje dátový model).

**Výsledky technického testu (2026-09-27) – úspešný, R3 platí:**
- Spojenie Cloud Run (europe-west3) → `eSpeleoSoc2` funguje, PostgreSQL 14.13.
- Úsek Cloud Run → WebSupport je šifrovaný (TLS). WebSupport má pred DB proxy; úsek proxy → PostgreSQL
  je vnútri ich privátnej siete a nešifrovaný (mimo našej kontroly, akceptované).
- Otvorenie spojenia ~180 ms, dotaz ~18 ms (medián), max. ~39 ms.
- Dôsledky: pool spojení, najviac niekoľko DB dotazov na stránku.

### Fáza 1 – Administrácia
**Priebeh (2026-09-27):** hotový dátový model (migrácie 0002–0003), pravidlá členstva a oprávnení,
generátor testovacích dát, prihlásenie cez Google, obrazovky: prehľad, členovia (vyhľadávanie, filtre),
detail člena (zmeny stavu, ukončenie), zoznam požiadaviek (aktivácia so zamietnutím, rozhodnutie o
členstve v SSS), skupiny.
(2026-09-28) Doplnené: formuláre na pridanie/úpravu člena a skupiny, pridanie do skupiny, primárna
skupina, vylúčenie, funkcie (detail člena, skupiny, prehľad organizácie), certifikáty, správa prístupov
a nastavení (systémový administrátor), dokumenty.
Dizajn: zatiaľ postačujúci; úprava vzhľadu (vizuálne nedostatky) príde, keď bude hotová funkcionalita.
Návrh pre úpravu vzhľadu: krátke akcie (zamietnutie s dôvodom, ukončenie, vylúčenie, funkcia, certifikát)
v dialógových oknach namiesto polí priamo v riadku; dlhé formuláre (nový člen, skupina) ostanú ako stránky.
Import skupín a členov z CSV (`docs/import.md`, migrácia 0006 – kód skupiny) – hotové.
Fáza 1 je funkčne kompletná; zostáva úprava vzhľadu (spolu s ďalšími fázami).
Ikonky stavov (prevzaté z pôvodného projektu, `ess/static/icons`), logo aplikácie a SSS, logá skupín (adresa).

- Prihlásenie cez Google účet; hlavní systémoví administrátori z konfigurácie, ďalší systémoví administrátori a
  administrátori v aplikácii.
- Skupiny, členovia, členstvá s históriou, primárna skupina, zľavnené členské, certifikáty.
- Organizačná štruktúra a funkcie s obdobím; oprávnenia odvodené z funkcií.
- Aktivácia nových členov a zmena predsedov skupín (administrátor).
- Šablóna a import zjednoteného zoznamu členov; generátor fiktívnych testovacích dát.
- Návrh dátového modelu: `docs/data-model.md`.
- Kontroly: vylúčený sa nesmie znova stať členom, práve jedna primárna skupina.

### Fáza 2 – eCP a kartička
- Google Wallet: existujúci účet vydavateľa (Issuer) a navrhnutý eCP (class) z pôvodného projektu sa dajú
  použiť – v novom projekte stačí servisný účet s rolou v Pay & Wallet Console (overiť pri nastavení).
  Návrh vzhľadu eCP a e-mailu z pôvodného projektu: `docs/reference/wallet/` (mapovanie premenných a otázky).
  **Overené testom (28. 9. 2026, `spikes/wallet-probe`):** predvolený servisný účet Cloud Run číta triedu
  `member`, vytvára objekty a podpisuje JWT cez IAM bez kľúča; obrázky z bucketu sú čitateľné podľa názvu,
  zoznam objektov nie je verejný (403).
- Nahrávanie log skupín a fotiek tvárí do Cloud Storage (fotky s náhodnými 64-znakovými názvami, R24).
- Nový člen (R23): pri návrhu predsedu príznak „vydať eCP“ a potvrdenie súhlasu GDPR z papierovej prihlášky;
  po aktivácii dostane člen e-mail s odkazom na doplnenie fotky a overenie e-mailu → požiadavka „Vydanie eCP“.
- Verejná žiadosť: meno, priezvisko, rok narodenia, skupina, e-mail, **číslo preukazu** (povinné; ak IS nemá
  „člen SSS od“, aj ten) → overenie e-mailu
  („klikni sem“) → vyhľadanie člena. **Pokračovať sa dá len pri presnej zhode všetkých údajov.**
  Ak IS nemá dátum narodenia alebo e-mail, alebo sa e-mail nezhoduje, žiadosť sa zastaví s pokynom
  kontaktovať predsedu skupiny alebo administrátora SSS. Číslo preukazu: ak ho IS má, musí sa zhodovať
  (inak rovnako zastaviť); ak ho IS nemá, uloží sa po schválení (musí byť jedinečné). Rovnako „člen SSS od“.
  → fotka tváre + súhlasy (GDPR, notifikácie)
  + voľba PDF kartičky.
- Obrazovka spracovania žiadostí: schváliť / zamietnuť s dôvodom (napr. nevyhovujúca fotka).
- Vydanie: Google Wallet preukaz, PDF kartička, e-mail s odkazmi.
- Overovacia stránka (sekcia 5a) a správa dokumentov.
- Nastavenia vzhľadu eCP a kartičky.

### Fáza 3 – Platby
- Ročné referencie, PAYMe odkaz v eCP a na portáli.
- Nahratie bankového výpisu, automatické párovanie podľa referencie, ručné dopárovanie.
- Prehľad zaplateného členského.
- Po označení členského za zaplatené: členovi s kartičkou (`members.card_format`) sa vydá kartička na daný rok
  a pošle e-mailom (R33).

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
6. Potrebuje aj povýšenie čakateľa na člena aktiváciu administrátorom? (návrh: áno)
7. **Členstvo v SSS a zaplatené členské** (prejedná Lad'o s predsedom SSS): člen so zaplateným členským je členom
   SSS do konca roka, na ktorý zaplatil – má to IS zohľadniť pri ukončení členstva v SSS alebo pri odchode zo
   skupín? Zatiaľ platí R30 (rozhoduje administrátor, nič automaticky).

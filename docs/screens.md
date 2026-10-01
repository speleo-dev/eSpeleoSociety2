# Obrazovky a tlačidlá – prehľad na upratanie

Stav: 2026-10-01 (po fáze 5); 1. kolo úprav podľa R42 je zapracované (menu, štítky, „Späť“, hromadná platba len na portáli, „Ďalšie akcie“). Podklad na kontrolu prípadov použitia: **kde** je tlačidlo, **kto** ho vidí
a **kedy** je dostupné. Oprávnenie sa vždy kontroluje aj na serveri – skryté tlačidlo nie je jediná ochrana.

Skratky rolí: **V** verejnosť · **Č** člen s aktívnym eCP · **P** predseda skupiny (bez zástupcu) · **Z** zástupca
predsedu · **Pz** predseda, ktorého zastupuje zástupca (len číta) · **A** administrátor · **SA** superadmin (systémový administrátor).

---

## 1. Verejné stránky

| Obrazovka | Adresa | Kto | Tlačidlá / obsah | Kedy |
|---|---|---|---|---|
| Úvod | `/` | V | **Požiadať o eCP alebo kartičku SSS** (odkaz na administráciu tu nie je – R48) | vždy |
| Žiadosť o eCP / kartičku | `/ecp/apply` | V | popis eCP a kartičky s malou ukážkou, odkaz na inštaláciu Peňaženky Google, upozornenie, že druh dokladu sa volí v 2. kroku · Odoslať (meno, priezvisko, dátum narodenia, e-mail, č. preukazu, člen od, skupina) | vždy; rovnaká odpoveď, aj keď člen neexistuje |
| Žiadosť odoslaná | `/ecp/apply/sent` | V | – | po odoslaní |
| Overenie e-mailu | `/ecp/email/<token>` | V | – (presmeruje na fotku) | odkaz z e-mailu, jednorazový, 24 h |
| Druh dokladu, fotka a súhlasy | `/ecp/apply/photo` | V | **Druh dokladu: eCP / len kartička SSS** (R49; pri kartičke bez fotky, formát povinný) · Výber súboru · **Odfotiť kamerou** · Odfotiť / Zrušiť · posun a veľkosť výrezu · súhlas GDPR (povinný) · oznámenia · kartička: nie / PDF / obrázok PNG · **Odoslať žiadosť** | po overení e-mailu; „Odfotiť kamerou“ len ak prehliadač má kameru; voľba kartičky len ak člen ešte nemá zvolený formát (R47) |
| Fotka nového člena | `/ecp/photo/<token>` | V | ako vyššie | odkaz z e-mailu po aktivácii člena s voľbou „Vydať eCP“ |
| Hotovo | `/ecp/apply/done` | V | – | po odoslaní žiadosti |
| Overenie eCP | `/v/<token>` | V (kontrolór) | – (výsledok, fotka, údaje, kontakty, dokumenty) | QR z eCP; jednorazový, 15 min ochranná lehota |
| Overenie kartičky | `/k/<kód>` | V | – (len „Člen SSS“ a rok) | QR z kartičky |

## 2. Portál člena (`/p/<kľúč>` z eCP, `/portal`)

Menu (R52, na mobile ☰): Členovia · Skupiny · Organizácia (Výbor, Dokumenty, Notifikácie) · štítok s menom
(Môj profil, Administrácia – len člen s rolou admin, Odhlásiť). Logo vedie na profil. Vedľa loga je vždy
viditeľný štítok roly (Člen / Predseda / Zástupca predsedu; v administrácii Administrátor / Superadmin), aj na mobile.

### Prihlásenie
| Obrazovka | Tlačidlá | Kedy |
|---|---|---|
| Prihlásenie (`/p/<kľúč>`) | **Prihlásiť odtlačkom prsta / tvárou** · Poslať kód na e-mail | odtlačok len ak prehliadač podporuje passkeys; stránka len pre aktívny eCP |
| Kód z e-mailu | Prihlásiť · Poslať nový kód | 10 min, 5 pokusov, len v tom istom prehliadači |
| Príliš veľa zariadení | Odhlásiť toto zariadenie a pokračovať (pri každom zariadení) | keď je člen prihlásený na `portal_max_devices` (2) zariadeniach |
| Neprihlásený / odhlásený | Prihlásiť odtlačkom prsta / tvárou | – |

### Domov (`/portal`) – Č, P, Z, Pz
| Časť | Tlačidlá | Kedy |
|---|---|---|
| Ponuka passkey | **Nastaviť prihlásenie odtlačkom / tvárou** | po prihlásení kódom alebo keď člen nemá passkey; len ak prehliadač podporuje |
| Platba | **Zaplatiť členské SSS na rok X** | kým nie je zaplatené, je nastavený IBAN a známka na rok X je zverejnená (R45) |
| Vstup do jaskyne | Nahlásiť vstup (rozbaľovacie) · **Som vonku** · Predĺžiť návrat | „Som vonku“ a „Predĺžiť“ len pri otvorenom hlásení |
| Členstvo | odkazy na skupiny | odkaz nie pri „SSS – nezaradení“ |
| Dokumenty | odkazy | platné dokumenty |
| Moje údaje | – (len čítanie) | – |
| Moje zariadenia | Odhlásiť (pri inom zariadení) | – |
| Päta | Odhlásiť | – |

### Skupina (`/portal/clubs/<id>`)
| Časť | Kto | Tlačidlá | Kedy |
|---|---|---|---|
| Zoznam členov | Č | – (meno, stav, telefón, e-mail; všetci vrátane čakateľov) | člen skupiny |
| Zoznam členov | P, Z, Pz | – (všetci vrátane čakateľov, bydlisko, č. preukazu) | – |
| Správa skupiny | P, Z | **Pridať čakateľa / navrhnúť člena** · Členské a hromadná platba · mená sú odkazy na detail | kto skupinu práve spravuje |
| Zastupovanie | P | Preniesť správu (výber zástupcu, rozbaľovacie) | predseda bez zástupcu, existuje vhodný člen |
| Zastupovanie | Pz | **Prevziať správu** | počas zastupovania |
| Zastupovanie | Z | Zrušiť administráciu klubu | počas zastupovania |

## 3. Portál predsedu – správa skupiny (P, Z)

| Obrazovka | Tlačidlá | Kedy |
|---|---|---|
| Pridať do skupiny („Nový člen / čakateľ“ v skupine, skupina vyplnená) | Uložiť (čakateľ / nový člen, voľba **Vydať eCP**, kartička SSS: nie / PDF / PNG – R47) | „čakateľ“ len ak skupina používa čakateľov |
| Detail člena | Upraviť údaje | člen skupiny |
| Detail člena – stav | Navrhnúť za člena | čakateľ |
|  | Vrátiť medzi čakateľov | navrhnutý (čaká na aktiváciu) |
|  | Pozastaviť členstvo | člen |
|  | Obnoviť členstvo | pozastavený |
|  | Ukončiť členstvo v skupine | vždy |
| Detail člena – kartička | Vydať a stiahnuť kartičku (rok, PDF/PNG) | stav „člen“ a na rok ešte nebola vydaná |
| Úprava údajov | Uložiť · Zrušiť | zľavnené členské sa tu nemení |
| Členské | výber roka · Vytvoriť platobný odkaz (výber členov) | rok platby; ďalší rok v období platby |
| Hromadná platba | **Zaplatiť X €** · Zrušiť platobný odkaz | vytvoriť len po zverejnení ročnej známky na daný rok (R45); zrušiť len kým nie je nič zaplatené |

## 4. Administrácia (tajná adresa `/<ESS_ADMIN_PATH>`, vo vývoji `/admin`; Google prihlásenie – R48)

Menu (R50): Členovia · Skupiny · Správa organizácie (Výbor; A navyše Členské, Ročná známka, Bankové výpisy,
Požiadavky; obaja Dokumenty) · Notifikácie · Nastavenia (Nastavenia aplikácie, Import; SA aj Prístupy) · štítky
(len A): čakajúce požiadavky (červený), nezaplatené členské (zlatý) · štítok s menom → Odhlásiť (admin cez eCP:
Môj portál, odhlásenie z portálu). SA vidí členov obmedzene (meno, skupiny, e-mail, telefón) s funkciami a
prístupom administrátora; skupiny len číta. Na mobile ☰.

| Obrazovka | Kto | Tlačidlá | Kedy |
|---|---|---|---|
| Prehľad | A | karty: požiadavky, členovia SSS, skupiny | – |
| Členovia | A | hľadanie, filtre skupina/stav · Nový člen / čakateľ (pri filtri skupiny „v tejto skupine“) | – |
| Nový člen / čakateľ | A | Uložiť (skupina, člen/čakateľ, **Vydať eCP**, **Vydať kartičku** + rok, formát) | zo skupiny je skupina vyplnená a nemenná, zo zoznamu SSS ju admin vyberie |
| Detail člena – hlavička | A | Upraviť údaje | – |
| Detail člena – portál | A | Odhlásiť zo všetkých zariadení | člen je prihlásený aspoň na 1 zariadení |
| Detail člena – členské | A | Platobný odkaz člena (rok) · Označiť ako zaplatené (rok, poznámka; len A, nie SA – R46) | nezaplatený rok platby; nie pri vylúčenom / ukončenom |
| Detail člena – kartička | A | Stiahnuť znova · Poslať znova · Vydať náhradnú (dôvod) · Vydať kartičku (rok) | podľa vydaných kartičiek; „Poslať“ len s e-mailom |
| Detail člena – členstvá | A | Aktivovať · Navrhnúť za člena · Pozastaviť · Obnoviť · Nastaviť ako primárnu · Ukončiť v skupine · Pridať do skupiny | podľa stavu (ako pri predsedovi + aktivácia) |
| Detail člena – SSS | A | Zaradiť do „SSS – nezaradení“ | čaká na rozhodnutie alebo ukončené členstvo v SSS |
| Detail člena – funkcie | A | Ukončiť · Priradiť funkciu | priradiť len člen SSS |
| Detail člena – certifikáty | A | Odstrániť · Pridať certifikát | – |
| Detail člena – vylúčenie | A | Vylúčiť zo SSS (dôvod) | nie vylúčený; nevratné |
| Skupiny | A | Nová skupina · detail | – |
| Detail skupiny | A | Uložiť · Nahrať / odstrániť logo · Zadať predsedu · Určiť zástupcu / Ukončiť zastupovanie · Členovia skupiny · **Nový člen / čakateľ** | zastupovanie nie pri „SSS – nezaradení“ |
| Členské | A | rok · Export CSV · stav platby cez eCP (odkaz na Ročnú známku) · Odoslať ďalšiu dávku · Bankové výpisy | „dávka“ len ak čakajú eCP |
| Ročná známka | A | Vygenerovať náhľad / Iné farby · **Zverejniť túto známku** (potvrdenie) · Nahrať šablónu | len kým známka na rok splatnosti nie je zverejnená (R45); inak len obrázok |
| Platobný odkaz (detail) | A | Otvoriť PAYMe · Zrušiť | zrušiť len otvorený |
| Bankové výpisy | A | Nahrať a spárovať (formát, súbor) | – |
| Požiadavky | A | Aktivovať / Zamietnuť · Zaradiť do nezaradených / Ukončiť členstvo v SSS · Posúdiť žiadosť · Priradiť platbu / Vybavené | podľa typu požiadavky |
| Žiadosť o eCP / kartičku | A | Orezať fotku znova (hneď pod fotkou) · Schváliť a vydať eCP (pri kartičke „Schváliť kartičku SSS“) · Zamietnuť (dôvod) | len podaná žiadosť |
| Výbor | A, SA | len funkcie SSS (predsedovia skupín sú v zozname Skupiny) · Ukončiť (len SA) | – |
| Detail člena (SA) | SA | Priradiť funkciu (aj Výbor) · Udeliť / Odobrať prístup administrátora (R51) | – |
| Dokumenty | A | Pridať · Odstrániť | – |
| Notifikácie | A | Odoslať · Odoslať ďalšiu dávku | „Odoslať“ len ak dnes ešte zostáva z limitu 3 |
| Import | SA | Skontrolovať / Vykonať import (skupiny, členovia) · vzory CSV · kódy skupín | – |
| Prístupy | SA | Pridať prístup · Odobrať | hlavných SA (z konfigurácie) nemožno odobrať |
| Nastavenia | A, SA | Upraviť → Zrušiť zmeny / Uložiť zmeny · Pridať typ certifikátu | A: len členské a platba (R44) |
| Nastavenia – len SA | SA | lehoty eCP, QR, zariadenia portálu · Testovací e-mail | – |

## 5. Postrehy na upratanie (návrhy)

1. **Menu administrácie má 10–12 položiek.** Návrh: Členovia · Skupiny · Požiadavky · Členské (s Bankovými výpismi)
   · eCP (Notifikácie) · Ďalšie (Organizácia, Dokumenty, Import) · Nastavenia (SA, s Prístupmi).
2. **Detail člena v administrácii je dlhý.** Návrh poradia: údaje a stav → členstvá → eCP a portál → členské →
   kartička → funkcie → certifikáty → história → vylúčenie. Menej časté akcie rozbaliť až na kliknutie.
3. **Hromadná platba je na dvoch miestach** (administrácia – detail skupiny a portál predsedu). Ponechať obe?
4. **Portál nemá hornú navigáciu** (používa verejnú hlavičku). Návrh: Domov · Moja skupina (pre P/Z) · Odhlásiť.
5. **Domov na portáli** – poradie: platba → jaskyňa → členstvo → dokumenty → údaje → zariadenia. Vyhovuje?
6. **Prehľad administrácie** ukazuje len 3 čísla. Návrh doplniť: žiadosti o eCP, nespárované platby, eCP čakajúce
   na odoslanie do Google Wallet, otvorené hlásenia vstupu do jaskyne (bez osobných údajov).
7. **Predseda nevidí zoznam svojich návrhov** čakajúcich na aktiváciu inak než podľa stavu v zozname členov.
   Stačí to, alebo samostatný zoznam?
8. **Ukončenie členstva v skupine** je pri každom členovi vždy viditeľné (s potvrdením). Skryť pod „Ďalšie akcie“?
9. **Tlačidlá bez potvrdenia**, ktoré menia dáta: Uložiť formuláre, Pridať do skupiny, Priradiť funkciu, Pridať
   dokument / certifikát. Potvrdenie majú: ukončenia, vylúčenie, zmeny stavu na portáli, zrušenia, odoslanie notifikácie.

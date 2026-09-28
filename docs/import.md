# Import skupín a členov z CSV

Návod pre toho, kto pripravuje zjednotený zoznam skupín a členov SSS. Import sa robí v administrácii
v časti **Import**.

## Postup

1. **Skupiny:** pripravte zoznam skupín s kódmi a naimportujte ho.
2. **Kódy:** v administrácii si stiahnite „kódy existujúcich skupín“ – tieto kódy použijete v zozname členov.
3. **Členovia:** pripravte zoznam členov a naimportujte ho.

Každý súbor sa najprv **len skontroluje**. Uloží sa až vtedy, keď ho nahráte znova so zaškrtnutým
„Vykonať import“, a len ak **nemá žiadnu chybu** – buď sa uloží celý, alebo nič. Chyby sa vypíšu
s číslom riadku (riadok 1 je hlavička).

Vzorové súbory si stiahnete priamo na stránke importu.

## Formát súboru

- CSV v kódovaní **UTF-8** (v Exceli: *Uložiť ako → CSV UTF-8 (oddelené čiarkami)*). Starší „CSV (oddelené
  bodkočiarkou)“ z Excelu v kódovaní Windows-1250 funguje tiež.
- Oddeľovač bodkočiarka `;` alebo čiarka `,` – rozpozná sa automaticky.
- Prvý riadok je hlavička. Na veľkosti písmen, diakritike a medzerách v hlavičke nezáleží
  („Kód skupiny“ = `kod_skupiny`). Poradie stĺpcov je ľubovoľné.
- Prázdne riadky sa preskočia.

## Skupiny

| Stĺpec | Povinný | Význam |
|---|---|---|
| `kod` | áno | krátky jedinečný kód, napr. `JS-DEM`, `OS-LIP` (A–Z, 0–9, `-`, `_`, najviac 20 znakov) |
| `nazov` | áno | celý názov skupiny |
| `skratka` | nie | skratka na preukaz |
| `cakatelia` | nie | `X` = skupina používa čakateľov, prázdne = nepoužíva (ak stĺpec chýba úplne, používa) |
| `logo` | nie | verejná adresa obrázka loga (`https://…`, napr. v Cloud Storage) |

Klub „SSS – nezaradení“ už existuje a má kód **`SSS`** – do súboru ho nepíšte.

## Členovia

**Jeden riadok = jedno členstvo v skupine.** Člen, ktorý je vo viacerých skupinách, má viac riadkov.
Údaje o osobe sa berú **len z riadku s primárnou skupinou** (stĺpec `primarna` = `X`). V ostatných riadkoch
toho istého člena stačí vyplniť `kod_skupiny`, `meno` a `priezvisko`.

| Stĺpec | Povinný | Význam |
|---|---|---|
| `kod_skupiny` | áno | kód skupiny zo zoznamu skupín (`SSS` = nezaradení) |
| `primarna` | áno (stĺpec) | `X` = primárna skupina člena; prázdne = ďalšie členstvo |
| `stav` | nie | `člen` (predvolené) alebo `čakateľ` |
| `titul_pred`, `titul_za` | nie | tituly (Ing., PhD.) |
| `meno`, `priezvisko` | áno | |
| `datum_narodenia` | nie* | `31.12.1980`, `31. 12. 1980` alebo `1980-12-31` |
| `email` | nie* | e-mail; manželia môžu mať rovnaký |
| `telefon` | nie | |
| `bydlisko` | nie | |
| `cislo_preukazu` | nie | číslo papierového preukazu; musí byť jedinečné |
| `clen_sss_od` | nie | dátum alebo len rok (`1995` = 1. 1. 1995) |
| `zlava` | nie | `X` = zľavnené členské (napr. ZTP; podľa veku sa nastaví automaticky) |

\* Bez dátumu narodenia a e-mailu nebude môcť člen sám požiadať o eCP – údaje neskôr doplní predseda
skupiny alebo administrátor.

Namiesto `X` sa v stĺpcoch `primarna` a `zlava` dá použiť aj `áno`, `true` alebo `1`.

### Ďalšie členstvá toho istého človeka

Riadok bez `X` v stĺpci `primarna` sa spojí s riadkom s `X` podľa mena a priezviska. Ak sú v súbore dvaja
ľudia s rovnakým menom, vyplňte v riadku ďalšieho členstva aj `datum_narodenia` alebo `cislo_preukazu`,
inak import ohlási chybu „nedá sa jednoznačne priradiť“.

## Čo import kontroluje

- existujúci a aktívny kód skupiny, čakateľ len v skupine, ktorá čakateľov používa,
- platné dátumy a e-maily, vyplnené meno a priezvisko,
- ten istý človek označený ako primárny dvakrát (rovnaké meno a dátum narodenia),
- jedinečnosť čísla preukazu (v súbore aj v databáze),
- člen s rovnakým menom a rokom narodenia, ktorý už v databáze je (ochrana pred dvojitým importom).

Chybové hlásenia neobsahujú osobné údaje, len číslo riadku a stĺpec.

## Osobné údaje

Súbor so zoznamom členov obsahuje osobné údaje. Posielajte ho len zabezpečene a po úspešnom importe ho
zmažte (aj z e-mailov a zdieľaných priečinkov). V systéme sú údaje uložené šifrovane.

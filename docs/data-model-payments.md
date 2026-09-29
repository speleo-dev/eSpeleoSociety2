# Dátový model – fáza 3: platby

Stav: odsúhlasené 2026-09-29, tabuľky v migrácii `0013`.
Hotové (krok 1): členské, referencie člena a hromadnej platby, PAYMe odkaz, ručné označenie „zaplatené“, pripísanie
platby k referencii (úplná, čiastočná, preplatok) – `ess/services/payments.py`, administrácia `ess/web/admin_payments.py`
(detail člena → Členské, detail skupiny → Hromadná platba, Nastavenia → IBAN).
Zostáva: účinky zaplatenia (eCP „Platný do“ a ročná známka, kartička e-mailom), odkaz v eCP, výpis a Požiadavky. Pravidlá: R7, R27, R30, R33–R36 v `docs/PLAN.md`.
Konvencie ako v `docs/data-model.md`.

## Členské

`fees` – členské člena na rok (jeden riadok na člena a rok). Vzniká, keď sa prvýkrát treba pozrieť na sumu
(platobný odkaz, hromadná platba, ručné označenie).

| Stĺpec | Význam |
|---|---|
| `member_id`, `year` | jedinečná dvojica |
| `amount`, `reduced` | vyrubená suma a či bola zľavnená (podľa nastavení a príznaku člena v čase vyrubenia) |
| `paid_at` | kedy bolo zaplatené; prázdne = nezaplatené |
| `payment_reference_id` | ktorou referenciou bolo zaplatené; prázdne pri ručnom označení |
| `paid_manually_by`, `note` | ručné označenie administrátorom (R36) |

Čiastočná platba sa eviduje pri referencii, nie pri členskom: členské je zaplatené až vtedy, keď je
referencia zaplatená celá (pri hromadnej platbe by sa čiastočná suma nedala spravodlivo rozdeliť).

## Platobné referencie

`payment_references` – kód pre pole „referencia platiteľa“ (R35).

| Stĺpec | Význam |
|---|---|
| `code` | 12 znakov, jedinečný, bez významu |
| `kind` | `member` (člen za seba) / `bulk` (hromadná platba predsedu) |
| `year` | rok členského |
| `club_id` | pri `bulk` skupina, za ktorú predseda platí |
| `created_by` | kto vygeneroval |
| `expected_amount`, `paid_amount` | súčet súm členov / doteraz prijaté |
| `status` | `open`, `partial`, `paid`, `cancelled` |

`payment_reference_items` – ktorí členovia (ich členské) patria k referencii a za akú sumu. Pri `member` jeden riadok.

Člen má na rok najviac jednu neukončenú referenciu `member` (odkaz v eCP sa nemení).

## Bankové výpisy (implementuje sa po vzorovom výpise)

`bank_statements` – nahratý výpis: kto a kedy nahral, formát, odtlačok súboru (ten istý výpis sa nenahrá dvakrát).

`bank_transactions` – prijaté platby z výpisu.

| Stĺpec | Význam |
|---|---|
| `bank_ref` | identifikátor transakcie v banke – ochrana proti dvojitému spárovaniu |
| `booked_on`, `amount`, `currency` | |
| `payer_reference` | referencia platiteľa z výpisu |
| `payer_name_enc`, `payer_iban_enc` | šifrované (len na ručné dopárovanie) |
| `payment_reference_id` | spárovaná referencia |
| `result` | `paid`, `partial`, `overpaid`, `unknown_reference`, `manual`, `ignored` |

Čo sa nespáruje automaticky (neznáma referencia, preplatok), ide do Požiadaviek na ručné vybavenie
(`tasks.bank_transaction_id`; takáto požiadavka nemusí mať člena).

## Nastavenia

| Kľúč | Význam |
|---|---|
| `payment_iban` | IBAN účtu SSS pre členské |
| `payment_account_name` | názov príjemcu v PAYMe odkaze |

## Rozhodnuté

1. **Preplatok** (napr. člen zaplatí sám a zároveň je v hromadnej platbe): členské sa označí ako zaplatené
   a preplatok ide do Požiadaviek administrátorovi (vrátenie / dar).
2. **Hromadná platba** ponúkne len členov skupiny v stave „člen“, ktorí na daný rok ešte nemajú zaplatené
   a nie sú v inej otvorenej hromadnej platbe.
3. Keď sa členské zaplatí inak (ručne, inou referenciou), otvorená referencia `member` toho člena sa zruší.

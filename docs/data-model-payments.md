# Dátový model – fáza 3: platby (návrh na odsúhlasenie)

Pravidlá: R7, R27, R30, R33–R36 v `docs/PLAN.md`. Konvencie ako v `docs/data-model.md`.

## Členské

`fees` – členské člena na rok (jeden riadok na člena a rok).

| Stĺpec | Význam |
|---|---|
| `member_id`, `year` | jedinečná dvojica |
| `amount` | vyrubená suma (plné alebo zľavnené členské v čase vyrubenia) |
| `reduced` | či bolo zľavnené |
| `paid_amount` | doteraz spárované (pri čiastočnej platbe menej ako `amount`) |
| `paid_at` | kedy bolo zaplatené celé; prázdne = nezaplatené |
| `paid_manually_by`, `note` | ručné označenie administrátorom (R36) |

## Platobné referencie

`payment_references` – kód pre pole „referencia platiteľa“ (R35).

| Stĺpec | Význam |
|---|---|
| `code` | 12 znakov, jedinečný, bez významu |
| `kind` | `member` (člen za seba) / `bulk` (hromadná platba predsedu) |
| `year` | rok členského |
| `created_by` | kto vygeneroval (pri `bulk` predseda) |
| `expected_amount`, `paid_amount` | súčet súm členov / doteraz spárované |
| `status` | `open`, `partial`, `paid`, `cancelled` |

`payment_reference_items` – ktorí členovia patria k referencii a za akú sumu (pri `member` jeden riadok).

## Bankové výpisy

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

Čo sa nespáruje automaticky (neznáma referencia, preplatok), ide do Požiadaviek na ručné vybavenie.

## Otázky na odsúhlasenie

1. **Preplatok** (napr. člen zaplatí sám a zároveň je v hromadnej platbe): členské sa označí ako zaplatené
   a preplatok ide do Požiadaviek administrátorovi (vrátenie / dar). Návrh: áno.
2. **Hromadná platba** ponúkne len členov, ktorí ešte nemajú zaplatené a nie sú v inej otvorenej hromadnej
   platbe. Návrh: áno.

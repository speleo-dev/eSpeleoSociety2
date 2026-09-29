# Dátový model – fáza 4: portál člena

Pravidlá: R5, R37, R38 v `docs/PLAN.md`. Konvencie ako v `docs/data-model.md`.

## Prihlásenie (R38, migrácia `0017`)

- `ecp_passes.portal_key` – náhodný identifikátor v odkaze „Portál eSS“ v eCP (`/p/<kľúč>`). Určuje len, kto sa
  prihlasuje; nie je dôkaz identity. Vydané eCP ho dostali v migrácii a odkaz sa do nich odošle po dávkach.
- `member_login_codes` – 6-miestny kód z e-mailu: `member_id`, `code_hash`, `browser_hash` (kód platí len
  v prehliadači, ktorý oň požiadal), `expires_at` (10 min), `attempts` (najviac 5), `used_at`.
  Najviac 5 kódov za hodinu na člena.
- `member_sessions` – prihlásené zariadenie: `member_id`, `token_hash` (token je len v cookie `ess_member`),
  `method` (`email_code`, neskôr `passkey`), `expires_at` (90 dní), `revoked_at`.
- Prístup má len člen s **aktívnym** eCP; kontroluje sa pri každej požiadavke.

Hotové (krok 1): prihlásenie kódom z e-mailu, domovská stránka člena (`/portal`), odhlásenie, v administrácii
počet prihlásených zariadení a „Odhlásiť zo všetkých zariadení“.
Zostáva: passkeys, skupina a jej členovia (R37), dokumenty, novinky, notifikácie, hlásenie vstupu do jaskyne.

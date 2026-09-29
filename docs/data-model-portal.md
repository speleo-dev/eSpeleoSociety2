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
- `member_passkeys` – passkeys (WebAuthn, migrácia `0018`): `credential_id`, `public_key`, `sign_count`,
  `last_used_at`. Ukladá sa len verejný kľúč. RP id = hostiteľ verejnej adresy aplikácie (`ESS_PUBLIC_BASE_URL`).
  Passkey je „discoverable“ – prihlásenie funguje aj bez odkazu z eCP. Administrátorské „Odhlásiť zo všetkých
  zariadení“ passkeys zmaže.
- Najviac `portal_max_devices` (2) prihlásených zariadení (R40, migrácia `0019`): `member_sessions.device`
  (napr. „Chrome, Android“), `last_seen_at`; `member_passkeys.session_id` – passkey patrí zariadeniu a odhlásením
  zariadenia (výberom pri prihlásení na ďalšom) sa zmaže. Dobrovoľné odhlásenie passkey ponechá.
- Prístup má len člen s **aktívnym** eCP; kontroluje sa pri každej požiadavke.

Hotové (krok 1): prihlásenie kódom z e-mailu, domovská stránka člena (`/portal`), odhlásenie, v administrácii
počet prihlásených zariadení a „Odhlásiť zo všetkých zariadení“.
Hotové (krok 2): passkeys – `ess/services/passkeys.py`, `static/passkey.js`; ponuka po prihlásení kódom.
Hotové (krok 3): skupina na portáli (R37) – `/portal/clubs/<id>` pre každého člena skupiny (nie pre „SSS – nezaradení“):
bežný člen vidí členov v stave „člen“ s telefónom a e-mailom; predseda (aj počas zastupovania) a zástupca všetkých
vrátane čakateľov, bydliska a čísla preukazu. Tlačidlá „Preniesť správu“ a „Prevziať správu“ (predseda) a „Zrušiť
administráciu klubu“ (zástupca), všetky s potvrdením.
Zostáva: dokumenty, novinky, notifikácie, hlásenie vstupu do jaskyne.

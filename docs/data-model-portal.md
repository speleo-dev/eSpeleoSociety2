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
Hotové (krok 4): na portáli platné dokumenty. Novinky sa nerobia (R41) – tabuľka `news` z migrácie `0020` sa
v `0021` zmazala.
Hotové (krok 5): notifikácie do eCP (R41) – `ecp_notifications`, `ecp_notification_deliveries` (migrácia `0022`),
`ess/services/ecp_notifications.py`, administrácia **Notifikácie** (`/admin/notifications`). Len administrátor, celej SSS,
len členom s aktívnym eCP a súhlasom „oznámenia“ (posledný záznam v `consents`); najviac 3 za 24 hodín; odosiela sa
po dávkach 50, chybné doručenie sa skúša 5-krát.
Hotové (krok 6): hlásenie vstupu do jaskyne (R41) – `cave_trips` (migrácia `0023`; jaskyňa a spolulezci šifrovane),
`ess/services/cave_trips.py`; na portáli „Nahlásiť vstup“, „Som vonku“, „Predĺžiť návrat“. Pripomienka členovi 30 min
a upozornenie predsedovi primárnej skupiny 60 min po plánovanom návrate; kontrolu spúšťa Cloud Scheduler
(`POST /internal/tick` s hlavičkou `X-ESS-Scheduler-Token`, `docs/gcp-setup.md` krok 18), ktorý zároveň posiela
čakajúce dávky do Google Wallet.

## Fáza 5 – portál predsedu

Hotové (`ess/web/portal_chair.py`, `/portal/clubs/<id>/…`), len pre toho, kto skupinu práve spravuje
(`access.can_manage_club` – predseda bez zástupcu alebo zástupca):
- pridanie čakateľa alebo návrh nového člena (aktivuje administrátor), voliteľne „Vydať eCP“ (súhlas z papierovej prihlášky),
- detail člena skupiny, úprava údajov (zľavnené členské nemení), zmeny stavu: navrhnúť čakateľa za člena, vrátiť návrh,
  pozastaviť, obnoviť; ukončenie členstva v skupine (o členstve v SSS rozhodne administrátor),
- vydanie prvej kartičky SSS na rok (stiahnutie PDF/PNG, R33),
- členské skupiny na rok (kto zaplatil) a hromadná platba (výber členov, PAYMe odkaz, zrušenie nezaplatenej).

# Nastavenie Google Cloud (fáza 0)

Cieľ: pripraviť Google Cloud projekt a overiť, že Cloud Run sa vie šifrovane pripojiť k databáze
`eSpeleoSoc2` na WebSupporte a s akým oneskorením.

Všetky príkazy sa spúšťajú v **Cloud Shell** (ikona terminálu `>_` vpravo hore v
[console.cloud.google.com](https://console.cloud.google.com)). Nič netreba inštalovať do počítača.

## 1. Projekt

Možnosti:
- použiť existujúci projekt, v ktorom je bucket s fotkami zo starej aplikácie, alebo
- vytvoriť nový projekt: menu projektu hore → *New project* → názov napr. `espeleosociety`.

Poznač si **Project ID** (nemusí sa zhodovať s názvom). V Cloud Shell:

```bash
gcloud config set project PROJECT_ID
```

## 2. Fakturácia a rozpočtové upozornenie

Cloud Run vyžaduje prepojený fakturačný účet (platobná karta), aj keď sa zmestíme do bezplatného limitu.

1. *Billing* → prepojiť fakturačný účet s projektom.
2. *Billing* → *Budgets & alerts* → *Create budget*: suma **1 €**, upozornenia na 50 %, 90 % a 100 %.

Rozpočet **nezastaví** služby, iba pošle e-mail. Preto ho nastav nízko, nech o prípadných nákladoch
vieš hneď.

## 3. Zapnutie služieb

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 4. Príprava databázy na WebSupporte

V administrácii WebSupportu pri databáze `eSpeleoSoc2`:
1. Zisti **hostiteľa a port pre externý prístup** (sekcia „Odporúčané pripojenie“).
2. Vytvor samostatného DB používateľa pre aplikáciu so silným heslom (napr. 32 náhodných znakov).
3. Pozri, či je možné obmedziť prístup podľa IP. (Cloud Run nemá pevnú IP adresu, takže obmedzenie
   zatiaľ nepoužijeme, ale je dobré vedieť, či existuje.)

## 5. Uloženie prístupu do databázy ako tajomstvo

Heslo nikdy nepíš do súborov ani do repozitára. Ulož ho do Secret Manageru (v Cloud Shell):

```bash
read -s -p "DB heslo: " DBPASS; echo
printf 'postgresql://DB_USER:%s@DB_HOST:5432/eSpeleoSoc2' "$DBPASS" \
  | gcloud secrets create ess-database-url --data-file=-
unset DBPASS
```

`DB_USER` a `DB_HOST` nahraď skutočnými hodnotami. Ak heslo obsahuje znaky `@ : / ? #`, treba ich
zakódovať (alebo vygenerovať heslo len z písmen a číslic).

Povolenie čítať tajomstvo pre Cloud Run:

```bash
PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding ess-database-url \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## 6. Nasadenie testovacej aplikácie

```bash
git clone https://github.com/speleo-dev/eSpeleoSociety2.git
cd eSpeleoSociety2/spikes/db-probe

REGION=europe-west3   # Frankfurt – najbližšie k Bratislave
gcloud run deploy ess-db-probe --source . --region $REGION \
  --no-allow-unauthenticated \
  --set-secrets DATABASE_URL=ess-database-url:latest \
  --max-instances 1
```

Pri prvom nasadení sa gcloud môže opýtať na vytvorenie úložiska Artifact Registry. Odpovedz `Y`.
`--no-allow-unauthenticated` znamená, že služba nie je verejná a zavolať ju môžeš iba ty.

## 7. Spustenie testu

```bash
URL=$(gcloud run services describe ess-db-probe --region $REGION --format='value(status.url)')
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/probe"; echo
```

Výsledok skopíruj do konverzácie. Neobsahuje heslá. Očakávaný tvar:

```json
{"ok": true, "server_version": "PostgreSQL 14...", "ssl": true, "ssl_protocol": "TLSv1.3",
 "connect_ms": 120.0, "query_ms_median": 15.0, "query_ms_max": 20.0}
```

Ako výsledok vyhodnotiť:
- `"ok": true` a `"ssl": true`: spojenie funguje a je šifrované.
- `query_ms_median`: čas jedného dotazu do databázy. Do približne 20 ms je to v poriadku.
- `"ok": false`: chybová hláška napovie, či je problém v SSL, prihlásení alebo sieťovom spojení.

Ak chceš porovnať regióny, zopakuj krok 6 a 7 s `REGION=europe-west1` (Belgicko). Pri výbere regiónu
over na [stránke cien Cloud Run](https://cloud.google.com/run/pricing), do ktorej cenovej úrovne
(Tier 1 alebo Tier 2) patrí.

## 8. Upratanie po teste

```bash
gcloud run services delete ess-db-probe --region $REGION
```

Tajomstvo `ess-database-url` ponechaj, použije ho skutočná aplikácia.

## 9. Šifrovacie kľúče pre osobné údaje

Kľúče sa vygenerujú priamo v Cloud Shell a uložia do Secret Manageru. Na obrazovke sa nikdy nezobrazia.

```bash
printf 'k%s:%s' "$(date +%Y%m)" "$(openssl rand -base64 32)" \
  | gcloud secrets create ess-pii-keys --data-file=-
openssl rand -base64 32 | tr -d '\n' \
  | gcloud secrets create ess-blind-index-key --data-file=-

PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
for s in ess-pii-keys ess-blind-index-key; do
  gcloud secrets add-iam-policy-binding $s \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

> **Dôležité:** ak sa kľúč `ess-pii-keys` stratí, osobné údaje v databáze už **nikto nerozšifruje**.
> Secret Manager si ho pamätá, ale pre istotu si urob zálohu mimo Google (napr. správca hesiel).
> Záloha sa robí iba raz, pred prvým uložením reálnych údajov:
> `gcloud secrets versions access latest --secret=ess-pii-keys` a obsah ulož do správcu hesiel.
> Rovnako `ess-blind-index-key`.

## 10. Migrácia databázy

Spúšťa sa z Cloud Shell. Pripojenie k DB sa vezme zo Secret Manageru a nikam sa neuloží.

```bash
cd ~/eSpeleoSociety2 && git pull
python3 -m venv .venv && .venv/bin/pip install -q .
ESS_DATABASE_URL="$(gcloud secrets versions access latest --secret=ess-database-url)" \
  .venv/bin/alembic upgrade head
```

Očakávaný výstup končí riadkom `Running upgrade  -> 0001, Create audit_log table.`

## 11. Nasadenie aplikácie

```bash
cd ~/eSpeleoSociety2
REGION=europe-west3
gcloud run deploy ess --source . --region $REGION \
  --allow-unauthenticated \
  --set-env-vars ESS_ENVIRONMENT=dev \
  --set-secrets ESS_DATABASE_URL=ess-database-url:latest,ESS_PII_KEYS=ess-pii-keys:latest,ESS_BLIND_INDEX_KEY=ess-blind-index-key:latest \
  --max-instances 2
```

`--allow-unauthenticated` znamená, že stránka je verejná. Zatiaľ obsahuje len úvodnú stránku
„vo výstavbe“, takže to nevadí.

Kontrola: gcloud vypíše `Service URL`. Otvor v prehliadači:
- `<URL>/` – úvodná stránka,
- `<URL>/readyz` – má vrátiť `{"status":"ok","database":"ok"}`.

## 12. Aktualizácia DB a testovacie dáta (vývoj)

Po každej novej migrácii zopakuj krok 10. Testovacie dáta sa dajú nahrať **len do prázdnej** databázy
a len mimo produkcie (`ESS_ENVIRONMENT=prod` ich odmietne):

```bash
cd ~/eSpeleoSociety2 && git pull && .venv/bin/pip install -q .
export ESS_DATABASE_URL="$(gcloud secrets versions access latest --secret=ess-database-url)"
.venv/bin/alembic upgrade head
ESS_PII_KEYS="$(gcloud secrets versions access latest --secret=ess-pii-keys)" \
ESS_BLIND_INDEX_KEY="$(gcloud secrets versions access latest --secret=ess-blind-index-key)" \
  .venv/bin/python -m ess.tools.seed_test_data
unset ESS_DATABASE_URL
```

Testovacie dáta sú zašifrované tými istými kľúčmi ako aplikácia, takže ich aplikácia vie prečítať.
Pred ostrou prevádzkou bude treba samostatnú produkčnú databázu (a nové kľúče).

## 13. Prihlásenie administrátorov cez Google

**a) Adresa aplikácie** (v Cloud Shell):

```bash
REGION=europe-west3
URL=$(gcloud run services describe ess --region $REGION --format='value(status.url)'); echo $URL
```

**b) Prihlasovacia obrazovka Google** – v konzole *Google Auth Platform* (menu *APIs & Services* →
*OAuth consent screen*):
1. *Branding*: názov aplikácie `eSpeleoSociety`, e-mail podpory (tvoj).
2. *Audience*: typ **External**, stav nechaj **Testing** a do *Test users* pridaj Google účty oboch
   hlavných systémových administrátorov. Kým je aplikácia v režime Testing, prihlásiť sa môžu len títo
   používatelia – pri vývoji je to vítaná poistka navyše.
3. *Data access*: netreba pridávať nič (aplikácia žiada len `openid`, `email`, `profile`).

**c) OAuth klient** – *Clients* → *Create client*:
- typ **Web application**, názov `eSS`,
- *Authorized redirect URIs*: `<URL>/admin/auth/callback` (URL z kroku a),
- po vytvorení skopíruj **Client ID**; **Client secret** ulož rovno do Secret Manageru:

```bash
read -s -p "Client secret: " CS; echo
printf '%s' "$CS" | gcloud secrets create ess-google-client-secret --data-file=-; unset CS
openssl rand -base64 48 | tr -d '\n' | gcloud secrets create ess-session-secret --data-file=-

PROJECT_NUMBER=$(gcloud projects describe $(gcloud config get-value project) --format='value(projectNumber)')
for s in ess-google-client-secret ess-session-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

**d) Nové nasadenie.** Najprv si ulož hodnoty do premenných – `CLIENT_ID` je **Client ID** (nie secret),
končí na `.apps.googleusercontent.com`; vkladaj ho bez úvodzoviek a bez znakov `< >`. E-maily hlavných
administrátorov oddeľ čiarkou bez medzier:

```bash
CLIENT_ID=123456789012-xxxxxxxx.apps.googleusercontent.com
ADMINS=tvoj@gmail.com,kamarat@gmail.com
```

Potom nasaď (`^;^` hovorí gcloud, že premenné sú oddelené bodkočiarkou):

```bash
cd ~/eSpeleoSociety2 && git pull
gcloud run deploy ess --source . --region $REGION --allow-unauthenticated --max-instances 2 \
  --set-env-vars "^;^ESS_ENVIRONMENT=dev;ESS_PUBLIC_BASE_URL=$URL;ESS_GOOGLE_CLIENT_ID=$CLIENT_ID;ESS_SUPER_ADMIN_EMAILS=$ADMINS" \
  --set-secrets ESS_DATABASE_URL=ess-database-url:latest,ESS_PII_KEYS=ess-pii-keys:latest,ESS_BLIND_INDEX_KEY=ess-blind-index-key:latest,ESS_GOOGLE_CLIENT_SECRET=ess-google-client-secret:latest,ESS_SESSION_SECRET=ess-session-secret:latest
```

Potom otvor `<URL>/admin` a prihlás sa. Ďalších administrátorov bude možné pridať v aplikácii.

**Riešenie problémov:**
- *„The OAuth client was not found“ / `invalid_client`* – zlá hodnota `ESS_GOOGLE_CLIENT_ID` (Google ho
  nepozná). Over: `gcloud run services describe ess --region $REGION --format=yaml | grep -A1 GOOGLE_CLIENT_ID`
  a oprav bez nového zostavenia: `gcloud run services update ess --region $REGION --update-env-vars ESS_GOOGLE_CLIENT_ID=$CLIENT_ID`.
  Nový klient sa niekedy prejaví až o 5–10 minút.
- *„redirect_uri_mismatch“* – adresa v *Authorized redirect URIs* sa musí presne zhodovať s
  `<URL>/admin/auth/callback` (vrátane `https://`, bez lomky na konci).
- *„Prihlásenie cez Google sa nepodarilo“* (po výbere účtu) – zlý Client Secret v `ess-google-client-secret`;
  pridaj novú verziu: `printf '%s' "SECRET" | gcloud secrets versions add ess-google-client-secret --data-file=-`
  a znova nasaď. Client Secret sa **nekóduje** (kódovanie sa týka len hesla k DB v kroku 5).
- *„Tento Google účet nemá prístup“* – e-mail nie je v `ESS_SUPER_ADMIN_EMAILS` alebo nie je v *Test users*.

## Neskôr

- Automatické nasadenie z GitHubu cez GitHub Actions (Workload Identity Federation, bez kľúčov v súboroch).
- Vlastná doména `ess.sss.sk` namapovaná na Cloud Run.
- Overovanie certifikátu DB servera (`sslmode=verify-full`), ak WebSupport poskytne CA certifikát.
  Test používa `sslmode=require`, ktorý spojenie šifruje, ale neoveruje identitu servera.
- Ďalšie tajomstvá: Google Wallet účet, SMTP heslo pre `ess@sss.sk`.

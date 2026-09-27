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

## Neskôr (po úspešnom teste)

- Automatické nasadenie z GitHubu cez GitHub Actions (Workload Identity Federation, bez kľúčov v súboroch).
- Vlastná doména `ess.sss.sk` namapovaná na Cloud Run.
- OAuth klient pre prihlásenie adminov Google účtom.
- Overovanie certifikátu DB servera (`sslmode=verify-full`), ak WebSupport poskytne CA certifikát.
  Test používa `sslmode=require`, ktorý spojenie šifruje, ale neoveruje identitu servera.
- Ďalšie tajomstvá: šifrovací kľúč osobných údajov, HMAC kľúč, podpisový kľúč eCP, Google Wallet účet, SMTP.

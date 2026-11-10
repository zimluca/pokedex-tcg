# Guida alla Pubblicazione su PythonAnywhere

Questa guida ti porta passo-passo dal codice locale alla versione online del Pokédex TCG.

---

## Fase 0 — Cosa è già stato fatto ✅

- [x] Creato `wsgi.py` (entry point WSGI per PythonAnywhere)
- [x] Debug disattivato in produzione (attivo solo con `FLASK_DEBUG=1`)
- [x] Chiave API Pokémon leggibile da variabile d'ambiente `POKEMON_API_KEY`
- [x] `.gitignore` aggiornato (esclude `instance/`, `*.db`, log, pycache)
- [x] Codice committato nel repository git locale

---

## Fase 1 — Creare l'account PythonAnywhere

1. Vai su **[pythonanywhere.com](https://www.pythonanywhere.com)**
2. Clicca **"Start running Python online in less than a minute"**
3. Registrati con email e password (piano **gratuito**)
4. Annota il **nome utente** (sarà il dominio: `tuonome.pythonanywhere.com`)

---

## Fase 2 — Creare il repository su GitHub

1. Vai su **[github.com/new](https://github.com/new)**
2. **Repository name**: `pokedex-tcg` (o un altro nome)
3. Visibilità: **Private** (consigliato) o Public
4. **NON** spuntare "Add a README" / ".gitignore" (evita conflitti con quelli già esistenti)
5. Clicca **Create repository**
6. Copia l'URL del repository (es. `https://github.com/zimluca/pokedex-tcg.git`)

---

## Fase 3 — Caricare il codice su GitHub (dal tuo PC)

Apri il terminale nel progetto (`C:\Users\lucaz\Desktop\aider`) ed esegui:

```bash
git remote add origin https://github.com/TUO-NOME-UTENTE/pokedex-tcg.git
git push -u origin master
```

*(Sostituisci `TUO-NOME-UTENTE` con il tuo nome GitHub, es. `zimluca`)*

> **Nota**: Se il branch del tuo repo è `main` invece di `master`, usare
> `git push -u origin master` e poi impostare `main` come predefinito.

---

## Fase 4 — Configurare il progetto su PythonAnywhere

### 4.1 Clone del repository
1. Nella dashboard PythonAnywhere clicca **"Bash"** (apre una console)
2. Esegui:
   ```bash
   git clone https://github.com/TUO-NOME-UTENTE/pokedex-tcg.git
   cd pokedex-tcg
   ```

### 4.2 Creare il virtualenv e installare le dipendenze
```bash
mkvirtualenv --python=python3.12 pokedex
pip install -r requirements.txt
```

### 4.3 Creare il database
```bash
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('DB creato!')"
```

### 4.4 Caricare la collezione esistente (opzionale ma consigliato)
1. Dal pannello **Files** di PythonAnywhere vai in `pokedex-tcg/`
2. Crea la cartella `instance/`
3. Carica il file `instance/collezione.db` dal tuo PC (`C:\Users\lucaz\Desktop\aider\instance\collezione.db`)
4. Carica anche `instance/sets_cache.json`

---

## Fase 5 — Configurare la Web App

1. Dalla dashboard vai su **"Web"**
2. Clicca **"Add a new web app"**
3. Scegli **Manual configuration** → Python 3.12
4. Nel campo **"Code"** → Source code: `/home/TUONOME/pokedex-tcg`
5. **Virtualenv**: `/home/TUONOME/.virtualenvs/pokedex`
6. **WSGI configuration file**: clicca sul link del file (`/var/www/TUONOME_pythonanywhere_com_wsgi.py`),
   **seleziona TUTTO (Ctrl+A) ed elimina**, poi incolla esattamente questo:

   ```python
   import os
   import sys

   # Il progetto può trovarsi in ~/pokedex-tcg oppure in ~/pokedex-tcg/pokedex-tcg
   # (succede se il clone è stato fatto dentro una cartella già esistente).
   # Cerchiamo la cartella che contiene wsgi.py e la aggiungiamo al sys.path.
   UTENTE = 'TUONOME'
   candidati = [
       '/home/{0}/pokedex-tcg'.format(UTENTE),
       '/home/{0}/pokedex-tcg/pokedex-tcg'.format(UTENTE),
   ]
   project_home = next(
       (percorso for percorso in candidati
        if os.path.exists(os.path.join(percorso, 'wsgi.py'))),
       candidati[0]
   )
   if project_home not in sys.path:
       sys.path.insert(0, project_home)

   from wsgi import application
   ```

   > ⚠️ Le righe non devono essere indentate e `import sys` deve esserci:
   > incollare il codice *dentro* il file di default di PythonAnywhere produce
   > `IndentationError: unexpected indent`.

   Per capire quale layout hai davvero, dalla console Bash:
   ```bash
   ls -la ~/pokedex-tcg | head -20
   ls -la ~/pokedex-tcg/pokedex-tcg 2>/dev/null | head -5
   ```
   Se compare `pokedex-tcg/pokedex-tcg`, il progetto è nella sottocartella e anche il
   database andrà caricato in `~/pokedex-tcg/pokedex-tcg/instance/`.

### 5.1 Variabili d'ambiente
Nella sezione **"Environment variables"** della Web app aggiungi:

| Variabile | Valore |
|---|---|
| `SECRET_KEY` | (genera una chiave casuale lunga, es. con [this](https://randomkeygen.com)) |
| `GOOGLE_CLIENT_ID` | il tuo Client ID Google OAuth |
| `GOOGLE_CLIENT_SECRET` | il tuo Client Secret Google OAuth |
| `OAUTHLIB_INSECURE_TRANSPORT` | `0` |
| `POKEMON_API_KEY` | la chiave API Pokémon |
| `GEMINI_API_KEY` | la chiave API Google Gemini (per lo scanner fotocamera) |
| `GEMINI_MODEL` | modello multimodale per il riconoscimento (default `gemini-3.5-flash`) |

*(Se preferisci, puoi creare un file `.env` nella cartella `pokedex-tcg/` con gli stessi valori — l'app lo legge automaticamente.)*

### 5.2 File statici (CSS e JavaScript del nuovo design)
L'app ha ora una cartella **`static/`** (`css/app.css`, `js/app.js`). Flask li servirebbe già da solo,
ma su PythonAnywhere è **consigliato** mapparli per prestazioni migliori:

Nella pagina **Web** → sezione **Static files** → *Enter URL* / *Enter path* → **Add**:

| URL | Directory |
|---|---|
| `/static/` | `/home/TUONOME/pokedex-tcg/static` |

> Senza questa mappatura il sito funziona comunque (Flask serve `/static/...`), ma con più lentezza.

### 5.3 Avviare la web app
Clicca **"Reload"** in alto nella pagina Web.
Il sito sarà disponibile su: `https://tuonome.pythonanywhere.com`

---

## Fase 6 — Configurare Google OAuth per il dominio di produzione

1. Vai su **[Google Cloud Console](https://console.cloud.google.com/apis/credentials)**
2. Apri il tuo progetto OAuth esistente
3. Nella sezione **"URI di reindirizzamento autorizzati"** aggiungi:
   ```
   https://tuonome.pythonanywhere.com/auth/callback
   ```
4. Nella sezione **"Origini JavaScript autorizzate"** aggiungi:
   ```
   https://tuonome.pythonanywhere.com
   ```
5. Salva

---

## Fase 7 — Verifica finale

1. Apri `https://tuonome.pythonanywhere.com`
2. Verifica che la homepage carichi le espansioni
3. Fai il login con Google (dovrebbe funzionare con il nuovo redirect URI)
4. Apri un'espansione e verifica che le carte si carichino
5. Apri il sito dal **telefono** per verificare la versione mobile

---

## 🔄 Aggiornare il sito in futuro

Quando modifichi il codice in locale e vuoi pubblicare gli aggiornamenti:

```bash
# Sul tuo PC
git add -A
git commit -m "descrizione delle modifiche"
git push

# Su PythonAnywhere (console Bash)
cd ~/pokedex-tcg
git pull
```

---

## 🧯 Risoluzione problemi (errori visti davvero)

| Errore nel log | Causa | Soluzione |
|---|---|---|
| `IndentationError: unexpected indent` nel file WSGI | codice incollato **dentro** il file di default, con indentazione | Ctrl+A → cancella tutto → incolla lo snippet del punto 5.6 (senza indentazione) |
| path `/home/TUONOME/pokedex-tcg/pokedex-tcg` | progetto clonato in una sottocartella | usa lo snippet con auto-detect del punto 5.6 |
| `Invalid username or token` facendo `git pull` | GitHub non accetta più password: repo privato | crea un **Personal Access Token** (Contents: Read-only) e usalo come password, oppure rendi il repo pubblico |
| `ModuleNotFoundError: No module named 'flask'` | virtualenv non collegato | Web → Virtualenv: `/home/TUONOME/.virtualenvs/pokedex` + Reload |
| `Scanner non configurato` | manca la chiave | aggiungi `GEMINI_API_KEY` tra le Environment variables |
| Pagina senza stili | manca la mappatura dei file statici | Web → Static files: `/static/` → `/home/TUONOME/pokedex-tcg/static` |
| `redirect_uri_mismatch` su Google | URI non autorizzato | aggiungi `https://TUONOME.pythonanywhere.com/auth/callback` in Google Console |
| `sqlite3.OperationalError: unable to open database file` | manca `instance/` | `mkdir -p ~/pokedex-tcg/instance` e carica `collezione.db` |

**Test rapido prima del Reload** (dalla console Bash, nella cartella del progetto):
```bash
workon pokedex
python -c "import wsgi; print('WSGI OK')"
```
Se stampa `WSGI OK`, il Reload della web app funzionerà.

Poi clicca **"Reload"** sulla pagina Web di PythonAnywhere.

---

## ⚠️ Note importanti

- **Database**: `instance/` è escluso da git. Se cancelli il progetto su PythonAnywhere, la collezione va salvata prima!
- **Il piano gratuito** non supporta domini personalizzati (solo `tuonome.pythonanywhere.com`) e limita le richieste simultanee
- **Il DB in locale** e quello online sono separati. La versione online diventa quella "vera" da usare
- **HTTPS**: PythonAnywhere fornisce HTTPS automaticamente sul sottodominio gratuito

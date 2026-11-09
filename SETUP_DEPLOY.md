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
6. **WSGI configuration file**: clicca sul link del file e **sostituisci tutto** con:
   ```python
   import sys
   sys.path.insert(0, '/home/TUONOME/pokedex-tcg')
   from wsgi import application
   ```

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

Poi clicca **"Reload"** sulla pagina Web di PythonAnywhere.

---

## ⚠️ Note importanti

- **Database**: `instance/` è escluso da git. Se cancelli il progetto su PythonAnywhere, la collezione va salvata prima!
- **Il piano gratuito** non supporta domini personalizzati (solo `tuonome.pythonanywhere.com`) e limita le richieste simultanee
- **Il DB in locale** e quello online sono separati. La versione online diventa quella "vera" da usare
- **HTTPS**: PythonAnywhere fornisce HTTPS automaticamente sul sottodominio gratuito

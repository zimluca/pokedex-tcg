# Setup Google OAuth 2.0

## 1. Crea un progetto Google Cloud

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuovo progetto o selezionane uno esistente
3. Abilita l'API "Google+ API" (necessaria per OAuth)

## 2. Configura OAuth 2.0

1. Vai su **API e servizi** → **Credenziali**
2. Clicca su **Crea credenziali** → **ID client OAuth 2.0**
3. Seleziona **Applicazione web**
4. Configura:
   - **Nome**: Pokédex TCG
   - **Origini JavaScript autorizzate**: 
     - `http://localhost:5000` (per sviluppo)
     - `http://127.0.0.1:5000` (alternativa)
   - **URI di reindirizzamento autorizzati**:
     - `http://localhost:5000/auth/callback` (per sviluppo)
     - `http://127.0.0.1:5000/auth/callback` (alternativa)
5. Salva e copia **Client ID** e **Client Secret**

**IMPORTANTE**: L'URI di reindirizzamento deve corrispondere ESATTAMENTE a quello configurato qui. Se usi `localhost`, configura `localhost`. Se usi `127.0.0.1`, configura `127.0.0.1`. Aggiungi entrambi per sicurezza.

## 3. Configura le variabili d'ambiente

Crea un file `.env` nella root del progetto:

```env
SECRET_KEY=genera-una-chiave-segreta-casuale
GOOGLE_CLIENT_ID=il-tuo-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=il-tuo-client-secret
OAUTHLIB_INSECURE_TRANSPORT=1
```

**IMPORTANTE**: Non committare mai il file `.env` su Git!

## 4. Installa le dipendenze

```bash
py -3.12 -m pip install flask-login oauthlib pyopenssl requests
```

## 5. Inizializza il database

```bash
py -3.12 -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database creato!')"
```

## 6. Avvia l'applicazione

```bash
py -3.12 app.py
```

## 7. Testa il login

1. Apri `http://localhost:5000`
2. Clicca su "Accedi con Google"
3. Autorizza l'applicazione
4. Dovresti essere reindirizzato alla home page autenticato

## Note per la produzione

- Cambia `SECRET_KEY` con una chiave casuale sicura
- Rimuovi `OAUTHLIB_INSECURE_TRANSPORT=1`
- Usa HTTPS
- Aggiorna gli URI di reindirizzamento in Google Console con il dominio di produzione

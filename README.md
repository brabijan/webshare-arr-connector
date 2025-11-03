# Webshare Downloader

Automatický vyhledávač a downloader pro Sonarr/Radarr integrovaný s Webshare.cz a pyLoad.

## Funkce

### Automatický workflow (Webhook)
1. Sonarr/Radarr pošle webhook o nové epizodě/filmu
2. Aplikace vyhledá na Webshare.cz (kombinace strategií)
3. Parsuje názvy pomocí GuessIt (kvalita, jazyk, codec)
4. Vyhodnotí ranking s **prioritou českého jazyka**
5. Uloží top 5 výsledků jako "pending"
6. Uživatel potvrdí výběr přes web UI nebo API
7. Stáhne direct link a pošle do pyLoad
8. Zaloguje do historie

### Inteligentní ranking
- **Český jazyk má absolutní prioritu** (+50 bodů)
- Z českých verzí vybere nejlepší kvalitu
- Pokud není CZ, nabídne nejlepší dostupné
- Respektuje source kvalitu (BluRay > WEB-DL > HDTV)
- Filtruje podle minimální kvality a max. velikosti

### Manuální workflow
- Vyhledávání přes API endpoint
- Zobrazení výsledků v web UI
- Okamžitý výběr a stažení

## Architektura

```
webshare_downloader/
├── app.py                      # Flask aplikace
├── config.py                   # Konfigurace
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── models/
│   └── database.py            # SQLite modely (cache, history, pending)
├── services/
│   ├── webshare.py            # Webshare API client
│   ├── sonarr.py              # Sonarr API client
│   ├── radarr.py              # Radarr API client
│   ├── pyload.py              # pyLoad integration
│   ├── parser.py              # GuessIt wrapper + ranking
│   └── search.py              # Vyhledávací orchestrace
├── routes/
│   ├── webhooks.py            # Webhook endpointy
│   ├── api.py                 # REST API
│   └── web.py                 # Web UI
└── templates/
    ├── base.html
    ├── index.html             # Pending downloads
    └── history.html           # Download history
```

## API Endpointy

### Webhooks
- `POST /webhook/sonarr` - Příjem Sonarr webhooků (Grab, Download)
- `POST /webhook/radarr` - Příjem Radarr webhooků (Grab, Download)

### REST API
- `GET /api/pending` - Seznam čekajících potvrzení
- `GET /api/pending/<id>` - Detail čekajícího potvrzení
- `POST /api/confirm` - Potvrdit a stáhnout vybraný soubor
- `POST /api/search` - Manuální vyhledávání
- `GET /api/history` - Historie stažení
- `GET /api/stats` - Statistiky

### Web UI
- `GET /` - Pending downloads
- `POST /download` - Potvrdit stažení
- `GET /history` - Historie
- `GET /health` - Health check

## Instalace

### 1. Klonování
```bash
git clone <repo>
cd webshare_downloader
```

### 2. Konfigurace
```bash
cp .env.example .env
# Uprav .env s tvými credentials
```

### 3. Docker Compose
```bash
docker compose up -d
```

Aplikace bude dostupná na: `http://localhost:5000`

### 4. Manuální instalace (development)
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# nebo
venv\Scripts\activate  # Windows

pip install -r requirements.txt

# Nastav environment proměnné
export WEBSHARE_USER=your_username
export WEBSHARE_PASS=your_password
# ... další proměnné

python app.py
```

## Konfigurace Sonarr/Radarr

### Sonarr

1. Settings → Connect → Add Webhook
2. **Name**: Webshare Downloader
3. **Trigger**: On Grab, On Download
4. **URL**: `http://webshare-downloader:5000/webhook/sonarr`
5. **Method**: POST

### Radarr

1. Settings → Connect → Add Webhook
2. **Name**: Webshare Downloader
3. **Trigger**: On Grab, On Download
4. **URL**: `http://webshare-downloader:5000/webhook/radarr`
5. **Method**: POST

## Environment proměnné

### Webshare
- `WEBSHARE_USER` - Uživatelské jméno
- `WEBSHARE_PASS` - Heslo

### pyLoad
- `PYLOAD_URL` - URL pyLoad serveru (default: `http://pyload.homelab.carpiftw.cz`)
- `PYLOAD_USER` - Uživatel (default: `admin`)
- `PYLOAD_PASS` - Heslo (default: `admin`)

### Sonarr
- `SONARR_URL` - URL Sonarr serveru (default: `http://sonarr:8989`)
- `SONARR_API_KEY` - API klíč

### Radarr
- `RADARR_URL` - URL Radarr serveru (default: `http://radarr:7878`)
- `RADARR_API_KEY` - API klíč

### Search preferences
- `PREFER_CZECH` - Preferovat český jazyk (default: `true`)
- `MIN_QUALITY` - Minimální kvalita (default: `720p`)
- `MAX_SIZE_GB` - Max. velikost souboru v GB (default: `50`)
- `SEARCH_LIMIT` - Max. počet výsledků z Webshare (default: `50`)

### Cache
- `CACHE_TTL_DAYS` - TTL cache ve dnech (default: `7`)
- `HISTORY_TTL_DAYS` - TTL historie ve dnech (default: `30`)

## Flask CLI příkazy

```bash
# Cleanup expired cache a old history
flask cleanup

# Vyhledat missing položky v Sonarr/Radarr
flask search-missing
```

## Použití API

### Získat pending položky
```bash
curl http://localhost:5000/api/pending
```

### Potvrdit download
```bash
curl -X POST http://localhost:5000/api/confirm \
  -H "Content-Type: application/json" \
  -d '{"pending_id": 1, "result_index": 0}'
```

### Manuální vyhledávání
```bash
curl -X POST http://localhost:5000/api/search \
  -H "Content-Type: application/json" \
  -d '{"source": "radarr", "query": "Movie Title 2024"}'
```

## Databáze

Aplikace používá SQLite (`data/downloader.db`) s třemi tabulkami:

1. **search_cache** - Cache vyhledávacích výsledků (TTL 7 dní)
2. **pending_confirmations** - Položky čekající na potvrzení
3. **download_history** - Historie stažených souborů

## Technologie

- **Flask 3.0** - Web framework
- **GuessIt 3.8** - Parsing release názvů (kvalita, jazyk, codec)
- **SQLAlchemy 2.0** - ORM pro SQLite
- **Requests 2.31** - HTTP client
- **Gunicorn 21.2** - Production WSGI server

## Ranking algoritmus

```python
Score = Quality + Source + Codec + Language Bonus + Votes - Penalties

Quality scores:  2160p=40, 1080p=30, 720p=20, 480p=10
Source scores:   BluRay=25, WEB-DL=20, HDTV=10
Codec scores:    HEVC=10, H.264=8
Czech bonus:     +50 (highest priority!)
Votes bonus:     +1-10 (from Webshare ratings)

Penalties:
- Below MIN_QUALITY: -50
- Oversized (>MAX_SIZE_GB): -100
```

## Health Check

```bash
curl http://localhost:5000/health
# {"status": "ok"}
```

## Troubleshooting

### Aplikace neodpovídá
```bash
docker logs webshare-downloader
docker restart webshare-downloader
```

### Webhooks nefungují
1. Zkontroluj URL v Sonarr/Radarr settings
2. Zkontroluj network (musí být ve stejné síti)
3. Zkontroluj logy: `docker logs webshare-downloader`

### Nenachází české soubory
1. Zkontroluj `PREFER_CZECH=true` v .env
2. Webshare nemusí mít české verze
3. Zkontroluj logy - co GuessIt detekoval

### Databáze je příliš velká
```bash
# Spusť cleanup
docker exec webshare-downloader flask cleanup

# Nebo zkrať TTL
CACHE_TTL_DAYS=3
HISTORY_TTL_DAYS=14
```

## Vývoj

### Spuštění dev serveru
```bash
DEBUG=true python app.py
```

### Struktura logu
```
logs/
└── app.log  (rotuje se po 10MB, max 5 backups)
```

## Budoucí vylepšení

- [ ] Automatické potvrzování (bez manuální interakce)
- [ ] Discord/Telegram notifikace
- [ ] Retry logika když není nalezen soubor
- [ ] Dashboard s grafy a statistikami
- [ ] Multi-language support v UI
- [ ] Import existujících položek z pyLoad

## Autor

Vytvořeno pomocí Claude Code

## License

MIT

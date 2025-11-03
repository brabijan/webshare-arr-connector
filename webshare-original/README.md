# Webshare to pyLoad

Webová aplikace pro automatický převod Webshare.cz odkazů na direct linky a jejich odeslání do pyLoad.

## Funkce

### Webový formulář
- Zadání více URL (každý na řádek)
- Automatický převod na direct linky
- **Všechny linky se přidají do jednoho package v pyLoad**
- Odeslání do pyLoad download manageru

### API Endpoint
- REST API pro programatický přístup
- POST `/api/convert` s JSON payload
- Jeden URL = jeden package (pro více URL použij webový formulář)

## Použití

### Webové rozhraní
Otevři v prohlížeči: `https://webshare.homelab.carpiftw.cz`

1. Vlož Webshare URL do textového pole (každý odkaz na nový řádek)
2. Klikni na "Převést a odeslat do pyLoad"
3. Zobrazí se výsledky pro každý odkaz

### API

```bash
curl -X POST https://webshare.homelab.carpiftw.cz/api/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://webshare.cz/file/abc123/"}'
```

Odpověď:
```json
{
  "success": true,
  "url": "https://webshare.cz/file/abc123/",
  "direct_link": "https://...",
  "message": "Successfully added to pyLoad"
}
```

## Konfigurace

Environment proměnné v `docker-compose.yml`:

- `WEBSHARE_USER` - Webshare uživatelské jméno (výchozí: mates91)
- `WEBSHARE_PASS` - Webshare heslo
- `PYLOAD_URL` - URL pyLoad serveru (výchozí: https://pyload.homelab.carpiftw.cz)
- `PYLOAD_USER` - pyLoad uživatelské jméno
- `PYLOAD_PASS` - pyLoad heslo

## Podporované formáty URL

Aplikace podporuje oba formáty Webshare URL:

1. **Klasický formát**: `https://webshare.cz/file/ABC123/`
2. **SPA formát (s #)**: `https://webshare.cz/#/file/ABC123/filename.mkv`

## Nasazení

### Lokální vývoj

```bash
# Build
docker build -t webshare-app:test .

# Run
docker run -p 8888:5000 \
  -e WEBSHARE_USER=... \
  -e WEBSHARE_PASS=... \
  -e PYLOAD_URL=http://pyload.homelab.carpiftw.cz \
  -e PYLOAD_USER=... \
  -e PYLOAD_PASS=... \
  webshare-app:test
```

### Produkce (server)

```bash
cd /root/webshare-app
docker compose up -d
```

Aplikace bude dostupná na: `https://webshare.homelab.carpiftw.cz`

## Technologie

- **Backend**: Flask 3.0 + Gunicorn
- **Kontejnerizace**: Docker + Docker Compose
- **Reverse Proxy**: Traefik s Let's Encrypt SSL
- **DNS**: Pi-hole local DNS
- **API**: Webshare.cz API + pyLoad API

## Struktura projektu

```
webshare-app/
├── app.py                  # Flask aplikace
├── requirements.txt        # Python závislosti
├── Dockerfile             # Docker image definice
├── docker-compose.yml     # Produkční konfigurace
├── templates/
│   └── index.html        # Webový formulář
└── README.md             # Tato dokumentace
```

## Health Check

```bash
curl https://webshare.homelab.carpiftw.cz/health
# {"status":"ok"}
```

## Řešení problémů

### Aplikace neodpovídá
```bash
docker logs webshare-app
docker restart webshare-app
```

### SSL certifikát nefunguje
```bash
docker logs traefik | grep -i certificate
```

### DNS nefunguje
```bash
docker exec pihole cat /etc/pihole/custom.list
docker exec pihole pihole reloaddns
```

## Autor

Vytvořeno pomocí Claude Code

# Popis původní aplikace Webshare to pyLoad

## Účel
Webová aplikace pro automatický převod Webshare.cz odkazů na direct download linky a jejich odeslání do pyLoad download manageru.

## Hlavní funkce

### 1. Webové rozhraní (/)
- Formulář pro zadání jednoho nebo více Webshare.cz URL (každý na řádek)
- Převede všechny URL na direct download linky
- **Všechny linky přidá do JEDNOHO package v pyLoad**
- Zobrazí výsledky pro každý odkaz (úspěch/chyba)

### 2. REST API (/api/convert)
- POST endpoint pro programatický přístup
- Přijímá JSON: `{"url": "https://webshare.cz/file/abc123/"}`
- Jeden URL = jeden package v pyLoad
- Vrací JSON s výsledkem a direct linkem

### 3. Health check (/health)
- Jednoduchý endpoint pro kontrolu stavu aplikace
- Vrací: `{"status": "ok"}`

## Podporované formáty URL

Aplikace parsuje oba formáty Webshare URL:
1. **Klasický**: `https://webshare.cz/file/ABC123/`
2. **SPA formát (s #)**: `https://webshare.cz/#/file/ABC123/filename.mkv`

Extrahuje file identifier (ident) z URL path nebo fragment.

## Jak to funguje

### Krok 1: Převod na direct link (`get_webshare_direct_link()`)
1. Parsuje URL a extrahuje file identifier (ident)
2. Volá Webshare API: `https://webshare.cz/api/file_link/`
3. Posílá POST s `{ident: ..., wst: ''}` + HTTP Basic Auth
4. Webshare vrací XML s direct download linkem
5. Parsuje XML a vrací link

### Krok 2: Přidání do pyLoad (`add_to_pyload()`)
1. Přijímá buď jeden link (string) nebo list linků
2. Volá pyLoad API: `{PYLOAD_URL}/api/addPackage`
3. Posílá JSON: `{name: "Webshare Download", links: [...]}`
4. Používá HTTP Basic Auth pro pyLoad
5. Vrací package ID

## Konfigurace (Environment proměnné)

```
WEBSHARE_USER - Webshare uživatelské jméno (default: mates91)
WEBSHARE_PASS - Webshare heslo (default: afdm54F3)
PYLOAD_URL    - URL pyLoad serveru (default: http://pyload.homelab.carpiftw.cz)
PYLOAD_USER   - pyLoad uživatel (default: admin)
PYLOAD_PASS   - pyLoad heslo (default: admin)
```

## Technologie

- **Framework**: Flask 3.0
- **HTTP requesty**: requests 2.31.0
- **Production server**: Gunicorn 21.2.0
- **XML parsing**: xml.etree.ElementTree (builtin)
- **Deployment**: Docker + Docker Compose + Traefik reverse proxy

## Architektura kódu

```
app.py (220 řádků):
  - Flask routes (/, /convert, /api/convert, /health)
  - get_webshare_direct_link() - parsování URL a volání Webshare API
  - add_to_pyload() - volání pyLoad API
  - Error handling pro všechny případy

templates/index.html - HTML formulář + zobrazení výsledků
static/ - CSS/JS (pokud nějaké)
```

## Klíčové vlastnosti

1. **Batch processing**: Webový formulář umí zpracovat více URL najednou a přidat je všechny do jednoho package
2. **Dual URL format support**: Zvládá klasické i SPA (#) URL formáty
3. **Dvě rozhraní**: Web UI pro lidi + REST API pro automatizaci
4. **XML response handling**: Webshare API vrací XML, ne JSON
5. **Error handling**: Detailní error messages pro debugging
6. **HTTP Basic Auth**: Pro komunikaci s Webshare i pyLoad

## Použití na serveru

Běží na: `https://webshare.homelab.carpiftw.cz`
- Traefik reverse proxy s Let's Encrypt SSL
- Pi-hole local DNS
- Docker Compose deployment

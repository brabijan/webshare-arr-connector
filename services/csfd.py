"""ČSFD scraper pro dohledání českého názvu pořadu/filmu.

ČSFD je chráněné anti-bot výzvou Anubis (proof-of-work). Tento modul výzvu
vyřeší v Pythonu (SHA-256 PoW, difficulty bývá 2 = pár stovek iterací),
získá ověřovací cookie a tu dál používá ve sdílené session.

Modul je navržen tak, aby NIKDY nevyhodil výjimku do vyhledávacího toku –
při jakékoliv chybě vrací prázdný výsledek a vyhledávání pokračuje
s původním (anglickým) názvem.
"""
import hashlib
import json
import logging
import re
import threading
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.csfd.cz"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 12

_session = None
_session_lock = threading.Lock()


def _get_session():
    """Vrátí sdílenou session (cookie z Anubis výzvy přežije mezi dotazy)."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "cs,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
    return _session


def _is_anubis_challenge(html):
    return 'id="anubis_challenge"' in html


def _solve_anubis(session, html, page_url):
    """Vyřeší Anubis proof-of-work výzvu a získá ověřovací cookie.

    Algoritmus (Anubis 'fast'): hledá se nonce takové, že
    SHA-256(randomData + nonce) má `difficulty` vedoucích nulových
    půlbajtů (difficulty=2 => hex digest začíná na "00").
    """
    m = re.search(
        r'<script id="anubis_challenge"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        logger.warning("ČSFD: Anubis výzva nenalezena v HTML")
        return False

    try:
        data = json.loads(m.group(1))
        challenge = data["challenge"]
        rules = data["rules"]
        random_data = challenge["randomData"]
        difficulty = int(rules["difficulty"])
        challenge_id = challenge["id"]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"ČSFD: nelze rozparsovat Anubis výzvu: {e}")
        return False

    full_bytes = difficulty // 2
    half_byte = difficulty % 2 != 0

    start = time.time()
    nonce = 0
    max_iterations = 5_000_000  # difficulty 2 ~ stovky, pojistka proti smyčce
    hash_hex = None
    while nonce < max_iterations:
        digest = hashlib.sha256(f"{random_data}{nonce}".encode()).digest()
        ok = True
        for i in range(full_bytes):
            if digest[i] != 0:
                ok = False
                break
        if ok and half_byte and (digest[full_bytes] >> 4) != 0:
            ok = False
        if ok:
            hash_hex = digest.hex()
            break
        nonce += 1

    if hash_hex is None:
        logger.warning(
            f"ČSFD: Anubis PoW se nevyřešilo do {max_iterations} iterací"
        )
        return False

    elapsed_ms = max(int((time.time() - start) * 1000), 50)
    logger.info(
        f"ČSFD: Anubis vyřešen (difficulty={difficulty}, nonce={nonce}, "
        f"{elapsed_ms}ms)"
    )

    try:
        resp = session.get(
            f"{BASE_URL}/.within.website/x/cmd/anubis/api/pass-challenge",
            params={
                "id": challenge_id,
                "response": hash_hex,
                "nonce": nonce,
                "redir": page_url,
                "elapsedTime": elapsed_ms,
            },
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning(f"ČSFD: pass-challenge selhal: {e}")
        return False

    if "techaro.lol-anubis-auth" not in session.cookies.get_dict():
        logger.warning(
            f"ČSFD: po pass-challenge chybí auth cookie (status "
            f"{resp.status_code})"
        )
        return False

    return True


def _fetch(url):
    """Stáhne URL; pokud narazí na Anubis výzvu, vyřeší ji a zkusí znovu."""
    session = _get_session()
    with _session_lock:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            logger.warning(f"ČSFD: dotaz selhal ({url}): {e}")
            return None

        if _is_anubis_challenge(resp.text):
            logger.info("ČSFD: detekována Anubis výzva, řeším…")
            if not _solve_anubis(session, resp.text, url):
                return None
            try:
                resp = session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                logger.warning(f"ČSFD: dotaz po vyřešení výzvy selhal: {e}")
                return None
            if _is_anubis_challenge(resp.text):
                logger.warning("ČSFD: výzva přetrvává i po vyřešení")
                return None

    return resp.text


def _parse_year(info_text):
    m = re.search(r"(\d{4})", info_text or "")
    return int(m.group(1)) if m else None


def _parse_articles(soup, container_class, kind_hint):
    """Vyparsuje výsledky z jednoho bloku (filmy / seriály)."""
    box = soup.select_one(f"div.box.{container_class}")
    if not box:
        return []

    results = []
    for article in box.select("article"):
        link = article.select_one("a.film-title-name")
        if not link:
            continue

        czech_title = link.get_text(strip=True)
        href = link.get("href", "")
        csfd_id = None
        mid = re.search(r"/film/(\d+)", href)
        if mid:
            csfd_id = int(mid.group(1))

        # p.search-name = původní / alternativní název, podle kterého se shoda našla
        original_title = None
        sn = article.select_one("p.search-name")
        if sn:
            original_title = sn.get_text(strip=True).strip("()").strip() or None

        infos = article.select(".film-title-info .info")
        year = _parse_year(infos[0].get_text()) if infos else None
        kind = (
            infos[1].get_text(strip=True).strip("()")
            if len(infos) > 1
            else kind_hint
        )

        if not czech_title:
            continue

        results.append({
            "czech_title": czech_title,
            "original_title": original_title,
            "year": year,
            "kind": kind,
            "url": f"{BASE_URL}{href}" if href else None,
            "csfd_id": csfd_id,
        })

    return results


def search(query, limit=8):
    """Vyhledá na ČSFD a vrátí kandidáty (seriály i filmy).

    Args:
        query (str): hledaný text (typicky anglický/originální název)
        limit (int): max. počet vrácených kandidátů

    Returns:
        list[dict]: každý dict má klíče czech_title, original_title, year,
            kind, url, csfd_id. Seriály jsou uvedené před filmy.
            Při chybě vrací [].
    """
    if not query or not query.strip():
        return []

    url = f"{BASE_URL}/hledat/?q={requests.utils.quote(query.strip())}"
    try:
        html = _fetch(url)
    except Exception as e:  # pojistka – nikdy nepadat do vyhledávání
        logger.warning(f"ČSFD: neočekávaná chyba při hledání '{query}': {e}")
        return []

    if not html:
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
        series = _parse_articles(soup, "main-series", "seriál")
        movies = _parse_articles(soup, "main-movies", "film")
    except Exception as e:
        logger.warning(f"ČSFD: chyba při parsování výsledků: {e}")
        return []

    combined = series + movies
    logger.info(
        f"ČSFD: pro '{query}' nalezeno {len(series)} seriálů, "
        f"{len(movies)} filmů"
    )
    return combined[:limit]


def _normalize(text):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _title_overlap(a, b):
    """Hrubá míra shody dvou názvů (0–1) podle společných slov."""
    sa = set(_normalize(a).split())
    sb = set(_normalize(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_czech_title(query, year=None, want_series=False):
    """Najde nejlepší český název pro daný (anglický) název.

    Vybírá kandidáta, jehož typ odpovídá (seriál vs. film), originální
    název nejlépe odpovídá dotazu a rok je nejblíž.

    Returns:
        dict | None: nejlepší kandidát (viz search()) nebo None.
    """
    candidates = search(query)
    if not candidates:
        return None

    def is_series(c):
        return "seriál" in (c.get("kind") or "").lower()

    # Preferuj odpovídající typ, ale neměj prázdný výsledek
    typed = [c for c in candidates if is_series(c) == want_series]
    pool = typed or candidates

    def score(c):
        s = 0.0
        # shoda originálního názvu s dotazem (hlavní kritérium)
        orig = c.get("original_title") or c.get("czech_title")
        s += _title_overlap(query, orig) * 100
        # shoda roku
        if year and c.get("year"):
            diff = abs(int(year) - int(c["year"]))
            if diff == 0:
                s += 25
            elif diff <= 1:
                s += 15
            elif diff <= 3:
                s += 5
        # mírná preference odpovídajícího typu i v rámci poolu
        if is_series(c) == want_series:
            s += 10
        return s

    best = max(pool, key=score)
    logger.info(
        f"ČSFD: '{query}' → '{best['czech_title']}' "
        f"(orig='{best.get('original_title')}', rok={best.get('year')}, "
        f"typ={best.get('kind')})"
    )
    return best

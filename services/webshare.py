"""Webshare API client.

Webshare API NEPOUŽÍVÁ HTTP Basic Auth. Pro získání direct linku u souborů,
které vyžadují (prémiový) účet, je potřeba se přihlásit a získat token
(``wst``):

  1. ``/salt/``  – vrátí salt pro uživatele (může být prázdný)
  2. heslo = sha1( md5crypt(heslo, salt) )
  3. ``/login/`` – vrátí token (wst)
  4. ``/file_link/`` s ``wst`` – vrátí direct link

Některé soubory vrací status ``FATAL`` i s platným tokenem – ty jsou na
straně Webshare mrtvé (smazané/poškozené) a žádný klient pro ně odkaz
nezíská. Proto je tu fallback, který zkusí další výsledky a vrátí první
funkční (viz ``get_direct_link_with_fallback``).
"""
import hashlib
import logging
import threading
import xml.etree.ElementTree as ET

import requests
import config

logger = logging.getLogger(__name__)

# itoa64 abeceda pro md5crypt ($1$)
_ITOA64 = './0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'


def _md5_crypt(password, salt, magic='$1$'):
    """Pure-python md5crypt ($1$) – deterministický, zvládá i prázdný salt.

    Ekvivalent PHP ``crypt($password, '$1$'.$salt.'$')`` (stdlib modul
    ``crypt`` byl v Pythonu 3.13 odstraněn, proto vlastní implementace).
    """
    pw = password.encode('utf-8')
    sl = salt.encode('utf-8')

    ctx = hashlib.md5(pw + magic.encode() + sl)
    alt = hashlib.md5(pw + sl + pw).digest()

    i = len(pw)
    while i > 0:
        ctx.update(alt[:min(16, i)])
        i -= 16

    i = len(pw)
    while i > 0:
        ctx.update(b'\x00' if (i & 1) else pw[:1])
        i >>= 1

    final = ctx.digest()
    for i in range(1000):
        c = hashlib.md5()
        c.update(pw if (i & 1) else final)
        if i % 3:
            c.update(sl)
        if i % 7:
            c.update(pw)
        c.update(final if (i & 1) else pw)
        final = c.digest()

    out = ''
    for a, b, cc in ((0, 6, 12), (1, 7, 13), (2, 8, 14), (3, 9, 15), (4, 10, 5)):
        v = (final[a] << 16) | (final[b] << 8) | final[cc]
        for _ in range(4):
            out += _ITOA64[v & 0x3f]
            v >>= 6
    v = final[11]
    for _ in range(2):
        out += _ITOA64[v & 0x3f]
        v >>= 6

    return magic + salt + '$' + out


class WebshareClient:
    """Client for Webshare.cz API"""

    def __init__(self):
        self.api_url = config.WEBSHARE_API_URL
        self.username = config.WEBSHARE_USER
        self.password = config.WEBSHARE_PASS
        self.token = None
        self._login_lock = threading.Lock()
        self._headers = {
            'User-Agent': 'webshare-arr-connector/1.0',
            'Accept': 'text/xml; charset=UTF-8',
        }

    # ---- nízkoúrovňové volání ----------------------------------------

    def _post(self, endpoint, payload, timeout=15):
        """POST na Webshare API endpoint, vrací (ElementTree root | None, raw)."""
        url = f"{self.api_url}/{endpoint}/"
        try:
            resp = requests.post(
                url, data=payload, headers=self._headers, timeout=timeout
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Webshare {endpoint} request failed: {e}")
            return None, ''

        if resp.status_code != 200:
            logger.error(
                f"Webshare {endpoint} HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return None, resp.text

        try:
            return ET.fromstring(resp.text), resp.text
        except ET.ParseError as e:
            logger.error(f"Webshare {endpoint} XML parse error: {e} - {resp.text[:200]}")
            return None, resp.text

    @staticmethod
    def _status(root):
        s = root.find('status') if root is not None else None
        return s.text if s is not None else 'UNKNOWN'

    # ---- přihlášení --------------------------------------------------

    def login(self, force=False):
        """Přihlásí se a uloží token (wst). Vrací True/False."""
        with self._login_lock:
            if self.token and not force:
                return True

            root, _ = self._post('salt', {'username_or_email': self.username})
            if root is None or self._status(root) != 'OK':
                logger.error(
                    f"Webshare salt selhal (status "
                    f"{self._status(root) if root is not None else 'n/a'})"
                )
                return False

            salt = root.findtext('salt') or ''
            encrypted = hashlib.sha1(
                _md5_crypt(self.password, salt).encode()
            ).hexdigest()
            digest = hashlib.md5(
                f"{self.username}:Webshare:{self.password}".encode()
            ).hexdigest()

            root, raw = self._post('login', {
                'username_or_email': self.username,
                'password': encrypted,
                'digest': digest,
                'keep_logged_in': 1,
            })
            if root is None or self._status(root) != 'OK':
                logger.error(f"Webshare login selhal: {raw[:200]}")
                self.token = None
                return False

            self.token = root.findtext('token')
            if not self.token:
                logger.error("Webshare login OK, ale chybí token")
                return False

            logger.info("Webshare: přihlášení úspěšné, token získán")
            return True

    def _ensure_token(self):
        if not self.token:
            self.login()
        return self.token

    # ---- vyhledávání -------------------------------------------------

    def search(self, query, category='video', limit=None, sort='rating'):
        """
        Search for files on Webshare

        Args:
            query (str): Search query
            category (str): Category filter (video, audio, images, docs, archives)
            limit (int): Maximum number of results
            sort (str): Sort order (recent, rating, largest, smallest)

        Returns:
            list: List of file dictionaries
        """
        if limit is None:
            limit = config.SEARCH_LIMIT

        payload = {
            'what': query,
            'category': category,
            'sort': sort,
            'limit': limit,
            'wst': self._ensure_token() or '',
        }

        logger.info(f"Searching Webshare for: {query} (limit={limit})")
        root, raw = self._post('search', payload)
        if root is None:
            return []

        files = []
        for file_elem in root.findall('file'):
            try:
                files.append({
                    'ident': file_elem.find('ident').text,
                    'name': file_elem.find('name').text,
                    'size': int(file_elem.find('size').text) if file_elem.find('size') is not None else 0,
                    'type': file_elem.find('type').text if file_elem.find('type') is not None else '',
                    'positive_votes': int(file_elem.find('positive_votes').text) if file_elem.find('positive_votes') is not None else 0,
                    'negative_votes': int(file_elem.find('negative_votes').text) if file_elem.find('negative_votes') is not None else 0,
                    'password': file_elem.find('password').text == 'true' if file_elem.find('password') is not None else False
                })
            except Exception as e:
                logger.warning(f"Error parsing file element: {e}")
                continue

        logger.info(f"Found {len(files)} results for query: {query}")
        return files

    def get_file_info(self, ident):
        """
        Get detailed information about a file

        Args:
            ident (str): File identifier

        Returns:
            dict: File information or None
        """
        root, _ = self._post('file_info', {
            'ident': ident,
            'wst': self._ensure_token() or '',
        }, timeout=10)
        if root is None:
            return None

        return {
            'name': root.find('name').text if root.find('name') is not None else '',
            'description': root.find('description').text if root.find('description') is not None else '',
            'size': int(root.find('size').text) if root.find('size') is not None else 0,
            'type': root.find('type').text if root.find('type') is not None else '',
            'available': root.find('available').text == 'true' if root.find('available') is not None else False,
            'positive_votes': int(root.find('positive_votes').text) if root.find('positive_votes') is not None else 0,
            'negative_votes': int(root.find('negative_votes').text) if root.find('negative_votes') is not None else 0
        }

    # ---- direct link -------------------------------------------------

    @staticmethod
    def _extract_ident(url_or_ident):
        """Z URL nebo identu vytáhne ident. Vrací (ident, error)."""
        if 'webshare.cz' in url_or_ident:
            from urllib.parse import urlparse
            parsed = urlparse(url_or_ident)
            if 'webshare.cz' not in parsed.netloc:
                return None, "Invalid Webshare URL - must be webshare.cz domain"
            path_to_parse = parsed.fragment if parsed.fragment else parsed.path
            path_parts = [p for p in path_to_parse.split('/') if p]
            try:
                file_index = path_parts.index('file')
                ident = path_parts[file_index + 1] if len(path_parts) > file_index + 1 else None
            except (ValueError, IndexError):
                ident = None
            if not ident:
                return None, f"Cannot extract file identifier from URL: {url_or_ident}"
            return ident, None
        return url_or_ident, None

    def get_direct_link(self, url_or_ident, _retried=False):
        """
        Convert Webshare URL or ident to direct download link.

        Používá přihlašovací token (wst). Pokud Webshare vrátí stav
        naznačující neplatný token, jednou se znovu přihlásí a zkusí to
        znovu. ``FATAL`` i s platným tokenem = soubor je na Webshare mrtvý.

        Returns:
            tuple: (direct_link, error_message)
        """
        ident, err = self._extract_ident(url_or_ident)
        if err:
            return None, err

        token = self._ensure_token() or ''
        root, raw = self._post('file_link', {
            'ident': ident,
            'wst': token,
            'force_https': 1,
        }, timeout=10)

        if root is None:
            return None, f"API error / parse error: {raw[:200]}"

        link = root.find('link')
        if link is not None and link.text:
            logger.info(f"Got direct link for ident: {ident}")
            return link.text, None

        status = self._status(root)
        message = root.findtext('message') or ''

        # Možná vypršel/neplatný token → jednou se přihlas a zkus znovu
        if not _retried and status in ('FATAL', 'AUTH', 'ERROR', 'LOGIN'):
            logger.info(
                f"file_link status={status} pro {ident} – zkouším re-login"
            )
            if self.login(force=True):
                return self.get_direct_link(ident, _retried=True)

        return None, f"No link in response. Status: {status}" + (
            f" ({message})" if message else ""
        )

    def is_available(self, ident):
        """Rychlé ověření, že soubor má funkční odkaz (není FATAL/mrtvý)."""
        link, _ = self.get_direct_link(ident)
        return link is not None

    def filter_available(self, results, want=None, max_checks=None,
                         max_workers=6):
        """Vrátí jen soubory s funkčním odkazem (mrtvé/FATAL vyhodí).

        Ověřuje paralelně a v omezeném počtu – projde výsledky v pořadí
        a skončí, jakmile má ``want`` funkčních, případně po ``max_checks``
        ověřeních (aby skenování celé série nedělalo stovky volání).

        Args:
            results (list): výsledky seřazené podle skóre (nejlepší první)
            want (int|None): kolik funkčních stačí (None = co nejvíc)
            max_checks (int|None): strop počtu ověření
            max_workers (int): souběžnost dotazů na Webshare

        Returns:
            list: podmnožina ``results`` (zachované pořadí) s funkčním odkazem
        """
        if not results:
            return []

        from concurrent.futures import ThreadPoolExecutor

        if max_checks is None:
            base = want if want else len(results)
            max_checks = min(len(results), max(base * 3, 12))
        candidates = results[:max_checks]

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            flags = list(ex.map(
                lambda r: self.is_available(r.get('ident')), candidates
            ))

        available = [r for r, ok in zip(candidates, flags) if ok]
        if want:
            available = available[:want]

        logger.info(
            f"filter_available: z {len(candidates)} ověřených je "
            f"{len(available)} funkčních"
        )
        return available


# Singleton instance
_client = None

def get_client():
    """Get Webshare client singleton"""
    global _client
    if _client is None:
        _client = WebshareClient()
    return _client

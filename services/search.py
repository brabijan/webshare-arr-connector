"""Search orchestration service"""
import logging
import re
from datetime import datetime, timedelta
from models.database import (
    SearchCache, PendingConfirmation, SearchAlias, get_or_create_alias,
    get_db_session,
)
from services import webshare, parser, sonarr, radarr, csfd

logger = logging.getLogger(__name__)

# Jak často znovu zkoušet ČSFD dohledání, pokud už proběhlo
CSFD_RECHECK_DAYS = 30


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def resolve_extra_titles(item_info):
    """Doplní do item_info['extra_titles'] vlastní a český (ČSFD) název.

    - Vlastní název (custom_title) zadaný uživatelem má vždy přednost.
    - Český název se dohledá z ČSFD a uloží do DB (auto_title); znovu se
      ptáme nejvýš jednou za CSFD_RECHECK_DAYS.

    Vrací seznam názvů navíc (může být prázdný). Nikdy nevyhazuje výjimku.
    """
    source = item_info.get('source')
    source_id = item_info.get('series_id') or item_info.get('movie_id')
    base_title = item_info.get('series_title') or item_info.get('title') or ''
    year = item_info.get('series_year') or item_info.get('year')
    want_series = source == 'sonarr'

    if not source or source_id is None:
        return []

    db = get_db_session()
    try:
        alias = get_or_create_alias(db, source, source_id)

        # Potřebujeme dohledat český název z ČSFD?
        need_lookup = alias.auto_title is None and (
            alias.auto_checked_at is None
            or alias.auto_checked_at < datetime.utcnow() - timedelta(days=CSFD_RECHECK_DAYS)
        )

        if need_lookup and base_title:
            try:
                match = csfd.find_czech_title(
                    base_title, year=year, want_series=want_series
                )
            except Exception as e:
                logger.warning(f"ČSFD dohledání selhalo pro '{base_title}': {e}")
                match = None

            alias.auto_checked_at = datetime.utcnow()
            if match and match.get('czech_title'):
                czech = match['czech_title'].strip()
                # Ukládej jen pokud se liší od původního názvu
                if _norm(czech) and _norm(czech) != _norm(base_title):
                    alias.auto_title = czech
            db.commit()

        # Sestav názvy navíc, vyřaď shodné s původním názvem
        extra = [
            t for t in alias.effective_titles()
            if _norm(t) and _norm(t) != _norm(base_title)
        ]
        return extra
    except Exception as e:
        logger.warning(f"resolve_extra_titles selhalo: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return []
    finally:
        db.close()


def search_with_cache(query, force_refresh=False):
    """
    Search with caching

    Args:
        query (str): Search query
        force_refresh (bool): Force refresh cache

    Returns:
        list: Search results
    """
    if not force_refresh:
        # Try to get from cache
        db = get_db_session()
        try:
            cache_entry = db.query(SearchCache).filter(SearchCache.query == query).first()

            if cache_entry and not cache_entry.is_expired:
                logger.info(f"Using cached results for query: {query}")
                return cache_entry.results

        finally:
            db.close()

    # Fetch from Webshare
    ws_client = webshare.get_client()
    results = ws_client.search(query)

    # Cache results
    if results:
        db = get_db_session()
        try:
            # Delete existing cache entry
            db.query(SearchCache).filter(SearchCache.query == query).delete()

            # Create new cache entry
            cache_entry = SearchCache(query=query, results=results)
            db.add(cache_entry)
            db.commit()

        except Exception as e:
            logger.error(f"Error caching search results: {e}")
            db.rollback()
        finally:
            db.close()

    return results


def search_for_item(item_info, top_n=5):
    """
    Search for an item using multiple query variations

    Args:
        item_info (dict): Item information from Sonarr/Radarr
        top_n (int): Number of top results to return

    Returns:
        list: Ranked top results
    """
    source = item_info.get('source')

    # Doplň vlastní / český (ČSFD) název pro hledání
    if not item_info.get('extra_titles'):
        item_info['extra_titles'] = resolve_extra_titles(item_info)

    # Generate queries
    if source == 'sonarr':
        sonarr_client = sonarr.get_client()
        queries = sonarr_client.generate_search_queries(item_info)
    elif source == 'radarr':
        radarr_client = radarr.get_client()
        queries = radarr_client.generate_search_queries(item_info)
    else:
        logger.error(f"Unknown source: {source}")
        return []

    if not queries:
        logger.warning("No search queries generated")
        return []

    # Search with each query and aggregate results
    all_results = []
    seen_idents = set()

    for query in queries:
        results = search_with_cache(query)

        # Deduplicate by ident
        for result in results:
            ident = result.get('ident')
            if ident and ident not in seen_idents:
                all_results.append(result)
                seen_idents.add(ident)

    logger.info(f"Found {len(all_results)} unique results across {len(queries)} queries")

    if not all_results:
        return []

    # Extract expected values for ranking
    expected_title = item_info.get('series_title') or item_info.get('title')
    expected_season = item_info.get('season')
    expected_episode = item_info.get('episode')

    # Přijatelné názvy = původní + vlastní/český (kvůli filtru nesedících)
    expected_titles = []
    for t in [expected_title, *(item_info.get('extra_titles') or [])]:
        if t and t not in expected_titles:
            expected_titles.append(t)

    # Rank results with expected values (nesedící názvy se diskvalifikují)
    ranked = parser.rank_results(
        all_results,
        min_results=top_n,
        expected_season=expected_season,
        expected_episode=expected_episode,
        expected_titles=expected_titles
    )

    if not ranked:
        return []

    # Zahoď soubory bez funkčního odkazu (FATAL/mrtvé na Webshare),
    # ať se uživateli nezobrazují vůbec
    ws_client = webshare.get_client()
    available = ws_client.filter_available(ranked, want=top_n)
    return available


def create_pending_confirmation(item_info, search_results):
    """
    Create a pending confirmation entry in database

    Args:
        item_info (dict): Item information
        search_results (list): Top search results

    Returns:
        int: Pending confirmation ID
    """
    db = get_db_session()
    try:
        # Build search query string (first query)
        if item_info.get('source') == 'sonarr':
            title = item_info.get('series_title', '')
            season = item_info.get('season')
            episode = item_info.get('episode')
            search_query = f"{title} S{season:02d}E{episode:02d}" if title else ""
        else:  # radarr
            title = item_info.get('title', '')
            year = item_info.get('year')
            search_query = f"{title} {year}" if year else title

        pending = PendingConfirmation(
            source=item_info.get('source'),
            source_id=item_info.get('series_id') or item_info.get('movie_id'),
            item_title=item_info.get('series_title') or item_info.get('title'),
            season=item_info.get('season'),
            episode=item_info.get('episode'),
            year=item_info.get('year'),
            search_query=search_query,
            results_json='[]',  # Will be set via property
            status='pending'
        )

        # Set results via property (converts to JSON)
        pending.results = search_results

        db.add(pending)
        db.commit()
        db.refresh(pending)

        logger.info(f"Created pending confirmation ID: {pending.id}")
        return pending.id

    except Exception as e:
        logger.error(f"Error creating pending confirmation: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def _scan_episode(series_id, series_title, series_path, season, episode_meta,
                  top_n=8):
    """Prohledá jednu epizodu, vrátí dict s funkčními výsledky.

    U epizody s aspoň jedním výsledkem založí pending confirmation, aby
    šlo stáhnout přes /api/confirm.
    """
    ep_num = episode_meta.get('episodeNumber')
    item_info = {
        'source': 'sonarr',
        'series_id': series_id,
        'series_title': series_title,
        'season': season,
        'episode': ep_num,
    }

    try:
        results = search_for_item(item_info, top_n=top_n)
    except Exception as e:
        logger.warning(
            f"Sken S{season:02d}E{ep_num or 0:02d} selhal: {e}"
        )
        results = []

    pending_id = None
    if results:
        pending_id = create_pending_confirmation(item_info, results)
        if pending_id and series_path:
            db = get_db_session()
            try:
                pending = db.query(PendingConfirmation).filter(
                    PendingConfirmation.id == pending_id
                ).first()
                if pending:
                    pending.destination_path = series_path
                    db.commit()
            finally:
                db.close()

    return {
        'episode_number': ep_num,
        'title': episode_meta.get('title'),
        'air_date': episode_meta.get('airDate'),
        'pending_id': pending_id,
        'results_count': len(results),
        'results': results,
    }


def _scan_episodes_parallel(series_id, series_title, series_path, season,
                            episodes_meta, top_n, max_workers=5):
    """Proskenuje epizody paralelně (síťově náročné), zachová pořadí."""
    if not episodes_meta:
        return []

    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, min(max_workers, len(episodes_meta)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(
            lambda em: _scan_episode(
                series_id, series_title, series_path, season, em, top_n
            ),
            episodes_meta
        ))


def scan_season(series_id, season, series_title=None, series_path=None,
                top_n=8):
    """Proskenuje všechny chybějící epizody jedné sezóny.

    Returns:
        dict: {success, series_id, season, episodes:[...]}
    """
    sonarr_client = sonarr.get_client()
    if not series_title or not series_path:
        series = sonarr_client.get_series_by_id(series_id)
        if series:
            series_title = series_title or series.get('title')
            series_path = series_path or series.get('path')

    seasons = sonarr_client.get_series_missing_episodes(series_id)
    episodes_meta = sorted(
        seasons.get(season, []),
        key=lambda e: e.get('episodeNumber') or 0
    )

    logger.info(
        f"Sken sezóny: {series_title} S{season:02d} "
        f"({len(episodes_meta)} chybějících epizod)"
    )

    episodes = _scan_episodes_parallel(
        series_id, series_title, series_path, season, episodes_meta, top_n
    )

    return {
        'success': True,
        'series_id': series_id,
        'series_title': series_title,
        'season': season,
        'episodes': episodes,
    }


def scan_series(series_id, top_n=8):
    """Proskenuje všechny chybějící epizody napříč všemi sezónami seriálu.

    Returns:
        dict: {success, series_id, series_title, seasons:[{season, episodes}]}
    """
    sonarr_client = sonarr.get_client()
    series = sonarr_client.get_series_by_id(series_id)
    if not series:
        return {'success': False, 'error': 'Series not found'}

    series_title = series.get('title')
    series_path = series.get('path')

    seasons_dict = sonarr_client.get_series_missing_episodes(series_id)

    logger.info(
        f"Sken celého seriálu: {series_title} "
        f"({len(seasons_dict)} sezón s chybějícími epizodami)"
    )

    seasons = []
    for season_num in sorted(seasons_dict):
        episodes_meta = sorted(
            seasons_dict[season_num],
            key=lambda e: e.get('episodeNumber') or 0
        )
        episodes = _scan_episodes_parallel(
            series_id, series_title, series_path,
            season_num, episodes_meta, top_n
        )
        seasons.append({'season': season_num, 'episodes': episodes})

    return {
        'success': True,
        'series_id': series_id,
        'series_title': series_title,
        'seasons': seasons,
    }


def search_missing_items(source='sonarr', limit=10):
    """
    Search for missing items from Sonarr/Radarr

    Args:
        source (str): 'sonarr' or 'radarr'
        limit (int): Maximum number of items to process

    Returns:
        list: List of pending confirmation IDs
    """
    pending_ids = []

    if source == 'sonarr':
        sonarr_client = sonarr.get_client()
        missing_items = sonarr_client.get_missing_episodes(page_size=limit)

        for item in missing_items:
            # Convert to item_info format
            series = item.get('series', {})
            item_info = {
                'source': 'sonarr',
                'series_id': series.get('id'),
                'series_title': series.get('title'),
                'series_year': series.get('year'),
                'season': item.get('seasonNumber'),
                'episode': item.get('episodeNumber'),
                'episode_title': item.get('title')
            }

            # Search for this item
            results = search_for_item(item_info)

            if results:
                pending_id = create_pending_confirmation(item_info, results)
                if pending_id:
                    pending_ids.append(pending_id)

    elif source == 'radarr':
        radarr_client = radarr.get_client()
        missing_items = radarr_client.get_missing_movies(page_size=limit)

        for item in missing_items:
            item_info = {
                'source': 'radarr',
                'movie_id': item.get('id'),
                'title': item.get('title'),
                'year': item.get('year'),
                'tmdb_id': item.get('tmdbId'),
                'imdb_id': item.get('imdbId')
            }

            # Search for this item
            results = search_for_item(item_info)

            if results:
                pending_id = create_pending_confirmation(item_info, results)
                if pending_id:
                    pending_ids.append(pending_id)

    logger.info(f"Created {len(pending_ids)} pending confirmations for {source}")
    return pending_ids

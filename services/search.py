"""Search orchestration service"""
import logging
from datetime import datetime
from models.database import SearchCache, PendingConfirmation, get_db_session
from services import webshare, parser, sonarr, radarr

logger = logging.getLogger(__name__)


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

    # Rank results with expected values
    ranked = parser.rank_results(
        all_results,
        min_results=top_n,
        expected_title=expected_title,
        expected_season=expected_season,
        expected_episode=expected_episode
    )

    # Return top N
    return ranked[:top_n]


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

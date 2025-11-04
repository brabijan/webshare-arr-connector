"""REST API endpoints"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import logging
from models.database import PendingConfirmation, DownloadHistory, get_db_session
from services import webshare, pyload, search

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/pending', methods=['GET'])
def get_pending():
    """Get list of pending confirmations"""
    try:
        db = get_db_session()
        try:
            pending_items = db.query(PendingConfirmation).filter(
                PendingConfirmation.status == 'pending'
            ).order_by(PendingConfirmation.created_at.desc()).all()

            return jsonify({
                'count': len(pending_items),
                'items': [
                    {
                        'id': item.id,
                        'source': item.source,
                        'title': item.item_title,
                        'season': item.season,
                        'episode': item.episode,
                        'year': item.year,
                        'search_query': item.search_query,
                        'results_count': len(item.results),
                        'results': item.results,
                        'created_at': item.created_at.isoformat()
                    }
                    for item in pending_items
                ]
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting pending items: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/pending/<int:pending_id>', methods=['GET'])
def get_pending_detail(pending_id):
    """Get detailed info for a pending confirmation"""
    try:
        db = get_db_session()
        try:
            item = db.query(PendingConfirmation).filter(
                PendingConfirmation.id == pending_id
            ).first()

            if not item:
                return jsonify({'error': 'Pending item not found'}), 404

            return jsonify({
                'id': item.id,
                'source': item.source,
                'title': item.item_title,
                'season': item.season,
                'episode': item.episode,
                'year': item.year,
                'search_query': item.search_query,
                'results': item.results,
                'status': item.status,
                'created_at': item.created_at.isoformat()
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting pending detail: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/confirm', methods=['POST'])
def confirm_download():
    """
    Confirm and download a selected file

    POST body:
    {
        "pending_id": 123,
        "result_index": 0
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        pending_id = data.get('pending_id')
        result_index = data.get('result_index', 0)

        if not pending_id:
            return jsonify({'error': 'pending_id is required'}), 400

        db = get_db_session()
        try:
            # Get pending item
            pending = db.query(PendingConfirmation).filter(
                PendingConfirmation.id == pending_id
            ).first()

            if not pending:
                return jsonify({'error': 'Pending item not found'}), 404

            if pending.status != 'pending':
                return jsonify({'error': f'Item already {pending.status}'}), 400

            results = pending.results

            if result_index >= len(results):
                return jsonify({'error': 'Invalid result_index'}), 400

            selected_result = results[result_index]

            # Get direct link from Webshare
            ws_client = webshare.get_client()
            direct_link, error = ws_client.get_direct_link(selected_result['ident'])

            if error:
                return jsonify({'error': f'Failed to get direct link: {error}'}), 500

            # Generate package name
            if pending.source == 'sonarr':
                package_name = f"{pending.item_title} - S{pending.season:02d}E{pending.episode:02d}"
            else:  # radarr
                package_name = f"{pending.item_title} ({pending.year})"

            # Get destination path from pending confirmation
            destination_path = pending.destination_path

            # Add to pyLoad with destination path
            success, message, package_id = pyload.add_to_pyload(
                direct_link,
                package_name,
                destination_path=destination_path
            )

            if not success:
                return jsonify({'error': f'Failed to add to pyLoad: {message}'}), 500

            # Update pending confirmation
            pending.status = 'confirmed'
            pending.selected_index = result_index
            pending.confirmed_at = datetime.utcnow()

            # Create download history entry
            history = DownloadHistory(
                source=pending.source,
                source_id=pending.source_id,
                item_title=pending.item_title,
                season=pending.season,
                episode=pending.episode,
                year=pending.year,
                webshare_ident=selected_result['ident'],
                filename=selected_result['name'],
                file_size=selected_result.get('size'),
                quality=selected_result.get('parsed', {}).get('quality'),
                language=selected_result.get('parsed', {}).get('language'),
                destination_path=destination_path,
                pyload_package_id=package_id,
                status='sent'
            )

            db.add(history)
            db.commit()

            logger.info(f"Confirmed download for pending ID {pending_id}, pyLoad package: {package_id}")

            # Get navigation info for next step
            from services import navigation
            nav_info = navigation.get_navigation_info(
                source=pending.source,
                series_id=pending.source_id,
                season_num=pending.season
            )

            return jsonify({
                'success': True,
                'pending_id': pending_id,
                'package_id': package_id,
                'package_name': package_name,
                'filename': selected_result['name'],
                'message': message,
                'navigation': nav_info
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error confirming download: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/search', methods=['POST'])
def manual_search():
    """
    Manual search endpoint

    POST body:
    {
        "source": "sonarr" or "radarr",
        "source_id": 123  // Optional: ID from Sonarr/Radarr
        "query": "Movie Title"  // Or free text search
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        source = data.get('source')
        source_id = data.get('source_id')
        query = data.get('query')

        if not source or not (source_id or query):
            return jsonify({'error': 'source and (source_id or query) are required'}), 400

        # TODO: Implement fetching from Sonarr/Radarr by ID
        # For now, just use query directly
        if query:
            results = search.search_with_cache(query, force_refresh=True)

            if not results:
                return jsonify({
                    'status': 'no_results',
                    'message': 'No files found'
                }), 200

            # Rank results
            from services import parser
            ranked = parser.rank_results(results, min_results=10)

            return jsonify({
                'success': True,
                'query': query,
                'results_count': len(ranked),
                'results': ranked[:10]
            }), 200

        return jsonify({'error': 'Not implemented yet'}), 501

    except Exception as e:
        logger.error(f"Error in manual search: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/history', methods=['GET'])
def get_history():
    """Get download history"""
    try:
        limit = request.args.get('limit', 50, type=int)

        db = get_db_session()
        try:
            history_items = db.query(DownloadHistory).order_by(
                DownloadHistory.created_at.desc()
            ).limit(limit).all()

            return jsonify({
                'count': len(history_items),
                'items': [
                    {
                        'id': item.id,
                        'source': item.source,
                        'title': item.item_title,
                        'season': item.season,
                        'episode': item.episode,
                        'year': item.year,
                        'filename': item.filename,
                        'quality': item.quality,
                        'language': item.language,
                        'file_size_gb': round(item.file_size / (1024**3), 2) if item.file_size else None,
                        'pyload_package_id': item.pyload_package_id,
                        'status': item.status,
                        'created_at': item.created_at.isoformat()
                    }
                    for item in history_items
                ]
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/stats', methods=['GET'])
def get_stats():
    """Get statistics"""
    try:
        db = get_db_session()
        try:
            total_downloads = db.query(DownloadHistory).count()
            pending_count = db.query(PendingConfirmation).filter(
                PendingConfirmation.status == 'pending'
            ).count()

            return jsonify({
                'total_downloads': total_downloads,
                'pending_confirmations': pending_count
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/series', methods=['GET'])
def get_series():
    """Get all monitored series from Sonarr with missing episode counts"""
    try:
        from services import sonarr
        from sqlalchemy import func
        sonarr_client = sonarr.get_client()

        all_series = sonarr_client.get_all_series()

        # Get downloading counts from database (GROUP BY series_id)
        db = get_db_session()
        try:
            downloading_counts = db.query(
                DownloadHistory.source_id,
                func.count(DownloadHistory.id).label('count')
            ).filter(
                DownloadHistory.source == 'sonarr',
                DownloadHistory.status == 'sent'
            ).group_by(DownloadHistory.source_id).all()

            # Convert to dict for easy lookup
            downloading_dict = {series_id: count for series_id, count in downloading_counts}

        finally:
            db.close()

        # Enrich with missing count and downloading count
        series_list = []
        for s in all_series:
            series_id = s.get('id')
            stats = s.get('statistics', {})
            missing_count = stats.get('episodeCount', 0) - stats.get('episodeFileCount', 0)
            downloading_count = downloading_dict.get(series_id, 0)

            # Find poster image
            poster_url = None
            for image in s.get('images', []):
                if image.get('coverType') == 'poster':
                    poster_url = image.get('remoteUrl') or image.get('url')
                    break

            series_list.append({
                'id': series_id,
                'title': s.get('title'),
                'year': s.get('year'),
                'path': s.get('path'),
                'poster_url': poster_url,
                'missing_count': missing_count,
                'downloading_count': downloading_count,
                'monitored': s.get('monitored')
            })

        # Filter for series with missing OR downloading episodes
        series_with_activity = [
            s for s in series_list
            if s['missing_count'] > 0 or s['downloading_count'] > 0
        ]

        return jsonify({
            'success': True,
            'count': len(series_with_activity),
            'series': series_with_activity
        }), 200

    except Exception as e:
        logger.error(f"Error fetching series: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/series/<int:series_id>/seasons', methods=['GET'])
def get_series_seasons(series_id):
    """Get seasons with missing episodes for a specific series"""
    try:
        from services import sonarr
        from sqlalchemy import func
        sonarr_client = sonarr.get_client()

        seasons_dict = sonarr_client.get_series_missing_episodes(series_id)

        # Get downloading counts per season from database
        db = get_db_session()
        try:
            downloading_counts = db.query(
                DownloadHistory.season,
                func.count(DownloadHistory.id).label('count')
            ).filter(
                DownloadHistory.source == 'sonarr',
                DownloadHistory.source_id == series_id,
                DownloadHistory.status == 'sent'
            ).group_by(DownloadHistory.season).all()

            # Convert to dict for easy lookup
            downloading_dict = {season: count for season, count in downloading_counts}

        finally:
            db.close()

        # Convert to list format with counts
        seasons_list = []
        for season_num, episodes in sorted(seasons_dict.items()):
            seasons_list.append({
                'season_number': season_num,
                'missing_count': len(episodes),
                'downloading_count': downloading_dict.get(season_num, 0)
            })

        return jsonify({
            'success': True,
            'series_id': series_id,
            'seasons': seasons_list
        }), 200

    except Exception as e:
        logger.error(f"Error fetching seasons: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/series/<int:series_id>/season/<int:season_num>', methods=['GET'])
def get_season_episodes(series_id, season_num):
    """Get missing episodes for a specific season"""
    try:
        from services import sonarr
        sonarr_client = sonarr.get_client()

        seasons_dict = sonarr_client.get_series_missing_episodes(series_id)
        episodes = seasons_dict.get(season_num, [])

        # Format episode list
        episode_list = []
        for ep in episodes:
            episode_list.append({
                'id': ep.get('id'),
                'episode_number': ep.get('episodeNumber'),
                'season_number': ep.get('seasonNumber'),
                'title': ep.get('title'),
                'air_date': ep.get('airDate'),
                'has_file': ep.get('hasFile'),
                'monitored': ep.get('monitored')
            })

        return jsonify({
            'success': True,
            'series_id': series_id,
            'season_number': season_num,
            'episodes': episode_list
        }), 200

    except Exception as e:
        logger.error(f"Error fetching episodes: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/movies', methods=['GET'])
def get_movies():
    """Get all monitored movies without files from Radarr"""
    try:
        from services import radarr
        radarr_client = radarr.get_client()

        missing_movies = radarr_client.get_all_monitored_movies()

        # Get downloading movie IDs from database
        db = get_db_session()
        try:
            downloading_ids = db.query(DownloadHistory.source_id).filter(
                DownloadHistory.source == 'radarr',
                DownloadHistory.status == 'sent'
            ).distinct().all()

            # Convert to set for fast lookup
            downloading_set = {movie_id for (movie_id,) in downloading_ids}

        finally:
            db.close()

        # Format movie list
        movie_list = []
        for m in missing_movies:
            movie_id = m.get('id')
            is_downloading = movie_id in downloading_set

            # Find poster image
            poster_url = None
            for image in m.get('images', []):
                if image.get('coverType') == 'poster':
                    poster_url = image.get('remoteUrl') or image.get('url')
                    break

            movie_list.append({
                'id': movie_id,
                'title': m.get('title'),
                'year': m.get('year'),
                'path': m.get('path'),
                'poster_url': poster_url,
                'monitored': m.get('monitored'),
                'has_file': m.get('hasFile'),
                'is_downloading': is_downloading
            })

        return jsonify({
            'success': True,
            'count': len(movie_list),
            'movies': movie_list
        }), 200

    except Exception as e:
        logger.error(f"Error fetching movies: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/search-episode', methods=['POST'])
def search_episode():
    """
    Search Webshare for a specific episode

    POST body:
    {
        "series_id": 123,
        "series_title": "Breaking Bad",
        "series_path": "/mnt/sdc1/Serialy/Breaking Bad",
        "season": 1,
        "episode": 1
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        series_title = data.get('series_title')
        season = data.get('season')
        episode = data.get('episode')
        series_path = data.get('series_path')

        if not all([series_title, season is not None, episode is not None]):
            return jsonify({'error': 'series_title, season, and episode are required'}), 400

        # Create item_info for search
        item_info = {
            'source': 'sonarr',
            'series_id': data.get('series_id'),
            'series_title': series_title,
            'season': season,
            'episode': episode
        }

        # Search for this episode
        results = search.search_for_item(item_info, top_n=10)

        if not results:
            return jsonify({
                'success': True,
                'results_count': 0,
                'results': [],
                'message': 'No results found'
            }), 200

        # Create pending confirmation
        pending_id = search.create_pending_confirmation(item_info, results)

        # Store destination path in pending confirmation
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

        return jsonify({
            'success': True,
            'pending_id': pending_id,
            'results_count': len(results),
            'results': results,
            'destination_path': series_path
        }), 200

    except Exception as e:
        logger.error(f"Error searching episode: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/search-movie', methods=['POST'])
def search_movie():
    """
    Search Webshare for a specific movie

    POST body:
    {
        "movie_id": 123,
        "title": "The Matrix",
        "year": 1999,
        "path": "/movies/The Matrix (1999)"
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        title = data.get('title')
        year = data.get('year')
        movie_path = data.get('path')

        if not title:
            return jsonify({'error': 'title is required'}), 400

        # Create item_info for search
        item_info = {
            'source': 'radarr',
            'movie_id': data.get('movie_id'),
            'title': title,
            'year': year
        }

        # Search for this movie
        results = search.search_for_item(item_info, top_n=10)

        if not results:
            return jsonify({
                'success': True,
                'results_count': 0,
                'results': [],
                'message': 'No results found'
            }), 200

        # Create pending confirmation
        pending_id = search.create_pending_confirmation(item_info, results)

        # Store destination path in pending confirmation
        if pending_id and movie_path:
            db = get_db_session()
            try:
                pending = db.query(PendingConfirmation).filter(
                    PendingConfirmation.id == pending_id
                ).first()
                if pending:
                    pending.destination_path = movie_path
                    db.commit()
            finally:
                db.close()

        return jsonify({
            'success': True,
            'pending_id': pending_id,
            'results_count': len(results),
            'results': results,
            'destination_path': movie_path
        }), 200

    except Exception as e:
        logger.error(f"Error searching movie: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/download-status', methods=['GET'])
def get_download_status():
    """
    Get download status for episodes in a season

    Query parameters:
    - series_id: Sonarr series ID (required for TV shows)
    - season: Season number (optional, if not provided returns all for series)
    - source: 'sonarr' or 'radarr' (optional, defaults to 'sonarr')

    Returns list of episode IDs or movie IDs that have been sent to pyLoad
    """
    try:
        source = request.args.get('source', 'sonarr')
        series_id = request.args.get('series_id', type=int)
        season = request.args.get('season', type=int)

        db = get_db_session()
        try:
            # Query download history
            query = db.query(DownloadHistory).filter(
                DownloadHistory.source == source,
                DownloadHistory.status == 'sent'
            )

            if series_id:
                query = query.filter(DownloadHistory.source_id == series_id)

            if season is not None:
                query = query.filter(DownloadHistory.season == season)

            history_items = query.all()

            # Build response with episode/movie identifiers
            downloaded_items = []
            for item in history_items:
                if source == 'sonarr':
                    downloaded_items.append({
                        'season': item.season,
                        'episode': item.episode,
                        'identifier': f"S{item.season:02d}E{item.episode:02d}",
                        'filename': item.filename,
                        'pyload_package_id': item.pyload_package_id
                    })
                else:  # radarr
                    downloaded_items.append({
                        'title': item.item_title,
                        'year': item.year,
                        'filename': item.filename,
                        'pyload_package_id': item.pyload_package_id
                    })

            return jsonify({
                'success': True,
                'count': len(downloaded_items),
                'downloaded': downloaded_items
            }), 200

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting download status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

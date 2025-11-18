"""REST API endpoints"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import logging
from models.database import PendingConfirmation, DownloadHistory, get_db_session
from services import webshare, pyload, search

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for deployment monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    }), 200


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
        "result_index": 0,
        "upgrade_metadata": {  // Optional, for upgrade downloads
            "is_upgrade": true,
            "episode_file_id": 123,  // or movie_file_id
            "movie_file_id": 456
        }
    }
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        pending_id = data.get('pending_id')
        result_index = data.get('result_index', 0)
        upgrade_metadata = data.get('upgrade_metadata', {})

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
            is_upgrade = upgrade_metadata.get('is_upgrade', False)
            if pending.source == 'sonarr':
                package_name = f"{pending.item_title} - S{pending.season:02d}E{pending.episode:02d}"
                if is_upgrade:
                    package_name += " (Upgrade)"
            else:  # radarr
                package_name = f"{pending.item_title} ({pending.year})"
                if is_upgrade:
                    package_name += " (Upgrade)"

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
                status='sent',
                is_upgrade=is_upgrade,
                sonarr_episode_file_id=upgrade_metadata.get('episode_file_id'),
                radarr_movie_file_id=upgrade_metadata.get('movie_file_id')
            )

            db.add(history)
            db.commit()

            logger.info(f"Confirmed download for pending ID {pending_id}, pyLoad package: {package_id}, is_upgrade: {is_upgrade}")

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

        # Get all downloading records from database
        db = get_db_session()
        try:
            downloading_records = db.query(DownloadHistory).filter(
                DownloadHistory.source == 'sonarr',
                DownloadHistory.status == 'sent'
            ).all()

            # Group by series_id for easy lookup
            downloading_by_series = {}
            for record in downloading_records:
                if record.source_id not in downloading_by_series:
                    downloading_by_series[record.source_id] = []
                downloading_by_series[record.source_id].append(record)

        finally:
            db.close()

        # Enrich with missing count and downloading count
        series_list = []
        for s in all_series:
            series_id = s.get('id')
            stats = s.get('statistics', {})
            missing_count = stats.get('episodeCount', 0) - stats.get('episodeFileCount', 0)

            # Get missing episodes for this series to filter downloading
            downloading_count = 0
            if series_id in downloading_by_series:
                seasons_dict = sonarr_client.get_series_missing_episodes(series_id)
                # Create set of (season, episode) tuples for missing episodes
                missing_episodes = set()
                for season_num, episodes in seasons_dict.items():
                    for ep in episodes:
                        missing_episodes.add((season_num, ep.get('episodeNumber')))

                # Count only downloading records that match missing episodes
                for record in downloading_by_series[series_id]:
                    if (record.season, record.episode) in missing_episodes:
                        downloading_count += 1

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

        # Get downloading records for this series from database
        db = get_db_session()
        try:
            downloading_records = db.query(DownloadHistory).filter(
                DownloadHistory.source == 'sonarr',
                DownloadHistory.source_id == series_id,
                DownloadHistory.status == 'sent'
            ).all()

        finally:
            db.close()

        # Convert to list format with counts
        seasons_list = []
        for season_num, episodes in sorted(seasons_dict.items()):
            # Create set of episode numbers that are missing in this season
            missing_episode_nums = {ep.get('episodeNumber') for ep in episodes}

            # Count only downloading records that match missing episodes in this season
            downloading_count = sum(
                1 for record in downloading_records
                if record.season == season_num and record.episode in missing_episode_nums
            )

            seasons_list.append({
                'season_number': season_num,
                'missing_count': len(episodes),
                'downloading_count': downloading_count
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


@api_bp.route('/library/series', methods=['GET'])
def library_series():
    """Get list of series with completed downloads"""
    try:
        from services.sonarr import get_client as get_sonarr
        from services.parser import parse_filename
        import requests

        sonarr = get_sonarr()

        # Get ALL series (not just monitored) directly from API
        url = f"{sonarr.base_url}/api/v3/series"
        response = requests.get(url, headers=sonarr.headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"Failed to get series from Sonarr: {response.status_code}")
            return jsonify({'error': 'Failed to fetch series from Sonarr'}), 500

        all_series = response.json()

        # Filter series that have at least one episode file
        series_with_files = []
        for series in all_series:
            files = sonarr.get_series_files(series['id'])
            if files:
                # Find poster image
                poster_url = None
                for image in series.get('images', []):
                    if image.get('coverType') == 'poster':
                        poster_url = image.get('remoteUrl') or image.get('url')
                        break

                series_with_files.append({
                    'id': series.get('id'),
                    'title': series.get('title'),
                    'year': series.get('year'),
                    'path': series.get('path'),
                    'poster_url': poster_url,
                    'file_count': len(files),
                    'monitored': series.get('monitored')
                })

        # Sort series alphabetically by title
        series_with_files.sort(key=lambda x: x['title'].lower() if x['title'] else '')

        return jsonify({
            'success': True,
            'count': len(series_with_files),
            'series': series_with_files
        }), 200

    except Exception as e:
        logger.error(f"Error getting library series: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/library/series/<int:series_id>/seasons', methods=['GET'])
def library_series_seasons(series_id):
    """Get seasons for a series with file counts"""
    try:
        from services.sonarr import get_client as get_sonarr

        sonarr = get_sonarr()
        series = sonarr.get_series_by_id(series_id)
        if not series:
            return jsonify({'error': 'Series not found'}), 404

        files = sonarr.get_series_files(series_id)

        # Group files by season
        seasons = {}
        for file in files:
            season_num = file.get('seasonNumber', 0)
            if season_num not in seasons:
                seasons[season_num] = {
                    'seasonNumber': season_num,
                    'fileCount': 0
                }
            seasons[season_num]['fileCount'] += 1

        # Find poster image
        poster_url = None
        for image in series.get('images', []):
            if image.get('coverType') == 'poster':
                poster_url = image.get('remoteUrl') or image.get('url')
                break

        # Create clean series dict
        series_dict = {
            'id': series.get('id'),
            'title': series.get('title'),
            'year': series.get('year'),
            'path': series.get('path'),
            'poster_url': poster_url,
            'monitored': series.get('monitored'),
            'overview': series.get('overview')
        }

        # Convert seasons to use snake_case for consistency with template
        seasons_list = []
        for season_data in seasons.values():
            seasons_list.append({
                'season_number': season_data['seasonNumber'],
                'file_count': season_data['fileCount']
            })

        # Sort seasons by season number
        seasons_list.sort(key=lambda x: x['season_number'])

        return jsonify({
            'success': True,
            'series': series_dict,
            'seasons': seasons_list
        }), 200

    except Exception as e:
        logger.error(f"Error getting series seasons: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/library/series/<int:series_id>/season/<int:season_num>', methods=['GET'])
def library_season_episodes(series_id, season_num):
    """Get episodes for a season with extracted metadata from files"""
    try:
        from services.sonarr import get_client as get_sonarr
        from services.parser import parse_filename
        from services.metadata_extractor import extract_video_metadata, format_metadata_for_display, is_ffprobe_available
        from services.file_mover import find_downloaded_file
        from models.database import DownloadHistory, get_db_session
        from pathlib import Path
        import json

        sonarr = get_sonarr()
        series = sonarr.get_series_by_id(series_id)
        episodes = sonarr.get_episodes(series_id)
        files = sonarr.get_series_files(series_id)
        db = get_db_session()

        if not series:
            return jsonify({'error': 'Series not found'}), 404

        series_path = series.get('path', '')
        use_ffprobe = is_ffprobe_available()

        if not use_ffprobe:
            logger.warning("ffprobe not available, falling back to filename parsing")

        # Create file lookup
        file_lookup = {f['id']: f for f in files}

        # Get all pending upgrades for this series
        pending_upgrades = db.query(DownloadHistory).filter(
            DownloadHistory.source == 'sonarr',
            DownloadHistory.source_id == series_id,
            DownloadHistory.is_upgrade == True,
            DownloadHistory.upgrade_decision.is_(None)
        ).all()

        # Create lookup by season/episode
        upgrade_lookup = {}
        for upgrade in pending_upgrades:
            key = (upgrade.season, upgrade.episode)
            upgrade_lookup[key] = upgrade

        # Convert Language objects to strings
        def convert_languages(lang_value):
            """Convert Language objects to string codes"""
            if lang_value is None:
                return []
            if isinstance(lang_value, list):
                return [str(lang) for lang in lang_value]
            else:
                return [str(lang_value)]

        # Filter and enrich episodes for this season
        season_episodes = []
        for ep in episodes:
            if ep.get('seasonNumber') != season_num:
                continue

            if ep.get('hasFile') and ep.get('episodeFileId'):
                file_id = ep['episodeFileId']
                file_data = file_lookup.get(file_id)

                if file_data:
                    filename = file_data.get('relativePath', '').split('/')[-1]
                    relative_path = file_data.get('relativePath', '')

                    # Build full file path
                    full_path = Path(series_path) / relative_path

                    # Try to extract metadata from file using ffprobe
                    metadata = None
                    if use_ffprobe and full_path.exists():
                        raw_metadata = extract_video_metadata(str(full_path))
                        if raw_metadata:
                            metadata = format_metadata_for_display(raw_metadata)

                    # Fallback to filename parsing if ffprobe failed or not available
                    if not metadata:
                        logger.debug(f"Using filename parsing for {filename}")
                        parsed = parse_filename(filename)
                        metadata = {
                            'resolution': parsed.get('screen_size', 'Unknown'),
                            'video_codec': parsed.get('video_codec_normalized', 'Unknown'),
                            'audio_languages': convert_languages(parsed.get('audio_languages')),
                            'subtitle_languages': convert_languages(parsed.get('subtitle_languages')),
                        }

                    # Check if there's a pending upgrade for this episode
                    upgrade_info = None
                    episode_key = (season_num, ep.get('episodeNumber'))
                    if episode_key in upgrade_lookup:
                        upgrade_record = upgrade_lookup[episode_key]

                        # Determine download status
                        is_downloading = upgrade_record.download_completed_at is None
                        download_status = 'downloading' if is_downloading else 'completed'

                        # Get new file metadata
                        new_metadata = None
                        new_parsed = parse_filename(upgrade_record.filename)

                        if not is_downloading:
                            # File is downloaded, try to extract real metadata
                            new_file_path = find_downloaded_file(upgrade_record.pyload_package_id, upgrade_record.filename)
                            if new_file_path and use_ffprobe:
                                real_metadata = extract_video_metadata(new_file_path)
                                if real_metadata:
                                    formatted = format_metadata_for_display(real_metadata)
                                    new_metadata = {
                                        'filename': upgrade_record.filename,
                                        'size': upgrade_record.file_size or formatted.get('file_size', 0),
                                        'quality': formatted.get('resolution', 'Unknown'),
                                        'codec': formatted.get('video_codec', 'Unknown'),
                                        'source': new_parsed.get('source_type_normalized', 'Unknown'),
                                        'audio_languages': formatted.get('audio_languages', []),
                                        'subtitles': formatted.get('subtitle_languages', []),
                                    }

                        # Fallback to filename parsing
                        if not new_metadata:
                            new_metadata = {
                                'filename': upgrade_record.filename,
                                'size': upgrade_record.file_size,
                                'quality': new_parsed.get('screen_size', 'Unknown'),
                                'codec': new_parsed.get('video_codec_normalized', 'Unknown'),
                                'source': new_parsed.get('source_type_normalized', 'Unknown'),
                                'audio_languages': convert_languages(new_parsed.get('audio_languages')),
                                'subtitles': convert_languages(new_parsed.get('subtitle_languages')),
                            }

                        upgrade_info = {
                            'id': upgrade_record.id,
                            'download_status': download_status,
                            'new_metadata': new_metadata,
                            'created_at': upgrade_record.created_at.isoformat() if upgrade_record.created_at else None
                        }

                    # Create clean episode dict
                    episode_dict = {
                        'id': ep.get('id'),
                        'episodeNumber': ep.get('episodeNumber'),
                        'seasonNumber': ep.get('seasonNumber'),
                        'title': ep.get('title'),
                        'airDate': ep.get('airDate'),
                        'hasFile': ep.get('hasFile'),
                        'monitored': ep.get('monitored'),
                        'overview': ep.get('overview'),
                        'episodeFileId': file_id,
                        'fileMetadata': {
                            'episodeFileId': file_id,
                            'filename': filename,
                            'size': file_data.get('size', 0),
                            'quality': file_data.get('quality', {}).get('quality', {}).get('name', 'Unknown'),
                            'resolution': metadata.get('resolution', 'Unknown'),
                            'video_codec': metadata.get('video_codec', 'Unknown'),
                            'source_type': parse_filename(filename).get('source_type_normalized', 'Unknown'),
                            'audio_languages': metadata.get('audio_languages', []),
                            'subtitle_languages': metadata.get('subtitle_languages', []),
                            'language': convert_languages(parse_filename(filename).get('language'))
                        },
                        'upgrade': upgrade_info
                    }
                    season_episodes.append(episode_dict)

        # Sort episodes by episode number
        season_episodes.sort(key=lambda x: x['episodeNumber'])

        db.close()
        return jsonify(season_episodes), 200

    except Exception as e:
        logger.error(f"Error getting season episodes: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/library/movies', methods=['GET'])
def library_movies():
    """Get list of movies with completed downloads"""
    try:
        from services.radarr import get_client as get_radarr
        from services.parser import parse_filename

        radarr = get_radarr()
        all_movies = radarr.get_all_movies()

        # Convert Language objects to strings
        def convert_languages(lang_value):
            """Convert Language objects to string codes"""
            if lang_value is None:
                return []
            if isinstance(lang_value, list):
                return [str(lang) for lang in lang_value]
            else:
                return [str(lang_value)]

        # Filter movies that have files and parse metadata
        movies_with_files = []
        for movie in all_movies:
            if movie.get('hasFile') and movie.get('movieFile'):
                file_data = movie['movieFile']
                filename = file_data.get('relativePath', '').split('/')[-1]
                parsed = parse_filename(filename)

                # Find poster image
                poster_url = None
                for image in movie.get('images', []):
                    if image.get('coverType') == 'poster':
                        poster_url = image.get('remoteUrl') or image.get('url')
                        break

                movies_with_files.append({
                    'id': movie.get('id'),
                    'title': movie.get('title'),
                    'year': movie.get('year'),
                    'path': movie.get('path'),
                    'poster_url': poster_url,
                    'file_count': 1,  # Movies have 1 file
                    'monitored': movie.get('monitored'),
                    'fileMetadata': {
                        'filename': filename,
                        'size': file_data.get('size', 0),
                        'quality': file_data.get('quality', {}).get('quality', {}).get('name', 'Unknown'),
                        'resolution': parsed.get('screen_size', 'Unknown'),
                        'video_codec': parsed.get('video_codec_normalized', 'Unknown'),
                        'source_type': parsed.get('source_type_normalized', 'Unknown'),
                        'audio_languages': convert_languages(parsed.get('audio_languages')),
                        'subtitle_languages': convert_languages(parsed.get('subtitle_languages')),
                        'language': convert_languages(parsed.get('language')),
                        'movieFileId': file_data.get('id')
                    }
                })

        # Sort movies alphabetically by title
        movies_with_files.sort(key=lambda x: x['title'].lower() if x['title'] else '')

        return jsonify({
            'success': True,
            'count': len(movies_with_files),
            'movies': movies_with_files
        }), 200

    except Exception as e:
        logger.error(f"Error getting library movies: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/pending-upgrades/series', methods=['GET'])
def pending_upgrades_series():
    """Get series upgrades waiting for decision"""
    try:
        from services.sonarr import get_client as get_sonarr
        from services.parser import parse_filename
        from services.metadata_extractor import extract_video_metadata, format_metadata_for_display
        from services.file_mover import find_downloaded_file
        from models.database import DownloadHistory, get_db_session

        db = get_db_session()
        sonarr = get_sonarr()

        # Get upgrades waiting for decision (including downloading)
        pending = db.query(DownloadHistory).filter(
            DownloadHistory.source == 'sonarr',
            DownloadHistory.is_upgrade == True,
            DownloadHistory.upgrade_decision.is_(None)
        ).all()

        results = []
        for record in pending:
            # Get old file from Sonarr
            old_file = None
            if record.sonarr_episode_file_id:
                logger.info(f"Fetching episode file {record.sonarr_episode_file_id} from Sonarr for upgrade {record.id}")
                old_file = sonarr.get_episode_file(record.sonarr_episode_file_id)
                if not old_file:
                    logger.warning(f"Failed to fetch episode file {record.sonarr_episode_file_id} from Sonarr - file may have been deleted")
            else:
                logger.warning(f"Record {record.id} has no sonarr_episode_file_id set - attempting to find file from episode data")
                # Try to find the file by getting episode info from Sonarr
                if record.source_id and record.season is not None and record.episode is not None:
                    episodes = sonarr.get_episodes(record.source_id)
                    # Find the matching episode
                    matching_episode = None
                    for ep in episodes:
                        if ep.get('seasonNumber') == record.season and ep.get('episodeNumber') == record.episode:
                            matching_episode = ep
                            break

                    if matching_episode and matching_episode.get('hasFile') and matching_episode.get('episodeFileId'):
                        episode_file_id = matching_episode['episodeFileId']
                        logger.info(f"Found episode file ID {episode_file_id} from episode data for S{record.season:02d}E{record.episode:02d}")
                        old_file = sonarr.get_episode_file(episode_file_id)
                        if old_file:
                            logger.info(f"Successfully fetched episode file using episode data")
                    else:
                        logger.warning(f"Could not find file for S{record.season:02d}E{record.episode:02d} in Sonarr")

            # Extract real metadata from both files
            old_metadata = None
            if old_file:
                old_filename = old_file.get('relativePath', '').split('/')[-1]
                old_path = old_file.get('path')  # Full path to file

                # Always parse filename to get source type (ffprobe can't detect this)
                old_parsed = parse_filename(old_filename)

                def convert_languages(lang_value):
                    if lang_value is None:
                        return []
                    if isinstance(lang_value, list):
                        return [str(lang) for lang in lang_value]
                    else:
                        return [str(lang_value)]

                # Try to extract real metadata from file
                if old_path:
                    logger.info(f"Extracting real metadata from old file: {old_path}")
                    real_metadata = extract_video_metadata(old_path)
                    if real_metadata:
                        formatted = format_metadata_for_display(real_metadata)
                        old_metadata = {
                            'filename': old_filename,
                            'size': old_file.get('size', 0),
                            'quality': formatted.get('resolution', 'Unknown'),
                            'codec': formatted.get('video_codec', 'Unknown'),
                            'source': old_parsed.get('source_type_normalized', 'Unknown'),  # From filename
                            'audio_languages': formatted.get('audio_languages', []),
                            'subtitles': formatted.get('subtitle_languages', []),
                        }
                        logger.info(f"Successfully extracted real metadata from old file (source from filename)")

                # Fallback to filename parsing if extraction failed
                if not old_metadata:
                    logger.warning(f"Falling back to filename parsing for old file: {old_filename}")
                    old_metadata = {
                        'filename': old_filename,
                        'size': old_file.get('size', 0),
                        'quality': old_parsed.get('screen_size', 'Unknown'),
                        'codec': old_parsed.get('video_codec_normalized', 'Unknown'),
                        'source': old_parsed.get('source_type_normalized', 'Unknown'),
                        'audio_languages': convert_languages(old_parsed.get('audio_languages')),
                        'subtitles': convert_languages(old_parsed.get('subtitle_languages')),
                    }

            # Extract real metadata from new file
            new_metadata = None

            # Always parse filename to get source type (ffprobe can't detect this)
            new_parsed = parse_filename(record.filename)

            def convert_languages_new(lang_value):
                if lang_value is None:
                    return []
                if isinstance(lang_value, list):
                    return [str(lang) for lang in lang_value]
                else:
                    return [str(lang_value)]

            # Find the downloaded file
            new_file_path = find_downloaded_file(record.pyload_package_id, record.filename)
            if new_file_path:
                logger.info(f"Extracting real metadata from new file: {new_file_path}")
                real_metadata = extract_video_metadata(new_file_path)
                if real_metadata:
                    formatted = format_metadata_for_display(real_metadata)
                    new_metadata = {
                        'filename': record.filename,
                        'size': record.file_size or formatted.get('file_size', 0),
                        'quality': formatted.get('resolution', 'Unknown'),
                        'codec': formatted.get('video_codec', 'Unknown'),
                        'source': new_parsed.get('source_type_normalized', 'Unknown'),  # From filename
                        'audio_languages': formatted.get('audio_languages', []),
                        'subtitles': formatted.get('subtitle_languages', []),
                    }
                    logger.info(f"Successfully extracted real metadata from new file (source from filename)")

            # Fallback to filename parsing if extraction failed
            if not new_metadata:
                logger.warning(f"Falling back to filename parsing for new file: {record.filename}")
                new_metadata = {
                    'filename': record.filename,
                    'size': record.file_size,
                    'quality': new_parsed.get('screen_size', 'Unknown'),
                    'codec': new_parsed.get('video_codec_normalized', 'Unknown'),
                    'source': new_parsed.get('source_type_normalized', 'Unknown'),
                    'audio_languages': convert_languages_new(new_parsed.get('audio_languages')),
                    'subtitles': convert_languages_new(new_parsed.get('subtitle_languages')),
                }

            # Format title
            episode_str = f"S{record.season:02d}E{record.episode:02d}"
            title = f"{record.item_title} - {episode_str}"

            # Determine download status
            is_downloading = record.download_completed_at is None
            download_status = 'downloading' if is_downloading else 'completed'

            results.append({
                'id': record.id,
                'title': title,
                'item_title': record.item_title,
                'season': record.season,
                'episode': record.episode,
                'current': old_metadata,
                'new': new_metadata,
                'download_status': download_status,
                'created_at': record.created_at.isoformat() if record.created_at else None
            })

        db.close()
        return jsonify({'upgrades': results}), 200

    except Exception as e:
        logger.error(f"Error getting pending upgrades (series): {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/pending-upgrades/movies', methods=['GET'])
def pending_upgrades_movies():
    """Get movie upgrades waiting for decision"""
    try:
        from services.radarr import get_client as get_radarr
        from services.parser import parse_filename
        from services.metadata_extractor import extract_video_metadata, format_metadata_for_display
        from services.file_mover import find_downloaded_file
        from models.database import DownloadHistory, get_db_session

        db = get_db_session()
        radarr = get_radarr()

        # Get upgrades waiting for decision (including downloading)
        pending = db.query(DownloadHistory).filter(
            DownloadHistory.source == 'radarr',
            DownloadHistory.is_upgrade == True,
            DownloadHistory.upgrade_decision.is_(None)
        ).all()

        results = []
        for record in pending:
            # Get old file from Radarr
            old_file = None
            if record.radarr_movie_file_id:
                logger.info(f"Fetching movie file {record.radarr_movie_file_id} from Radarr for upgrade {record.id}")
                old_file = radarr.get_movie_file(record.radarr_movie_file_id)
                if not old_file:
                    logger.warning(f"Failed to fetch movie file {record.radarr_movie_file_id} from Radarr - file may have been deleted")
            else:
                logger.warning(f"Record {record.id} has no radarr_movie_file_id set - attempting to find file from movie data")
                # Try to find the file by getting movie info from Radarr
                if record.source_id:
                    movie = radarr.get_movie_by_id(record.source_id)
                    if movie and movie.get('hasFile') and movie.get('movieFile'):
                        movie_file = movie['movieFile']
                        movie_file_id = movie_file.get('id')
                        if movie_file_id:
                            logger.info(f"Found movie file ID {movie_file_id} from movie data for {record.item_title}")
                            old_file = radarr.get_movie_file(movie_file_id)
                            if old_file:
                                logger.info(f"Successfully fetched movie file using movie data")
                        else:
                            # movie_file IS the file data
                            logger.info(f"Using movie file data directly from movie object")
                            old_file = movie_file
                    else:
                        logger.warning(f"Could not find file for movie {record.item_title} in Radarr")

            # Extract real metadata from both files
            old_metadata = None
            if old_file:
                old_filename = old_file.get('relativePath', '').split('/')[-1]
                old_path = old_file.get('path')  # Full path to file

                # Always parse filename to get source type (ffprobe can't detect this)
                old_parsed = parse_filename(old_filename)

                def convert_languages(lang_value):
                    if lang_value is None:
                        return []
                    if isinstance(lang_value, list):
                        return [str(lang) for lang in lang_value]
                    else:
                        return [str(lang_value)]

                # Try to extract real metadata from file
                if old_path:
                    logger.info(f"Extracting real metadata from old file: {old_path}")
                    real_metadata = extract_video_metadata(old_path)
                    if real_metadata:
                        formatted = format_metadata_for_display(real_metadata)
                        old_metadata = {
                            'filename': old_filename,
                            'size': old_file.get('size', 0),
                            'quality': formatted.get('resolution', 'Unknown'),
                            'codec': formatted.get('video_codec', 'Unknown'),
                            'source': old_parsed.get('source_type_normalized', 'Unknown'),  # From filename
                            'audio_languages': formatted.get('audio_languages', []),
                            'subtitles': formatted.get('subtitle_languages', []),
                        }
                        logger.info(f"Successfully extracted real metadata from old file (source from filename)")

                # Fallback to filename parsing if extraction failed
                if not old_metadata:
                    logger.warning(f"Falling back to filename parsing for old file: {old_filename}")
                    old_metadata = {
                        'filename': old_filename,
                        'size': old_file.get('size', 0),
                        'quality': old_parsed.get('screen_size', 'Unknown'),
                        'codec': old_parsed.get('video_codec_normalized', 'Unknown'),
                        'source': old_parsed.get('source_type_normalized', 'Unknown'),
                        'audio_languages': convert_languages(old_parsed.get('audio_languages')),
                        'subtitles': convert_languages(old_parsed.get('subtitle_languages')),
                    }

            # Extract real metadata from new file
            new_metadata = None

            # Always parse filename to get source type (ffprobe can't detect this)
            new_parsed = parse_filename(record.filename)

            def convert_languages_new(lang_value):
                if lang_value is None:
                    return []
                if isinstance(lang_value, list):
                    return [str(lang) for lang in lang_value]
                else:
                    return [str(lang_value)]

            # Find the downloaded file
            new_file_path = find_downloaded_file(record.pyload_package_id, record.filename)
            if new_file_path:
                logger.info(f"Extracting real metadata from new file: {new_file_path}")
                real_metadata = extract_video_metadata(new_file_path)
                if real_metadata:
                    formatted = format_metadata_for_display(real_metadata)
                    new_metadata = {
                        'filename': record.filename,
                        'size': record.file_size or formatted.get('file_size', 0),
                        'quality': formatted.get('resolution', 'Unknown'),
                        'codec': formatted.get('video_codec', 'Unknown'),
                        'source': new_parsed.get('source_type_normalized', 'Unknown'),  # From filename
                        'audio_languages': formatted.get('audio_languages', []),
                        'subtitles': formatted.get('subtitle_languages', []),
                    }
                    logger.info(f"Successfully extracted real metadata from new file (source from filename)")

            # Fallback to filename parsing if extraction failed
            if not new_metadata:
                logger.warning(f"Falling back to filename parsing for new file: {record.filename}")
                new_metadata = {
                    'filename': record.filename,
                    'size': record.file_size,
                    'quality': new_parsed.get('screen_size', 'Unknown'),
                    'codec': new_parsed.get('video_codec_normalized', 'Unknown'),
                    'source': new_parsed.get('source_type_normalized', 'Unknown'),
                    'audio_languages': convert_languages_new(new_parsed.get('audio_languages')),
                    'subtitles': convert_languages_new(new_parsed.get('subtitle_languages')),
                }

            # Format title
            title = f"{record.item_title} ({record.year})" if record.year else record.item_title

            # Determine download status
            is_downloading = record.download_completed_at is None
            download_status = 'downloading' if is_downloading else 'completed'

            results.append({
                'id': record.id,
                'title': title,
                'item_title': record.item_title,
                'year': record.year,
                'current': old_metadata,
                'new': new_metadata,
                'download_status': download_status,
                'created_at': record.created_at.isoformat() if record.created_at else None
            })

        db.close()
        return jsonify({'upgrades': results}), 200

    except Exception as e:
        logger.error(f"Error getting pending upgrades (movies): {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/search-upgrade', methods=['POST'])
def search_upgrade():
    """Search for better version and return results for user selection"""
    try:
        from services.sonarr import get_client as get_sonarr
        from services.radarr import get_client as get_radarr
        from services.search import search_for_item, create_pending_confirmation

        data = request.get_json()
        source = data.get('source')  # 'sonarr' or 'radarr'

        if source == 'sonarr':
            series_id = data.get('series_id')
            season = data.get('season')
            episode = data.get('episode')
            episode_file_id = data.get('episode_file_id')

            # Check if upgrade already exists for this episode
            db = get_db_session()
            try:
                existing_upgrade = db.query(DownloadHistory).filter(
                    DownloadHistory.source == 'sonarr',
                    DownloadHistory.source_id == series_id,
                    DownloadHistory.season == season,
                    DownloadHistory.episode == episode,
                    DownloadHistory.is_upgrade == True,
                    DownloadHistory.upgrade_decision.is_(None)
                ).first()

                if existing_upgrade:
                    return jsonify({
                        'error': 'Upgrade already pending for this episode',
                        'existing_upgrade_id': existing_upgrade.id
                    }), 409
            finally:
                db.close()

            sonarr = get_sonarr()
            series = sonarr.get_series_by_id(series_id)

            if not series:
                return jsonify({'error': 'Series not found'}), 404

            # Get current file metadata
            current_file_metadata = None
            if episode_file_id:
                from services.parser import parse_filename
                from services.metadata_extractor import extract_video_metadata, format_metadata_for_display

                episode_file = sonarr.get_episode_file(episode_file_id)
                if episode_file:
                    filename = episode_file.get('relativePath', '').split('/')[-1]
                    file_path = episode_file.get('path')  # Full path to file

                    # Always parse filename to get source type (ffprobe can't detect this)
                    parsed = parse_filename(filename)

                    def convert_languages(lang_value):
                        if lang_value is None:
                            return []
                        if isinstance(lang_value, list):
                            return [str(lang) for lang in lang_value]
                        else:
                            return [str(lang_value)]

                    # Try to extract real metadata from file
                    if file_path:
                        logger.info(f"Extracting metadata from current file: {file_path}")
                        real_metadata = extract_video_metadata(file_path)
                        if real_metadata:
                            formatted = format_metadata_for_display(real_metadata)
                            current_file_metadata = {
                                'filename': filename,
                                'quality': formatted.get('resolution', 'Unknown'),
                                'codec': formatted.get('video_codec', 'Unknown'),
                                'source': parsed.get('source_type_normalized', 'Unknown'),  # From filename
                                'audio_languages': formatted.get('audio_languages', []),
                                'subtitle_languages': formatted.get('subtitle_languages', []),
                                'size': episode_file.get('size', 0)
                            }
                            logger.info(f"Successfully extracted real metadata from current file (source from filename)")

                    # Fallback to filename parsing if extraction failed
                    if not current_file_metadata:
                        logger.warning(f"Falling back to filename parsing for current file: {filename}")
                        current_file_metadata = {
                            'filename': filename,
                            'quality': parsed.get('screen_size', 'Unknown'),
                            'codec': parsed.get('video_codec_normalized', 'Unknown'),
                            'source': parsed.get('source_type_normalized', 'Unknown'),
                            'audio_languages': convert_languages(parsed.get('audio_languages')),
                            'subtitle_languages': convert_languages(parsed.get('subtitle_languages')),
                            'size': episode_file.get('size', 0)
                        }

            # Create search query
            item_info = {
                'source': 'sonarr',
                'series_id': series_id,
                'series_title': series['title'],
                'season': season,
                'episode': episode
            }

            # Search for better version (uses existing scoring system from services/search.py)
            results = search_for_item(item_info, top_n=10)

            if not results:
                return jsonify({
                    'success': True,
                    'results_count': 0,
                    'results': [],
                    'message': 'No results found'
                }), 200

            # Create pending confirmation with upgrade metadata
            pending_id = create_pending_confirmation(item_info, results)

            # Store upgrade-specific metadata in pending confirmation
            if pending_id:
                db = get_db_session()
                try:
                    pending = db.query(PendingConfirmation).filter(
                        PendingConfirmation.id == pending_id
                    ).first()
                    if pending:
                        pending.destination_path = series.get('path', '')
                        # Store upgrade metadata in pending confirmation
                        # We'll add these fields when downloading
                        db.commit()
                finally:
                    db.close()

            return jsonify({
                'success': True,
                'pending_id': pending_id,
                'results_count': len(results),
                'results': results,
                'current_file': current_file_metadata,
                'upgrade_metadata': {
                    'episode_file_id': episode_file_id,
                    'is_upgrade': True
                }
            }), 200

        elif source == 'radarr':
            movie_id = data.get('movie_id')
            movie_file_id = data.get('movie_file_id')

            # Check if upgrade already exists for this movie
            db = get_db_session()
            try:
                existing_upgrade = db.query(DownloadHistory).filter(
                    DownloadHistory.source == 'radarr',
                    DownloadHistory.source_id == movie_id,
                    DownloadHistory.is_upgrade == True,
                    DownloadHistory.upgrade_decision.is_(None)
                ).first()

                if existing_upgrade:
                    return jsonify({
                        'error': 'Upgrade already pending for this movie',
                        'existing_upgrade_id': existing_upgrade.id
                    }), 409
            finally:
                db.close()

            radarr = get_radarr()
            movie = radarr.get_movie_by_id(movie_id)

            if not movie:
                return jsonify({'error': 'Movie not found'}), 404

            # Create search query
            item_info = {
                'source': 'radarr',
                'movie_id': movie_id,
                'title': movie['title'],
                'year': movie.get('year')
            }

            # Search for better version
            results = search_for_item(item_info, top_n=10)

            if not results:
                return jsonify({
                    'success': True,
                    'results_count': 0,
                    'results': [],
                    'message': 'No results found'
                }), 200

            # Create pending confirmation with upgrade metadata
            pending_id = create_pending_confirmation(item_info, results)

            # Store upgrade-specific metadata
            if pending_id:
                db = get_db_session()
                try:
                    pending = db.query(PendingConfirmation).filter(
                        PendingConfirmation.id == pending_id
                    ).first()
                    if pending:
                        pending.destination_path = movie.get('path', '')
                        db.commit()
                finally:
                    db.close()

            return jsonify({
                'success': True,
                'pending_id': pending_id,
                'results_count': len(results),
                'results': results,
                'upgrade_metadata': {
                    'movie_file_id': movie_file_id,
                    'is_upgrade': True
                }
            }), 200
        else:
            return jsonify({'error': 'Invalid source'}), 400

    except Exception as e:
        logger.error(f"Error in search-upgrade: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/confirm-upgrade', methods=['POST'])
def confirm_upgrade():
    """Confirm upgrade decision and execute action"""
    try:
        from services.sonarr import get_client as get_sonarr
        from services.radarr import get_client as get_radarr
        from services.file_mover import construct_destination_path, find_downloaded_file
        from models.database import DownloadHistory, get_db_session
        from datetime import datetime
        from pathlib import Path
        import shutil
        import os

        data = request.get_json()
        # Accept both upgrade_id and record_id for compatibility
        record_id = data.get('upgrade_id') or data.get('record_id')
        action = data.get('action')  # 'use_new', 'keep_old', 'keep_both'

        if action not in ['use_new', 'keep_old', 'keep_both']:
            return jsonify({'status': 'error', 'message': 'Invalid action'}), 400

        db = get_db_session()
        record = db.query(DownloadHistory).filter_by(id=record_id).first()

        if not record:
            db.close()
            return jsonify({'status': 'error', 'message': 'Record not found'}), 404

        if not record.is_upgrade:
            db.close()
            return jsonify({'status': 'error', 'message': 'Not an upgrade record'}), 400

        # Execute action
        if action == 'use_new':
            # Move new file to destination and delete old file
            dest_path = construct_destination_path(record)
            source_path = find_downloaded_file(record.pyload_package_id, record.filename)

            if not source_path:
                db.close()
                return jsonify({'status': 'error', 'message': 'New file not found in pyLoad directory'}), 404

            # Move new file FIRST (before deleting old one)
            try:
                dest_dir = Path(dest_path).parent
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, dest_path)
                logger.info(f"New file copied to destination: {dest_path}")
                os.remove(source_path)
                logger.info(f"New file removed from pyLoad directory: {source_path}")
            except Exception as e:
                db.close()
                logger.error(f"Failed to move new file: {str(e)}", exc_info=True)
                return jsonify({'status': 'error', 'message': f'Failed to move new file: {str(e)}'}), 500

            # Delete old file from Sonarr/Radarr AFTER new file is successfully moved
            if record.source == 'sonarr' and record.sonarr_episode_file_id:
                sonarr = get_sonarr()
                delete_success = sonarr.delete_episode_file(record.sonarr_episode_file_id)
                if delete_success:
                    logger.info(f"Old episode file {record.sonarr_episode_file_id} deleted from Sonarr")
                else:
                    logger.warning(f"Failed to delete old episode file {record.sonarr_episode_file_id} from Sonarr")
            elif record.source == 'radarr' and record.radarr_movie_file_id:
                radarr = get_radarr()
                delete_success = radarr.delete_movie_file(record.radarr_movie_file_id)
                if delete_success:
                    logger.info(f"Old movie file {record.radarr_movie_file_id} deleted from Radarr")
                else:
                    logger.warning(f"Failed to delete old movie file {record.radarr_movie_file_id} from Radarr")

            # Update record
            record.file_moved_at = datetime.utcnow()
            record.final_path = dest_path
            record.upgrade_decision = 'use_new'

        elif action == 'keep_old':
            # Delete new file from pyLoad directory
            logger.info(f"Keep old action: Looking for new file to delete. Package ID: {record.pyload_package_id}, Filename: {record.filename}")
            source_path = find_downloaded_file(record.pyload_package_id, record.filename)

            if not source_path:
                logger.warning(f"New file not found by find_downloaded_file(). Package ID: {record.pyload_package_id}, Filename: {record.filename}")
                # Update record even if file not found (might have been manually deleted)
                record.upgrade_decision = 'keep_old'
            elif not Path(source_path).exists():
                logger.warning(f"New file path returned but file doesn't exist: {source_path}")
                # Update record even if file doesn't exist
                record.upgrade_decision = 'keep_old'
            else:
                # File found and exists, delete it
                try:
                    logger.info(f"Attempting to delete new file: {source_path}")
                    os.remove(source_path)
                    logger.info(f"Successfully deleted new file from pyLoad directory: {source_path}")
                    record.upgrade_decision = 'keep_old'
                except PermissionError as e:
                    error_msg = f"Permission denied when deleting file {source_path}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    db.close()
                    return jsonify({'status': 'error', 'message': error_msg}), 500
                except Exception as e:
                    error_msg = f"Failed to delete new file {source_path}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    db.close()
                    return jsonify({'status': 'error', 'message': error_msg}), 500

        elif action == 'keep_both':
            # Move new file with suffix
            dest_path = construct_destination_path(record)
            source_path = find_downloaded_file(record.pyload_package_id, record.filename)

            if not source_path:
                db.close()
                return jsonify({'status': 'error', 'message': 'New file not found in pyLoad directory'}), 404

            # Add suffix to filename
            path_obj = Path(dest_path)
            dest_path_v2 = str(path_obj.parent / f"{path_obj.stem}_v2{path_obj.suffix}")

            # Move new file
            try:
                dest_dir = Path(dest_path_v2).parent
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, dest_path_v2)
                logger.info(f"New file copied to destination with v2 suffix: {dest_path_v2}")
                os.remove(source_path)
                logger.info(f"New file removed from pyLoad directory: {source_path}")
            except Exception as e:
                db.close()
                logger.error(f"Failed to move new file: {str(e)}", exc_info=True)
                return jsonify({'status': 'error', 'message': f'Failed to move new file: {str(e)}'}), 500

            # Update record
            record.file_moved_at = datetime.utcnow()
            record.final_path = dest_path_v2
            record.upgrade_decision = 'keep_both'

        db.commit()
        db.close()

        return jsonify({
            'status': 'success',
            'action': action,
            'message': f'Upgrade decision "{action}" executed successfully'
        }), 200

    except Exception as e:
        logger.error(f"Error in confirm-upgrade: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

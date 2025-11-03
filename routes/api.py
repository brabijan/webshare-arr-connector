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

            # Add to pyLoad
            success, message, package_id = pyload.add_to_pyload(direct_link, package_name)

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
                pyload_package_id=package_id,
                status='sent'
            )

            db.add(history)
            db.commit()

            logger.info(f"Confirmed download for pending ID {pending_id}, pyLoad package: {package_id}")

            return jsonify({
                'success': True,
                'pending_id': pending_id,
                'package_id': package_id,
                'package_name': package_name,
                'filename': selected_result['name'],
                'message': message
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


@api_bp.route('/fetch-missing', methods=['POST'])
def fetch_missing():
    """
    Fetch missing items from Sonarr/Radarr and create pending confirmations

    POST body:
    {
        "source": "sonarr" or "radarr",
        "limit": 10  // Optional, default 10
    }
    """
    try:
        data = request.json or {}
        source = data.get('source', 'sonarr')
        limit = data.get('limit', 10)

        if source not in ['sonarr', 'radarr']:
            return jsonify({'error': 'Invalid source, must be sonarr or radarr'}), 400

        logger.info(f"Fetching missing items from {source} (limit={limit})")

        # Use search service to fetch and process missing items
        pending_ids = search.search_missing_items(source=source, limit=limit)

        return jsonify({
            'success': True,
            'source': source,
            'pending_count': len(pending_ids),
            'pending_ids': pending_ids,
            'message': f'Created {len(pending_ids)} pending confirmations from {source}'
        }), 200

    except Exception as e:
        logger.error(f"Error fetching missing items: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

"""Webhook endpoints for Sonarr/Radarr"""
from flask import Blueprint, request, jsonify
import logging
from services import sonarr, radarr, search

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/webhook')


@webhooks_bp.route('/sonarr', methods=['POST'])
def sonarr_webhook():
    """
    Handle Sonarr webhooks

    Expected events: Grab, Download
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        event_type = data.get('eventType')
        logger.info(f"Received Sonarr webhook: {event_type}")

        # Only process Grab and Download events
        if event_type not in ['Grab', 'Download']:
            return jsonify({'status': 'ignored', 'reason': f'Event type {event_type} not handled'}), 200

        # Parse webhook data
        sonarr_client = sonarr.get_client()
        item_info = sonarr_client.parse_webhook(data)

        if not item_info:
            return jsonify({'error': 'Failed to parse webhook data'}), 400

        # Search for files on Webshare
        results = search.search_for_item(item_info, top_n=5)

        if not results:
            logger.warning(f"No results found for {item_info.get('series_title')} S{item_info.get('season'):02d}E{item_info.get('episode'):02d}")
            return jsonify({
                'status': 'no_results',
                'message': 'No files found on Webshare'
            }), 200

        # Create pending confirmation
        pending_id = search.create_pending_confirmation(item_info, results)

        if not pending_id:
            return jsonify({'error': 'Failed to create pending confirmation'}), 500

        return jsonify({
            'status': 'success',
            'pending_id': pending_id,
            'results_count': len(results),
            'message': f'Found {len(results)} results, awaiting confirmation'
        }), 200

    except Exception as e:
        logger.error(f"Error processing Sonarr webhook: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@webhooks_bp.route('/radarr', methods=['POST'])
def radarr_webhook():
    """
    Handle Radarr webhooks

    Expected events: Grab, Download
    """
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        event_type = data.get('eventType')
        logger.info(f"Received Radarr webhook: {event_type}")

        # Only process Grab and Download events
        if event_type not in ['Grab', 'Download']:
            return jsonify({'status': 'ignored', 'reason': f'Event type {event_type} not handled'}), 200

        # Parse webhook data
        radarr_client = radarr.get_client()
        item_info = radarr_client.parse_webhook(data)

        if not item_info:
            return jsonify({'error': 'Failed to parse webhook data'}), 400

        # Search for files on Webshare
        results = search.search_for_item(item_info, top_n=5)

        if not results:
            logger.warning(f"No results found for {item_info.get('title')} ({item_info.get('year')})")
            return jsonify({
                'status': 'no_results',
                'message': 'No files found on Webshare'
            }), 200

        # Create pending confirmation
        pending_id = search.create_pending_confirmation(item_info, results)

        if not pending_id:
            return jsonify({'error': 'Failed to create pending confirmation'}), 500

        return jsonify({
            'status': 'success',
            'pending_id': pending_id,
            'results_count': len(results),
            'message': f'Found {len(results)} results, awaiting confirmation'
        }), 200

    except Exception as e:
        logger.error(f"Error processing Radarr webhook: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

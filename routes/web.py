"""Web UI routes"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
import logging
from models.database import PendingConfirmation, DownloadHistory, get_db_session
from services import webshare, pyload
from datetime import datetime

logger = logging.getLogger(__name__)

web_bp = Blueprint('web', __name__)


@web_bp.route('/')
def index():
    """Main page with series/movies navigation"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error loading index: {e}", exc_info=True)
        return render_template('index.html', error=str(e))


@web_bp.route('/series/<int:series_id>/seasons')
def series_seasons(series_id):
    """Show seasons for a series"""
    try:
        from services import sonarr
        sonarr_client = sonarr.get_client()

        # Get series info from Sonarr
        all_series = sonarr_client.get_all_series()
        series = next((s for s in all_series if s.get('id') == series_id), None)

        if not series:
            flash('Series not found', 'error')
            return redirect(url_for('web.index'))

        # Find poster image
        poster_url = None
        for image in series.get('images', []):
            if image.get('coverType') == 'poster':
                poster_url = image.get('remoteUrl') or image.get('url')
                break

        series_data = {
            'id': series.get('id'),
            'title': series.get('title'),
            'year': series.get('year'),
            'path': series.get('path'),
            'poster_url': poster_url
        }

        return render_template('series_seasons.html', series=series_data)

    except Exception as e:
        logger.error(f"Error loading seasons: {e}", exc_info=True)
        flash(f'Error loading seasons: {str(e)}', 'error')
        return redirect(url_for('web.index'))


@web_bp.route('/series/<int:series_id>/season/<int:season_num>')
def season_episodes(series_id, season_num):
    """Show episodes for a season"""
    try:
        from services import sonarr
        sonarr_client = sonarr.get_client()

        # Get series info from Sonarr
        all_series = sonarr_client.get_all_series()
        series = next((s for s in all_series if s.get('id') == series_id), None)

        if not series:
            flash('Series not found', 'error')
            return redirect(url_for('web.index'))

        # Find poster image
        poster_url = None
        for image in series.get('images', []):
            if image.get('coverType') == 'poster':
                poster_url = image.get('remoteUrl') or image.get('url')
                break

        series_data = {
            'id': series.get('id'),
            'title': series.get('title'),
            'year': series.get('year'),
            'path': series.get('path'),
            'poster_url': poster_url
        }

        return render_template('season_episodes.html', series=series_data, season_number=season_num)

    except Exception as e:
        logger.error(f"Error loading episodes: {e}", exc_info=True)
        flash(f'Error loading episodes: {str(e)}', 'error')
        return redirect(url_for('web.index'))


@web_bp.route('/download', methods=['POST'])
def download():
    """Handle download confirmation from web form"""
    try:
        pending_id = request.form.get('pending_id', type=int)
        result_index = request.form.get('result_index', type=int)

        if not pending_id or result_index is None:
            flash('Invalid request', 'error')
            return redirect(url_for('web.index'))

        db = get_db_session()
        try:
            # Get pending item
            pending = db.query(PendingConfirmation).filter(
                PendingConfirmation.id == pending_id
            ).first()

            if not pending or pending.status != 'pending':
                flash('Pending item not found or already processed', 'error')
                return redirect(url_for('web.index'))

            results = pending.results

            if result_index >= len(results):
                flash('Invalid selection', 'error')
                return redirect(url_for('web.index'))

            selected_result = results[result_index]

            # Get direct link
            ws_client = webshare.get_client()
            direct_link, error = ws_client.get_direct_link(selected_result['ident'])

            if error:
                flash(f'Failed to get direct link: {error}', 'error')
                return redirect(url_for('web.index'))

            # Generate package name
            if pending.source == 'sonarr':
                package_name = f"{pending.item_title} - S{pending.season:02d}E{pending.episode:02d}"
            else:
                package_name = f"{pending.item_title} ({pending.year})"

            # Get destination path
            destination_path = pending.destination_path

            # Add to pyLoad with destination path
            success, message, package_id = pyload.add_to_pyload(
                direct_link,
                package_name,
                destination_path=destination_path
            )

            if not success:
                flash(f'Failed to add to pyLoad: {message}', 'error')
                return redirect(url_for('web.index'))

            # Update pending confirmation
            pending.status = 'confirmed'
            pending.selected_index = result_index
            pending.confirmed_at = datetime.utcnow()

            # Create history entry
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

            flash(f'Successfully sent to pyLoad: {message}', 'success')
            return redirect(url_for('web.index'))

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error processing download: {e}", exc_info=True)
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('web.index'))


@web_bp.route('/history')
def history():
    """Show download history"""
    try:
        limit = request.args.get('limit', 50, type=int)

        db = get_db_session()
        try:
            history_items = db.query(DownloadHistory).order_by(
                DownloadHistory.created_at.desc()
            ).limit(limit).all()

            return render_template('history.html', history_items=history_items)

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error loading history: {e}", exc_info=True)
        return render_template('history.html', history_items=[], error=str(e))


@web_bp.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'ok'}, 200

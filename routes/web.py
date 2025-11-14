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
    """Redirect to library (home page)"""
    return redirect('/library')


@web_bp.route('/pending-downloads')
def pending_downloads_page():
    """Pending downloads page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error loading pending downloads: {e}", exc_info=True)
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
            return redirect(url_for('web.pending_downloads_page'))

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
        return redirect(url_for('web.pending_downloads_page'))


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
            return redirect(url_for('web.pending_downloads_page'))

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
        return redirect(url_for('web.pending_downloads_page'))


@web_bp.route('/download', methods=['POST'])
def download():
    """Handle download confirmation from web form"""
    try:
        pending_id = request.form.get('pending_id', type=int)
        result_index = request.form.get('result_index', type=int)

        if not pending_id or result_index is None:
            flash('Invalid request', 'error')
            return redirect(url_for('web.pending_downloads_page'))

        db = get_db_session()
        try:
            # Get pending item
            pending = db.query(PendingConfirmation).filter(
                PendingConfirmation.id == pending_id
            ).first()

            if not pending or pending.status != 'pending':
                flash('Pending item not found or already processed', 'error')
                return redirect(url_for('web.pending_downloads_page'))

            results = pending.results

            if result_index >= len(results):
                flash('Invalid selection', 'error')
                return redirect(url_for('web.pending_downloads_page'))

            selected_result = results[result_index]

            # Get direct link
            ws_client = webshare.get_client()
            direct_link, error = ws_client.get_direct_link(selected_result['ident'])

            if error:
                flash(f'Failed to get direct link: {error}', 'error')
                return redirect(url_for('web.pending_downloads_page'))

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
                return redirect(url_for('web.pending_downloads_page'))

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
            return redirect(url_for('web.pending_downloads_page'))

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error processing download: {e}", exc_info=True)
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('web.pending_downloads_page'))


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


@web_bp.route('/library')
def library():
    """Library page - completed downloads"""
    return render_template('library.html')


@web_bp.route('/library/series/<int:series_id>/seasons')
def library_series_seasons(series_id):
    """Series seasons in library"""
    try:
        from services import sonarr
        sonarr_client = sonarr.get_client()

        # Get series info from Sonarr by ID (works for all series, regardless of monitoring status)
        series = sonarr_client.get_series_by_id(series_id)

        if not series:
            flash('Series not found', 'error')
            return redirect(url_for('web.library'))

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

        return render_template('library_seasons.html', series_id=series_id, series=series_data)

    except Exception as e:
        logger.error(f"Error loading library seasons: {e}", exc_info=True)
        flash(f'Error loading seasons: {str(e)}', 'error')
        return redirect(url_for('web.library'))


@web_bp.route('/library/series/<int:series_id>/season/<int:season_num>')
def library_season_detail(series_id, season_num):
    """Season episodes in library"""
    try:
        from services import sonarr
        sonarr_client = sonarr.get_client()

        # Get series info from Sonarr
        series = sonarr_client.get_series_by_id(series_id)

        if not series:
            flash('Series not found', 'error')
            return redirect(url_for('web.library'))

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

        return render_template('library_season.html', series=series_data, season_number=season_num)

    except Exception as e:
        logger.error(f"Error loading library season detail: {e}", exc_info=True)
        flash(f'Error loading season: {str(e)}', 'error')
        return redirect(url_for('web.library'))


@web_bp.route('/library/movies')
def library_movies():
    """Movies in library"""
    return render_template('library_movies.html')


@web_bp.route('/library/movies/<int:movie_id>')
def library_movie_detail(movie_id):
    """Movie detail in library"""
    try:
        from services import radarr
        radarr_client = radarr.get_client()

        # Get movie info from Radarr
        movie = radarr_client.get_movie_by_id(movie_id)

        if not movie:
            flash('Movie not found', 'error')
            return redirect(url_for('web.library'))

        # Find poster image
        poster_url = None
        for image in movie.get('images', []):
            if image.get('coverType') == 'poster':
                poster_url = image.get('remoteUrl') or image.get('url')
                break

        movie_data = {
            'id': movie.get('id'),
            'title': movie.get('title'),
            'year': movie.get('year'),
            'path': movie.get('path'),
            'poster_url': poster_url
        }

        return render_template('library_movie_detail.html', movie_id=movie_id, movie=movie_data)

    except Exception as e:
        logger.error(f"Error loading library movie detail: {e}", exc_info=True)
        flash(f'Error loading movie: {str(e)}', 'error')
        return redirect(url_for('web.library'))


@web_bp.route('/pending-upgrades')
def pending_upgrades():
    """Pending upgrades page"""
    return render_template('pending_upgrades.html')


@web_bp.route('/health')
def health():
    """Health check endpoint"""
    return {'status': 'ok'}, 200

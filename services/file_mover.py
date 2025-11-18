"""File mover service for moving completed downloads to destination"""
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path
from models.database import DownloadHistory, get_db_session
from services import pyload
import config

logger = logging.getLogger(__name__)


def construct_destination_path(record):
    """
    Construct full destination path for a download record

    Args:
        record: DownloadHistory record

    Returns:
        str: Full path where file should be moved
    """
    if not record.destination_path:
        logger.warning(f"No destination_path for record {record.id}")
        return None

    base_path = Path(record.destination_path)

    # For TV shows, add season folder
    if record.source == 'sonarr' and record.season is not None:
        season_folder = f"Season {record.season}"
        full_path = base_path / season_folder / record.filename
    else:
        # For movies, just use base path + filename
        full_path = base_path / record.filename

    return str(full_path)


def find_downloaded_file(package_id, expected_filename):
    """
    Find downloaded file in pyLoad download directory

    Args:
        package_id: pyLoad package ID
        expected_filename: Expected filename

    Returns:
        str: Path to downloaded file, or None if not found
    """
    try:
        pyload_dir = Path(config.PYLOAD_DOWNLOAD_DIR)

        if not pyload_dir.exists():
            logger.error(f"pyLoad download directory does not exist: {pyload_dir}")
            return None

        # Try to find file directly
        direct_path = pyload_dir / expected_filename
        if direct_path.exists():
            logger.info(f"Found file directly: {direct_path}")
            return str(direct_path)

        # Try to find in subdirectories (pyLoad might create package folders)
        for root, dirs, filenames in os.walk(pyload_dir):
            if expected_filename in filenames:
                found_path = Path(root) / expected_filename
                logger.info(f"Found file in subdirectory: {found_path}")
                return str(found_path)

        logger.warning(f"File not found in pyLoad directory: {expected_filename}")
        logger.debug(f"Searched in: {pyload_dir}")
        return None

    except Exception as e:
        logger.error(f"Error finding downloaded file: {str(e)}")
        return None


def move_completed_file(record, db):
    """
    Move a completed download to its destination

    Args:
        record: DownloadHistory record
        db: Database session

    Returns:
        tuple: (success, error_message)
    """
    try:
        # Check if pyLoad package is finished
        if not record.pyload_package_id:
            return False, "No pyLoad package ID"

        # Skip automatic move for upgrade downloads - wait for user decision
        if record.is_upgrade:
            logger.info(f"Skipping automatic move for upgrade download (record {record.id}) - waiting for user decision")
            # Mark as download completed but don't move
            if not record.download_completed_at:
                record.download_completed_at = datetime.utcnow()
                db.commit()
            return False, "Upgrade waiting for user decision"

        # Construct destination path first (to check if file already exists)
        dest_path = construct_destination_path(record)
        if not dest_path:
            return False, "Could not construct destination path"

        # Check if package still exists in pyLoad
        is_finished = pyload.is_package_finished(record.pyload_package_id)

        # If package doesn't exist in pyLoad anymore, check if file was already moved
        if is_finished is None or is_finished is False:
            # Check if file already exists at destination (might have been moved already)
            if Path(dest_path).exists():
                logger.info(f"Package {record.pyload_package_id} not found in pyLoad, but file exists at destination - marking as complete")
                # Mark as completed
                if not record.download_completed_at:
                    record.download_completed_at = datetime.utcnow()
                record.file_moved_at = datetime.utcnow()
                record.final_path = dest_path
                record.move_error = None
                db.commit()
                logger.info(f"Marked record {record.id} as completed (file already at destination)")
                return True, None
            else:
                # Package not finished and file not at destination - still downloading
                if is_finished is False:
                    logger.debug(f"Package {record.pyload_package_id} not finished yet")
                    return False, "Download not finished yet"
                else:
                    # Package doesn't exist in pyLoad and file not at destination - error
                    error_msg = f"Package {record.pyload_package_id} not found in pyLoad and file not at destination"
                    logger.warning(error_msg)
                    return False, error_msg

        # Update download_completed_at if not set
        if not record.download_completed_at:
            record.download_completed_at = datetime.utcnow()
            db.commit()
            logger.info(f"Marked package {record.pyload_package_id} as completed")

        # Find downloaded file in pyLoad directory
        source_path = find_downloaded_file(record.pyload_package_id, record.filename)
        if not source_path:
            return False, f"Downloaded file not found: {record.filename}"

        # Verify source file still exists (might have been moved by another process)
        if not Path(source_path).exists():
            # Check if file already exists at destination
            if Path(dest_path).exists():
                logger.warning(f"Source file gone but destination exists - assuming already moved: {dest_path}")
            else:
                return False, f"Source file disappeared: {source_path}"

        # Create destination directory if needed
        dest_dir = Path(dest_path).parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured destination directory exists: {dest_dir}")

        # Move file (handles cross-device moves automatically)
        if Path(source_path).exists():
            logger.info(f"Moving file from {source_path} to {dest_path}")
            try:
                # Use copy2 + remove for cross-device compatibility
                shutil.copy2(source_path, dest_path)
                os.remove(source_path)
                logger.info(f"File moved successfully: {dest_path}")
            except Exception as move_error:
                # If copy succeeded but remove failed, that's ok
                if Path(dest_path).exists() and not Path(source_path).exists():
                    logger.warning(f"File copied but source cleanup had error: {move_error}")
                else:
                    raise
        else:
            logger.warning(f"Source file already moved, skipping move operation")

        # Update database - commit BEFORE trying to delete package
        record.file_moved_at = datetime.utcnow()
        record.final_path = dest_path
        record.move_error = None
        db.commit()

        # Trigger rescan in Sonarr/Radarr/Plex (non-critical)
        try:
            rescan_triggered = False

            # Trigger Sonarr rescan for TV shows
            if record.source == 'sonarr' and record.source_id:
                from services.sonarr import get_client as get_sonarr
                logger.info(f"Triggering Sonarr rescan for series ID {record.source_id}")
                sonarr = get_sonarr()
                rescan_triggered = sonarr.trigger_series_rescan(record.source_id)
                if rescan_triggered:
                    logger.info(f"Successfully triggered Sonarr rescan for series {record.source_id}")
                else:
                    logger.warning(f"Sonarr rescan returned False for series {record.source_id}")

            # Trigger Radarr rescan for movies
            elif record.source == 'radarr' and record.source_id:
                from services.radarr import get_client as get_radarr
                logger.info(f"Triggering Radarr rescan for movie ID {record.source_id}")
                radarr = get_radarr()
                rescan_triggered = radarr.trigger_movie_rescan(record.source_id)
                if rescan_triggered:
                    logger.info(f"Successfully triggered Radarr rescan for movie {record.source_id}")
                else:
                    logger.warning(f"Radarr rescan returned False for movie {record.source_id}")

            # Trigger Plex library scan (if configured)
            if config.PLEX_URL and config.PLEX_TOKEN:
                from services.plex import get_client as get_plex
                logger.info(f"Triggering Plex library scan for path: {dest_path}")
                plex = get_plex()
                plex_success = plex.trigger_library_scan(dest_path)
                if plex_success:
                    logger.info(f"Successfully triggered Plex library scan")
                else:
                    logger.warning(f"Plex library scan returned False")
            else:
                logger.debug(f"Plex not configured (PLEX_URL={bool(config.PLEX_URL)}, PLEX_TOKEN={bool(config.PLEX_TOKEN)}), skipping Plex scan")

            # Mark rescan as requested in database
            record.rescan_requested_at = datetime.utcnow()
            db.commit()
            logger.info(f"Rescan completed and marked in database at {record.rescan_requested_at}")

        except Exception as e:
            logger.warning(f"Error triggering rescan (non-critical): {str(e)}", exc_info=True)
            # Don't fail the overall file move operation

        # Try to delete package from pyLoad (non-critical if it fails)
        try:
            pyload.delete_package(record.pyload_package_id)
            logger.info(f"Deleted package {record.pyload_package_id} from pyLoad")
        except Exception as e:
            logger.warning(f"Could not delete package {record.pyload_package_id}: {e} (non-critical)")

        return True, None

    except Exception as e:
        error_msg = f"Error moving file: {str(e)}"
        logger.error(error_msg, exc_info=True)

        # Update error in database
        try:
            record.move_error = error_msg
            db.commit()
        except Exception as db_error:
            logger.error(f"Could not save error to database: {db_error}")

        return False, error_msg


def process_completed_downloads():
    """
    Main function to process all completed downloads
    This is called by the scheduler every N minutes
    """
    logger.info("Starting file mover process")

    try:
        db = get_db_session()

        # Find all records that need processing:
        # - status='sent' (successfully sent to pyLoad)
        # - pyload_package_id is set
        # - file_moved_at is NULL (not yet moved)
        pending_records = db.query(DownloadHistory).filter(
            DownloadHistory.status == 'sent',
            DownloadHistory.pyload_package_id.isnot(None),
            DownloadHistory.file_moved_at.is_(None)
        ).all()

        if not pending_records:
            logger.debug("No pending downloads to process")
            db.close()
            return

        logger.info(f"Found {len(pending_records)} downloads to check")

        processed = 0
        failed = 0

        for record in pending_records:
            logger.info(f"Processing record {record.id}: {record.item_title} - {record.filename}")

            success, error = move_completed_file(record, db)

            if success:
                processed += 1
                logger.info(f"Successfully processed record {record.id}")
            else:
                if error and "not finished yet" not in error.lower():
                    failed += 1
                    logger.warning(f"Failed to process record {record.id}: {error}")

        db.close()

        logger.info(f"File mover process complete: {processed} moved, {failed} failed, "
                    f"{len(pending_records) - processed - failed} still downloading")

    except Exception as e:
        logger.error(f"Error in process_completed_downloads: {str(e)}", exc_info=True)

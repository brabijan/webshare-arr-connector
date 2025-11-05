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
        season_folder = f"Season {record.season:02d}"
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

        # Try to find file directly in pyload directory
        direct_path = pyload_dir / expected_filename
        if direct_path.exists():
            logger.info(f"Found file directly: {direct_path}")
            return str(direct_path)

        # Try to find in subdirectories (pyLoad might create package folders)
        for root, dirs, files in os.walk(pyload_dir):
            if expected_filename in files:
                found_path = Path(root) / expected_filename
                logger.info(f"Found file in subdirectory: {found_path}")
                return str(found_path)

        logger.warning(f"File not found in pyLoad directory: {expected_filename}")
        return None

    except Exception as e:
        logger.error(f"Error finding downloaded file: {str(e)}")
        return None


def move_completed_file(record):
    """
    Move a completed download to its destination

    Args:
        record: DownloadHistory record

    Returns:
        tuple: (success, error_message)
    """
    try:
        # Check if pyLoad package is finished
        if not record.pyload_package_id:
            return False, "No pyLoad package ID"

        is_finished = pyload.is_package_finished(record.pyload_package_id)
        if not is_finished:
            logger.debug(f"Package {record.pyload_package_id} not finished yet")
            return False, "Download not finished yet"

        # Update download_completed_at if not set
        db = get_db_session()
        try:
            if not record.download_completed_at:
                record.download_completed_at = datetime.utcnow()
                db.commit()
                logger.info(f"Marked package {record.pyload_package_id} as completed")

            # Find downloaded file
            source_path = find_downloaded_file(record.pyload_package_id, record.filename)
            if not source_path:
                return False, f"Downloaded file not found: {record.filename}"

            # Construct destination path
            dest_path = construct_destination_path(record)
            if not dest_path:
                return False, "Could not construct destination path"

            # Create destination directory if needed
            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Ensured destination directory exists: {dest_dir}")

            # Move file
            logger.info(f"Moving file from {source_path} to {dest_path}")
            shutil.move(source_path, dest_path)
            logger.info(f"File moved successfully: {dest_path}")

            # Update database
            record.file_moved_at = datetime.utcnow()
            record.final_path = dest_path
            record.move_error = None
            db.commit()

            # Delete package from pyLoad
            deleted = pyload.delete_package(record.pyload_package_id)
            if deleted:
                logger.info(f"Deleted package {record.pyload_package_id} from pyLoad")
            else:
                logger.warning(f"Failed to delete package {record.pyload_package_id} from pyLoad")

            return True, None

        finally:
            db.close()

    except Exception as e:
        error_msg = f"Error moving file: {str(e)}"
        logger.error(error_msg, exc_info=True)

        # Update error in database
        try:
            db = get_db_session()
            record.move_error = error_msg
            db.commit()
            db.close()
        except:
            pass

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

            success, error = move_completed_file(record)

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

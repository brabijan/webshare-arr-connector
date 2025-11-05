"""Scheduler service for running periodic tasks"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from services import file_mover
import config

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = None


def start_scheduler():
    """
    Start the background scheduler for periodic tasks
    """
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return _scheduler

    logger.info("Starting file mover scheduler")

    # Create scheduler
    _scheduler = BackgroundScheduler(
        daemon=True,
        job_defaults={
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 1,  # Only one instance at a time
            'misfire_grace_time': 300  # Allow 5 min grace for missed runs
        }
    )

    # Add file mover job
    interval_seconds = config.MONITOR_INTERVAL_SECONDS
    _scheduler.add_job(
        func=file_mover.process_completed_downloads,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id='file_mover',
        name='Process completed downloads',
        replace_existing=True
    )

    logger.info(f"File mover scheduler configured (every {interval_seconds} seconds)")

    # Start scheduler
    _scheduler.start()
    logger.info("Scheduler started successfully")

    return _scheduler


def stop_scheduler():
    """
    Stop the scheduler gracefully
    """
    global _scheduler

    if _scheduler is None:
        return

    logger.info("Stopping scheduler...")
    _scheduler.shutdown(wait=True)
    _scheduler = None
    logger.info("Scheduler stopped")


def get_scheduler():
    """
    Get the current scheduler instance

    Returns:
        BackgroundScheduler: The scheduler instance, or None if not running
    """
    return _scheduler


def is_running():
    """
    Check if scheduler is running

    Returns:
        bool: True if scheduler is running
    """
    return _scheduler is not None and _scheduler.running

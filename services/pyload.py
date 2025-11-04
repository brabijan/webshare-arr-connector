"""pyLoad API client (reused from original app)"""
import requests
import logging
import config

logger = logging.getLogger(__name__)

# Default package name for all Webshare downloads
DEFAULT_PACKAGE_NAME = 'webshare-arr-connector'


def get_or_create_package():
    """
    Find existing package or create new one

    Returns:
        tuple: (success, package_id, message)
    """
    try:
        # First, try to find existing package in queue
        api_url = f"{config.PYLOAD_URL}/api/getQueue"

        response = requests.get(
            api_url,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code != 200:
            logger.warning(f"Failed to get queue: {response.status_code}")
            # If we can't get queue, create new package
            return _create_new_package()

        # Parse queue data
        queue_data = response.json()

        # Look for our default package
        for package in queue_data:
            if package.get('name') == DEFAULT_PACKAGE_NAME:
                pid = package.get('pid')
                logger.info(f"Found existing package: {DEFAULT_PACKAGE_NAME} (ID: {pid})")
                return True, pid, f"Using existing package: {DEFAULT_PACKAGE_NAME}"

        # Package not found, create new one
        logger.info(f"Package {DEFAULT_PACKAGE_NAME} not found, creating new one")
        return _create_new_package()

    except Exception as e:
        logger.error(f"Error in get_or_create_package: {e}", exc_info=True)
        # Fallback to creating new package
        return _create_new_package()


def _create_new_package():
    """
    Create new package in pyLoad

    Returns:
        tuple: (success, package_id, message)
    """
    try:
        api_url = f"{config.PYLOAD_URL}/api/addPackage"

        params = {
            'name': DEFAULT_PACKAGE_NAME,
            'links': [],  # Empty package
            'dest': 1  # Queue
        }

        response = requests.post(
            api_url,
            json=params,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            package_id = response.text.strip().strip('"')
            logger.info(f"Created new package: {DEFAULT_PACKAGE_NAME} (ID: {package_id})")
            return True, package_id, f"Created new package: {DEFAULT_PACKAGE_NAME}"
        else:
            error_msg = f"Failed to create package: {response.status_code}"
            logger.error(error_msg)
            return False, None, error_msg

    except Exception as e:
        error_msg = f"Error creating package: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg


def add_files_to_package(package_id, links):
    """
    Add files to existing package

    Args:
        package_id: pyLoad package ID
        links: List of download links

    Returns:
        tuple: (success, message)
    """
    try:
        if isinstance(links, str):
            links = [links]

        api_url = f"{config.PYLOAD_URL}/api/addFiles"

        params = {
            'pid': package_id,
            'links': links
        }

        logger.info(f"Adding {len(links)} file(s) to package {package_id}")

        response = requests.post(
            api_url,
            json=params,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            count = len(links)
            message = f"Successfully added {count} file(s) to package {package_id}"
            logger.info(message)
            return True, message
        else:
            error_msg = f"Failed to add files: {response.status_code} - {response.text[:200]}"
            logger.error(error_msg)
            return False, error_msg

    except Exception as e:
        error_msg = f"Error adding files to package: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def add_to_pyload(direct_links, package_name=None, destination_path=None):
    """
    Add download(s) to pyLoad API
    Now uses a single shared package for all downloads

    Args:
        direct_links: Single link (string) or list of links
        package_name: DEPRECATED - Ignored, always uses DEFAULT_PACKAGE_NAME
        destination_path: DEPRECATED - Kept for compatibility but not used

    Returns:
        tuple: (success, message, package_id)
    """
    try:
        # Convert single link to list
        if isinstance(direct_links, str):
            direct_links = [direct_links]

        if not direct_links:
            return False, "No links provided", None

        # Get or create the shared package
        success, package_id, pkg_message = get_or_create_package()

        if not success:
            return False, f"Failed to get/create package: {pkg_message}", None

        logger.info(f"Using package {package_id} ({DEFAULT_PACKAGE_NAME})")

        # Add files to the package
        success, add_message = add_files_to_package(package_id, direct_links)

        if success:
            return True, add_message, package_id
        else:
            return False, add_message, None

    except Exception as e:
        message = f"pyLoad error: {str(e)}"
        logger.error(message, exc_info=True)
        return False, message, None

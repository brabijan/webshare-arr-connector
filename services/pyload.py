"""pyLoad API client (reused from original app)"""
import requests
import logging
import config

logger = logging.getLogger(__name__)


def add_to_pyload(direct_links, package_name='Webshare Download', destination_path=None):
    """
    Add download(s) to pyLoad API
    (Reused from original app)

    Args:
        direct_links: Single link (string) or list of links
        package_name: Name of the package in pyLoad
        destination_path: DEPRECATED - Kept for compatibility but not used (pyLoad API doesn't support it)

    Returns:
        tuple: (success, message, package_id)
    """
    try:
        # Convert single link to list
        if isinstance(direct_links, str):
            direct_links = [direct_links]

        if not direct_links:
            return False, "No links provided", None

        # pyLoad API endpoint
        api_url = f"{config.PYLOAD_URL}/api/addPackage"

        # Package parameters
        params = {
            'name': package_name,
            'links': direct_links,
            'dest': 1  # 1 = Queue (immediate download), 0 = Collector
        }

        # Note: destination_path parameter is kept for compatibility but not used
        # pyLoad API doesn't support 'folder' parameter
        logger.info(f"Adding {len(direct_links)} file(s) to pyLoad as package: {package_name}")

        # Use HTTP Basic Auth
        response = requests.post(
            api_url,
            json=params,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            package_id = response.text.strip().strip('"')
            count = len(direct_links)
            message = f"Successfully added {count} file(s) to pyLoad (Package ID: {package_id})"
            logger.info(message)
            return True, message, package_id
        elif response.status_code == 401:
            message = "pyLoad authentication failed - check credentials"
            logger.error(message)
            return False, message, None
        else:
            message = f"pyLoad error: {response.status_code} - {response.text[:200]}"
            logger.error(message)
            return False, message, None

    except Exception as e:
        message = f"pyLoad error: {str(e)}"
        logger.error(message)
        return False, message, None

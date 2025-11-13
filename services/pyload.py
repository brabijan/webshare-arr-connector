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


def get_package_data(package_id):
    """
    Get complete package data from pyLoad API

    Args:
        package_id: pyLoad package ID

    Returns:
        dict: Package data from pyLoad API, or None if error
    """
    try:
        # Try positional argument in URL path
        api_url = f"{config.PYLOAD_URL}/api/getPackageData/{int(package_id)}"

        logger.debug(f"Getting package data for package {package_id}")

        response = requests.get(
            api_url,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            logger.debug(f"Package {package_id} data retrieved successfully")
            return data
        else:
            logger.error(f"Failed to get package data: {response.status_code} - {response.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"Error getting package data: {str(e)}")
        return None


def is_package_finished(package_id):
    """
    Check if package download is finished

    Args:
        package_id: pyLoad package ID

    Returns:
        bool: True if finished, False otherwise
    """
    try:
        data = get_package_data(package_id)
        if not data:
            return False

        # Check links (files) in package
        links = data.get('links', [])
        if not links:
            logger.warning(f"Package {package_id} has no links")
            return False

        # All links must have status "finished" (status code 0)
        all_finished = all(link.get('status') == 0 for link in links)

        if all_finished:
            logger.info(f"Package {package_id} is finished ({len(links)} files)")
        else:
            statuses = [link.get('status') for link in links]
            logger.debug(f"Package {package_id} not finished yet (statuses: {statuses})")

        return all_finished

    except Exception as e:
        logger.error(f"Error checking if package finished: {str(e)}")
        return False


def get_package_files(package_id):
    """
    Get list of files in package with their names and statuses

    Args:
        package_id: pyLoad package ID

    Returns:
        list: List of dicts with 'name', 'status', 'size' for each file
    """
    try:
        data = get_package_data(package_id)
        if not data:
            return []

        links = data.get('links', [])

        files = []
        for link in links:
            files.append({
                'name': link.get('name', ''),
                'status': link.get('status', -1),
                'size': link.get('size', 0),
                'plugin': link.get('plugin', ''),
                'url': link.get('url', '')
            })

        return files

    except Exception as e:
        logger.error(f"Error getting package files: {str(e)}")
        return []


def delete_package(package_id):
    """
    Delete package from pyLoad

    Args:
        package_id: pyLoad package ID

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    try:
        api_url = f"{config.PYLOAD_URL}/api/deletePackages"

        # pyLoad API expects positional argument as single-level list
        params = [int(package_id)]

        logger.info(f"Deleting package {package_id} from pyLoad")

        response = requests.post(
            api_url,
            json=params,
            auth=(config.PYLOAD_USER, config.PYLOAD_PASS),
            timeout=10
        )

        if response.status_code == 200:
            logger.info(f"Package {package_id} deleted successfully")
            return True
        else:
            logger.error(f"Failed to delete package: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error deleting package: {str(e)}")
        return False

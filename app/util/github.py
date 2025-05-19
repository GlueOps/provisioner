import requests
import os, glueops.setup_logging, traceback

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

def get_codespace_releases(environment):
    """
    Checks GitHub API for 30 releases.
    Filters the retrieved releases for the latest 5 stable releases and the latest 5 releases (including prereleases).
    """
    try:
        response = requests.get('https://api.github.com/repos/glueops/codespaces/releases')
        response.raise_for_status()
        releases = response.json()

        if not releases:
            logger.error("No releases returned from the API.")
            raise ValueError("No releases found")
        
        if environment == 'nonprod':
            # Get the latest 5 releases (including prereleases)
            latest_any = [release["tag_name"] for release in releases[:5]]
            return latest_any

        if environment == 'prod':
            # Get the latest 5 stable releases (filter out prereleases)
            stable_releases = [release["tag_name"] for release in releases if not release.get("prerelease")][:5]
            return stable_releases

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

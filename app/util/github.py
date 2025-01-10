# myreleasewatcher.py

import requests
import os, glueops.setup_logging, traceback, json

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

class ReleaseWatcher:
    def __init__(self, url="https://api.github.com/repos/glueops/codespaces/releases?per_page=1"):
        """
        Initialize the ReleaseWatcher with a default URL to check for new releases.
        Stores internal state for the last tag and last assets.
        """
        self.url = url
        self.last_tag = None
        self.last_assets = set()

    def check_for_new_release(self):
        """
        Checks the endpoint for the latest release. If the tag or asset URLs
        differ from the stored state, prints "Hello world".
        """
        try:
            response = requests.get(self.url)
            response.raise_for_status()
            releases = response.json()
            
            if not releases:
                logger.info("No releases returned from the API.")
                return
            
            latest_release = releases[0]
            new_tag = latest_release.get("tag_name", None)
            assets = latest_release.get("assets", [])
            new_assets = set(asset.get("browser_download_url") for asset in assets)

            # Consolidated check for new tag or new assets:
            if new_tag != self.last_tag or new_assets != self.last_assets:
                logger.info(f"new tag: {new_tag} or new asset_urls: {new_assets}")
                
                # Update internal state
                self.last_tag = new_tag
                self.last_assets = new_assets
                return True

        except requests.exceptions.RequestException as err:
            logger.error(f"Request failed: {traceback.format_exc()}")
            raise
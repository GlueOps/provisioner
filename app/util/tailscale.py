import subprocess, os, glueops.setup_logging, requests, traceback
# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

def get_devices(server_name = None, tailscale_tailnet_name = None, tailscale_api_token = None):
    # get all the devices from tailscale
    try:
        response = requests.get(f'https://api.tailscale.com/api/v2/tailnet/{tailscale_tailnet_name}/devices',
            headers={
            'Authorization': f'Bearer {tailscale_api_token}'
        })
        response.raise_for_status()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

    # loop through the devices and get a device_id, and device_ip
    device_id = None
    device_ip = None
    for device in response.json().get("devices", []):
        if device.get("hostname") == server_name:
            device_id = device.get("id")
            device_ip = device.get("addresses", [])[0]

    # return an object containing all the info
    return { "devices": response.json().get("devices", []), "device_id": device_id, "device_ip": device_ip }

def remove_device(tailscale_api_token, device_id):
    try:
        response = requests.delete(f'https://api.tailscale.com/api/v2/device/{device_id}',
            headers={
            'Authorization': f'Bearer {tailscale_api_token}'
        })
        response.raise_for_status()
        logger.info(f"Removed Tailscale device: {device_id}")
    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

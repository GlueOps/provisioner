import json, requests
import os, glueops.setup_logging, traceback

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logger = glueops.setup_logging.configure(level=LOG_LEVEL)

def get_data(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_USERNAME, GUACAMOLE_SERVER_PASSWORD):
    """
    Get the Guacamole API token and data source from the Guacamole server.
    """
    try:
        response = requests.post(f"{GUACAMOLE_SERVER_URL}/api/tokens", data={
            "username": GUACAMOLE_SERVER_USERNAME,
            "password": GUACAMOLE_SERVER_PASSWORD
        })
        response.raise_for_status()
        api_token = response.json().get("authToken")
        dataSource = response.json().get("dataSource")

        return api_token, dataSource

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def get_connection_groups(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_API_TOKEN, dataSource):
    """
    Get the connection groups from the Guacamole server.
    """
    try:
        response = requests.get(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/connectionGroups", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        })
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def find_group_id_by_name(
    groups_data,
    user_name,
    GUACAMOLE_SERVER_URL,
    GUACAMOLE_SERVER_API_TOKEN,
    dataSource
):
    """
    Parses the connection groups dictionary to find the ID of a group with a specific name.

    Args:
        groups_data (dict): The dictionary of connection groups.
        user_name (str): The name of the group to find.

    Returns:
        str: The identifier of the found group, or None if not found.
    """
    for group_details in groups_data.values():
        if group_details.get('name') == user_name:
            return group_details.get('identifier')
    
    identifier = create_connection_group(
        GUACAMOLE_SERVER_URL,
        GUACAMOLE_SERVER_API_TOKEN,
        dataSource,
        user_name
    )

    create_connection_user(
        GUACAMOLE_SERVER_URL,
        GUACAMOLE_SERVER_API_TOKEN,
        dataSource,
        user_name
    )

    grant_connection_group_permission(
        GUACAMOLE_SERVER_URL,
        GUACAMOLE_SERVER_API_TOKEN,
        dataSource,
        user_name,
        identifier
    )
    return identifier

def create_connection_group(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_API_TOKEN, dataSource, user_name):
    """
    create the connection groups for the Guacamole connection.
    """
    try:
        response = requests.post(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/connectionGroups", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        }, json={
            "parentIdentifier": "ROOT",
            "name": user_name,
            "attributes": {
                "max-connections": "",
                "max-connections-per-user": "",
                "enable-session-affinity": ""
            }
        })
        response.raise_for_status()
        return response.json().get("identifier")

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def create_connection_user(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_API_TOKEN, dataSource, user_name):
    """
    create the connection user for the Guacamole connection.
    """
    try:
        response = requests.post(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/users", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        }, json={
            "username": user_name,
            "attributes": {
                "disabled": False,
                "expired": False,
                "accessWindowStart": 0,
                "accessWindowEnd": 0
            }
        })
        response.raise_for_status()
        return response.json().get("identifier")

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def grant_connection_group_permission(
    GUACAMOLE_SERVER_URL,
    GUACAMOLE_SERVER_API_TOKEN,
    dataSource,
    user_name,
    connectionGroupId,
):
    """
    Give the user permissions to access the VM group in the Guacamole server.
    """
    try:
        response = requests.patch(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/users/{user_name}/permissions", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}",
            "Content-Type": "application/json"
        }, json=[
            {
                "op": "add",
                "path": f"/connectionGroupPermissions/{connectionGroupId}",
                "value": "READ"
            }
        ])

        response.raise_for_status()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def grant_connection_permission(
    GUACAMOLE_SERVER_URL,
    GUACAMOLE_SERVER_API_TOKEN,
    dataSource,
    user_name,
    connectionGroupId,
):
    """
    Give the user permissions to access the VM in the Guacamole server.
    """
    try:
        response = requests.patch(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/users/{user_name}/permissions", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}",
            "Content-Type": "application/json"
        }, json=[
            {
                "op": "add",
                "path": f"/connectionPermissions/{connectionGroupId}",
                "value": "READ"
            }
        ])

        response.raise_for_status()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def get_connections(GUACAMOLE_SERVER_URL, GUACAMOLE_SERVER_API_TOKEN, dataSource):
    """
    Get the connections from the Guacamole server.
    """
    try:
        response = requests.get(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/connections", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        })
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def find_connection_id_by_name(connections_data, vm_name):
    """
    Parses the connections dictionary to find the ID of a connection with a specific name.

    Args:
        connections_data (dict): The dictionary of connections.
        vm_name (str): The name of the connection to find.

    Returns:
        str: The identifier of the found connection, or None if not found.
    """
    for connection_details in connections_data.values():
        if connection_details.get('name') == vm_name:
            return connection_details.get('identifier')
    return None

def create_vm(
    GUACAMOLE_SERVER_URL,
    GUACAMOLE_SERVER_API_TOKEN,
    dataSource,
    connectionGroupId,
    vm_name,
    server_ip,
    server_port,
    server_user,
    server_private_key
):
    """
    Set up a VM in the Guacamole server.
    """
    try:
        response = requests.post(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/connections", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        }, json={
            "parentIdentifier": connectionGroupId,
            "name": vm_name,
            "protocol": "ssh",
            "parameters": {
                "hostname": server_ip,
                "port": server_port,
                "username": server_user,
                "private-key": server_private_key,
                "command": f"ssh root@{vm_name}"
            },
            "attributes":{}
        })
        response.raise_for_status()
        return response.json().get("identifier")

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

def delete_vm(
    GUACAMOLE_SERVER_URL,
    GUACAMOLE_SERVER_API_TOKEN,
    dataSource,
    connection_id
):
    """
    delete VM in the Guacamole server.
    """
    try:
        response = requests.delete(f"{GUACAMOLE_SERVER_URL}/api/session/data/{dataSource}/connections/{connection_id}", headers={
            "guacamole-token": f"{GUACAMOLE_SERVER_API_TOKEN}"
        })
        response.raise_for_status()

    except requests.exceptions.RequestException as err:
        logger.error(f"Request failed: {traceback.format_exc()}")
        raise

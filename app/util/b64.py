import base64

def encode_string(input_string: str) -> str:
    """
    Encodes a given string into its Base64 representation.

    Args:
        input_string (str): The string to be encoded.

    Returns:
        str: The Base64-encoded string.
    """
    # Convert the input string to bytes using UTF-8 encoding
    bytes_input = input_string.encode('utf-8')
    
    # Perform Base64 encoding on the bytes
    base64_bytes = base64.b64encode(bytes_input)
    
    # Convert the Base64 bytes back to a string using UTF-8 decoding
    base64_string = base64_bytes.decode('utf-8')
    
    return base64_string

def decode_string(encoded_string: str) -> str:
    """
    Decodes a Base64-encoded string back to its original string.

    Args:
        encoded_string (str): The Base64 string to be decoded.

    Returns:
        str: The decoded original string.

    Raises:
        ValueError: If the input string is not valid Base64.
        UnicodeDecodeError: If the decoded bytes cannot be converted to a UTF-8 string.
    """
    try:
        # Convert the Base64 string to bytes
        base64_bytes = encoded_string.encode('utf-8')
        
        # Perform Base64 decoding
        decoded_bytes = base64.b64decode(base64_bytes, validate=True)
        
        # Convert the decoded bytes back to a string using UTF-8 decoding
        decoded_string = decoded_bytes.decode('utf-8')
        
        return decoded_string
    except (base64.binascii.Error, UnicodeDecodeError) as error:
        # Handle errors related to Base64 decoding and string decoding
        raise ValueError("Invalid Base64 input or decoding error.") from error
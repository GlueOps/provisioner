import textwrap

def fix_indentation(decoded_user_data):
    dedented_data = textwrap.dedent(decoded_user_data)

    return dedented_data.strip()

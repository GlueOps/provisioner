def fix_indentation(decoded_user_data):
    lines = decoded_user_data.splitlines()
    fixed_lines = []
    for line in lines:
        # Remove leading spaces for top-level keys like runcmd
        if line.strip().startswith("runcmd:"):
            fixed_lines.append(line.strip())
        # Re-indent list items under runcmd with 2 spaces
        elif line.strip().startswith("-"):
            fixed_lines.append(f"  {line.strip()}")
        else:
            fixed_lines.append(line.strip())
    return "\n".join(fixed_lines)
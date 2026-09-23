def convert_to_bool(value, default):
    if value: return bool(value == "True" or value == "1")
    return default

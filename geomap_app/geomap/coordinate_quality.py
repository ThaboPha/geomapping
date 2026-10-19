"""Separate address-level geocoding from provisional locality points."""
def reliable_address(level):
    value=str(level or '')
    return value=='Street' or value.startswith('Azure Maps address (')

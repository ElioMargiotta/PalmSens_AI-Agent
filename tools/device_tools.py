# device_tools.py
from pspython import pspyinstruments

def discover_channels():
    """Return a list of available channel indices, e.g. [0,1,2]."""
    instruments = pspyinstruments.discover_instruments()
    return list(range(len(instruments)))

def describe_channels():
    """Return a formatted string describing available instruments."""
    instruments = pspyinstruments.discover_instruments()
    if not instruments:
        return "No PalmSens instruments detected."
    return f"Found {len(instruments)} PalmSens instruments: channels {', '.join(str(i) for i in range(len(instruments)))}"

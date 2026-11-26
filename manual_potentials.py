"""F6 screenshot import. This module never focuses, clicks or scrolls a window."""
import threading
from ldplayer_scanner import LDWindow
from potential_table import read_manual_capture,apply_manual_capture

def capture_current_game():
    return LDWindow(threading.Event(),read_only=True).capture()

def process_capture(scanner,image,records,directory):
    snapshot=read_manual_capture(scanner,image,directory,records)
    count=apply_manual_capture(records,snapshot)
    return snapshot,count

import collections
import threading

import config


latest_data = {}
serial_connected = False
serial_error = None
last_update = None

serial_port = None

state_lock = threading.Lock()
serial_lock = threading.Lock()
stop_event = threading.Event()

history_buffer = collections.deque(maxlen=config.HISTORY_MEMORY_LIMIT)
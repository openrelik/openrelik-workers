import os
import time

# Configure timezone to UTC for all tests at the very beginning of pytest collection
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

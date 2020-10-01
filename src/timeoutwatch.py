import time


class TimeoutWatch:
    def __init__(self, timeout):
        self.start_time = None
        self.timeout = timeout

    def start(self):
        self.start_time = time.time()

    @property
    def time_elapsed(self):
        return time.time() - self.start_time

    @property
    def time_remaining(self):
        return self.timeout - self.time_elapsed

    def refresh(self):
        self.start_time = time.time()

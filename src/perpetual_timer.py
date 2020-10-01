from threading import Timer


class PerpetualTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            try:
                self.function(*self.args, **self.kwargs)
            except NameError as e:
                self.cancel()


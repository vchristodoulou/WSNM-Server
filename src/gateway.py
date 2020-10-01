class Gateway:
    """Gateway class"""

    def __init__(self, _id, addr):
        self._id = _id
        self.addr = addr


class GatewayInfo:
    """GatewayInfo class"""

    def __init__(self, _id, start_time):
        self.id = _id
        self.seed = 0
        self.timer = start_time

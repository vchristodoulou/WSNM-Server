import db.utils as utils


class Node:
    """Node class"""

    def __init__(self, _id, nodetype_id, location):
        self.id = _id
        self.nodetype_id = nodetype_id
        self.gateway_id = None
        self.image_name = None
        self.flashed = utils.FLASH_NOT_STARTED
        self.location = location

import pymongo
from pymongo.errors import ConnectionFailure
import bson
from bson.objectid import ObjectId
import os
import logging.config
import json

import db.utils as utils
import xml_handler


class DBConnector:
    """DbConnector class"""

    def __init__(self, ip, port):
        self.client = pymongo.MongoClient(ip, port, serverSelectionTimeoutMS=1)
        self.db = self.client[utils.CLIENT]
        logging.config.fileConfig(os.path.dirname(os.path.abspath(__file__)) + '/../' + 'logging.conf')
        self.logger = logging.getLogger('db')

    def check_connection(self):
        try:
            self.client.admin.command('ismaster')
        except ConnectionFailure as err:
            self.logger.debug(err)
            return False
        self.logger.debug('Connection established with DB')
        return True

    def close(self):
        self.db.close()

    def insert_gateway(self, gateway, location, nodes):
        gateway = self.serialize(gateway)
        nodes = self.serialize(nodes)
        self.logger.info('Insert Gateway[%s]' % (gateway[utils.GATEWAY_UID]))
        gateway[utils.LOCATION] = location

        if nodes:
            res_gateway = self.db[utils.GATEWAYS].insert_one(gateway)
            for node in nodes:
                node[utils.GATEWAY_ID] = res_gateway.inserted_id
            self.db[utils.NODES].insert_many(nodes)
        else:
            self.db[utils.GATEWAYS].insert_one(gateway)

    def update_gateway_nodes(self, gateway, nodes):
        gateway = self.serialize(gateway)
        nodes = self.serialize(nodes)
        self.logger.info('Update Gateway[%s]' % (gateway[utils.GATEWAY_UID]))

        new_nodes = []
        for node in nodes:
            new_nodes.append(node[utils.NODE_ID])

        prev_nodes = []
        # Return a list so you can iterate over the result many times...pymongo cursor
        existing_nodes = list(self.db[utils.NODES].find({utils.GATEWAY_ID: gateway[utils.GATEWAY_UID]},
                                                        {utils.NODE_UID: 1, utils.NODE_ID: 1}))
        for node in existing_nodes:
            prev_nodes.append(node[utils.NODE_ID])

        insert_nodes_ids = set(new_nodes) - set(prev_nodes)
        for node_id in insert_nodes_ids:
            for node in nodes:
                if node_id == node[utils.NODE_ID]:
                    self.db[utils.NODES].insert_one(node)

        delete_nodes_ids = set(prev_nodes) - set(new_nodes)
        for node_id in delete_nodes_ids:
            for node in existing_nodes:
                if node_id == node[utils.NODE_ID]:
                    self.db[utils.NODES].delete_one({utils.NODE_UID: node[utils.NODE_UID]})

    def delete_gateway(self, _id):
        # Delete nodes
        nodes = self.db[utils.NODES].find({utils.GATEWAY_ID: _id}, {utils.NODE_UID: 1, utils.NODE_ID: 1,
                                                                    utils.IMAGE_NAME: 1})
        self.delete_many_nodes(nodes)

        # Delete gateway
        self.db[utils.GATEWAYS].delete_one({utils.GATEWAY_UID: _id})
        self.logger.debug('Delete Gateway[%s]' % _id)

    def update_gateway_location(self, _id, location):
        self.db[utils.GATEWAYS].update({utils.GATEWAY_UID: _id}, {utils.LOCATION: location})

    def get_gateway_addr(self, _id):
        gateway_addr = self.db[utils.GATEWAYS].find_one({utils.GATEWAY_UID: _id}, {utils.GATEWAY_UID: 0,
                                                                                   utils.GATEWAY_ADDRESS: 1})
        return gateway_addr[utils.GATEWAY_ADDRESS]

    def get_gateway_id_by_node_uid(self, _id):
        gateway = self.db[utils.NODES].find_one({utils.NODE_UID: ObjectId(_id)},
                                                {utils.NODE_UID: 0, utils.GATEWAY_ID: 1})

        return gateway[utils.GATEWAY_ID]

    def find_gateway_by_addr(self, addr):
        gateway = self.db[utils.GATEWAYS].find_one({utils.GATEWAY_ADDRESS: addr}, {utils.GATEWAY_UID: 1})

        return gateway[utils.GATEWAY_UID]

    def delete_many_nodes(self, nodes):
        for node in nodes:
            self.db[utils.NODES].delete_one({utils.NODE_UID: node[utils.NODE_UID]})
            self.logger.debug('--- Deleted Node[%s]' % node[utils.NODE_ID])

    def node_update_flash_info(self, node_uid, flashed, image_name):
        self.db[utils.NODES].update_one({utils.NODE_UID: ObjectId(node_uid)},
                                        {"$set": {utils.NODE_FLASHED: flashed, utils.IMAGE_NAME: image_name}})

    def get_nodes(self):
        nodes = []

        nodes_cursor = self.db[utils.NODES].find()
        for node in nodes_cursor:
            node[utils.NODE_UID] = str(node[utils.NODE_UID])
            nodes.append(node)

        self.logger.debug(nodes)

        return nodes

    def get_node_uid_by_gateway_id_and_node_id(self, gateway_uid, node_id):
        node = self.db[utils.NODES].find_one({utils.GATEWAY_ID: gateway_uid, utils.NODE_ID: node_id},
                                             {utils.NODE_UID: 1})

        return str(node[utils.NODE_UID])

    def get_node_id_by_uid(self, _id):
        node = self.db[utils.NODES].find_one({utils.NODE_UID: ObjectId(_id)}, {utils.NODE_UID: 0, utils.NODE_ID: 1})
        return node[utils.NODE_ID]

    def get_node_by_uid(self, _id):
        node = self.db[utils.NODES].find_one({utils.NODE_UID: ObjectId(_id)})
        node[utils.NODE_UID] = str(node[utils.NODE_UID])
        return node

    def insert_nodetypes(self, nodetypes_file):
        self.drop_nodetypes()
        nodetypes = xml_handler.get_nodetypes(nodetypes_file)
        self.db[utils.NODETYPES].insert(nodetypes)

    def drop_nodetypes(self):
        self.db[utils.NODETYPES].drop()

    def get_nodetypes(self):
        nodetypes = []
        cursor = self.db[utils.NODETYPES].find({})
        for nodetype in cursor:
            nodetypes.append(nodetype)

        return nodetypes

    def get_slots(self):
        return self.db[utils.TIMESLOTS].find()

    def get_slot_by_id(self, _id):
        try:
            return self.db[utils.TIMESLOTS].find_one({utils.TIMESLOT_UID: ObjectId(_id)})
        except bson.errors.InvalidId:
            return None

    def delete_slot_by_id(self, _id):
        self.db[utils.TIMESLOTS].delete_one({utils.TIMESLOT_UID: ObjectId(_id)})

    def save_timeslots(self, user_id, new_slots):
        saved_slots = []
        new_valid_slots = self.check_valid_slots(new_slots)
        new_combined_valid_slots = utils.combine_slots(new_valid_slots)
        for slot in new_combined_valid_slots:
            slot.update({utils.USER_ID: user_id})
            slot['end'] = slot['end'] - utils.millisecond()
            '''
            if not self.db[utils.TIMESLOTS].update_one({utils.TIMESLOT_START: {"$eq": slot[utils.TIMESLOT_END]}},
                                                       {'$set': {utils.TIMESLOT_START: slot[utils.TIMESLOT_START]}}):
                if not self.db[utils.TIMESLOTS].update_one({utils.TIMESLOT_END: {"$eq": slot[utils.TIMESLOT_START]}},
                                                           {'$set': {utils.TIMESLOT_END: slot[utils.TIMESLOT_END]}}):
                    self.db[utils.TIMESLOTS].insert_one(slot)
            '''
            self.db[utils.TIMESLOTS].insert_one(slot)
            slot.pop(utils.TIMESLOT_UID, None)
            slot.pop(utils.USER_ID, None)
            saved_slots.append(slot)

        return saved_slots

    def check_valid_slots(self, slots):
        cursor = self.get_slots()
        for slot in cursor:
            for _slot in slots[:]:
                if utils.not_valid_slot(slot, _slot):
                    slots.remove(_slot)
            if not slots:
                return []
        return slots

    def get_day_slots(self, day):
        day_slots = []
        day_datetime = utils.string_to_datetime(day)
        day_datetime_start = day_datetime - utils.utc_minus_offset()
        day_datetime_end = utils.get_midnight(day_datetime) + utils.utc_plus_offset()
        day_slots_cursor = self.db[utils.TIMESLOTS].find({"$or": [
            {"$and": [{"start": {"$lt": day_datetime_end}}, {"start": {"$gte": day_datetime_start}}]},
            {"$and": [{"end": {"$lte": day_datetime_end}}, {"end": {"$gt": day_datetime_start}}]},
            {"$and": [{"start": {"$lt": day_datetime_start}}, {"end": {"$gt": day_datetime_start}}]}
        ]})
        for slot in day_slots_cursor:
            slot.pop(utils.TIMESLOT_UID, None)
            day_slots.append(slot)

        return day_slots

    def get_user_slots(self, user_id):
        user_slots = []
        user_slots_cursor = self.db[utils.TIMESLOTS].find({utils.USER_ID: user_id})
        for slot in user_slots_cursor:
            slot.pop(utils.USER_ID, None)
            slot[utils.TIMESLOT_UID] = str(slot[utils.TIMESLOT_UID])
            user_slots.append(slot)

        return user_slots

    def delete_timeslot(self, _id):
        self.db[utils.TIMESLOTS].delete_one({utils.TIMESLOT_UID: _id})

    def check_slots_start(self):
        now = utils.get_current_time()
        minute = utils.minute()
        now_plus = now + minute
        cursor = self.get_slots()
        for slot in cursor:
            start_remaining_time = slot[utils.TIMESLOT_START] - now_plus
            if minute > start_remaining_time:
                return str(slot[utils.TIMESLOT_UID])

        return None

    def check_slots_end(self):
        now = utils.get_current_time()
        minute = utils.minute()
        now_plus = now + minute
        cursor = self.get_slots()
        for slot in cursor:
            end_remaining_time = slot[utils.TIMESLOT_END] - now_plus
            if minute > end_remaining_time:
                return slot[utils.TIMESLOT_UID]

        return None

    def create_user(self, data):
        res = self.db[utils.USERS].find({utils.USER_UID: data['email']})
        if not len(list(res)):
            hashed_password = utils.hash_password(data[utils.USER_PASSWORD])
            self.db[utils.USERS].insert_one({utils.USER_UID: data['email'], utils.USER_NAME: data[utils.USER_NAME],
                                             utils.USER_PASSWORD: hashed_password})
            return {'status': 201}
        else:
            return {'message': 'Error in Sign Up', 'status': 403}

    def login_user(self, data):
        user = self.db[utils.USERS].find_one({utils.USER_UID: data['email']})
        if user and utils.check_password_hash(data[utils.USER_PASSWORD].encode(), user[utils.USER_PASSWORD]):
            auth_token = utils.encode_auth_token(user[utils.USER_UID])
            return {'token': auth_token.decode(), 'status': 200}
        else:
            return {'message': 'User does not exist', 'status': 401}

    @staticmethod
    def serialize(obj):
        obj_serialized = json.dumps(obj, default=json_def_encoder)  # Serialized
        return json.loads(obj_serialized)                           # Dict


def json_def_encoder(obj):
    return obj.__dict__

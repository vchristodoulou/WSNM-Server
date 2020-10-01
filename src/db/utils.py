import bcrypt
from datetime import datetime, timedelta, time
import jwt


CLIENT = 'WSNM'

GATEWAYS = 'gateways'
GATEWAY_UID = '_id'
GATEWAY_ID = 'gateway_id'
GATEWAY_ADDRESS = 'addr'

NODES = 'nodes'
NODE_UID = '_id'
NODE_ID = 'id'
NODE_FLASHED = 'flashed'
FLASH_STARTED = 'STARTED'
FLASH_NOT_STARTED = 'NOT_STARTED'
FLASH_FINISHED = 'FINISHED'

NODETYPES = 'nodetypes'
NODETYPE_UID = '_id'
NODETYPE_ID = 'nodetype_id'
NODETYPE_PLATFORM = 'platform'
NODETYPE_PROCESSOR = 'processor'
NODETYPE_MEMORY = 'memory'
NODETYPE_RADIO = 'radio'
NODETYPE_SENSORS = 'sensors'

IMAGE_NAME = 'image_name'
IMAGE_DATA = 'image_data'

TIMESLOTS = 'timeslots'
TIMESLOT_UID = '_id'
TIMESLOT_ID = 'slot_id'
TIMESLOT_START = 'start'
TIMESLOT_END = 'end'

UTC_PLUS_OFFSET = 14
UTC_MINUS_OFFSET = 12

USERS = 'users'
USER_UID = '_id'
USER_ID = 'user_id'
USER_NAME = 'username'
USER_PASSWORD = 'password'

LOCATION = 'location'

USER = 'user'
TOKEN = 'token'
SLOTS = 'slots'
DATE = 'date'
NODE_UIDS = 'node_uids'
NODE_IDS = 'node_ids'


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


def check_password_hash(password, stored_password):
    return bcrypt.checkpw(password, stored_password)


def encode_auth_token(user_id):
    payload = {
        'exp': datetime.utcnow() + timedelta(days=0, hours=8),
        'user': user_id
    }

    return jwt.encode(payload, 'secret', algorithm='HS256')


def convert_isoformat_to_datetime(slots):
    for slot in slots:
        slot[TIMESLOT_START] = string_to_datetime(slot[TIMESLOT_START])
        slot[TIMESLOT_END] = string_to_datetime(slot[TIMESLOT_END])

    return slots


def convert_datetime_to_isoformat(slots):
    for slot in slots:
        slot[TIMESLOT_START] = datetime_to_string(slot[TIMESLOT_START])
        slot[TIMESLOT_END] = datetime_to_string(slot[TIMESLOT_END])

    return slots


def is_same_date(today, start, end):
    today = string_to_datetime(today)
    start = string_to_datetime(start)
    end = string_to_datetime(end)
    return ((today.day == start.day) and (today.month == start.month) and (today.year == start.year)) or \
           ((today.day == end.day) and (today.month == end.month) and (today.year == end.year))


def not_valid_slot(slot, new_slot):
    return ((slot[TIMESLOT_START] <= new_slot[TIMESLOT_START]) and
            (slot[TIMESLOT_END] > new_slot[TIMESLOT_START])) or \
           ((slot[TIMESLOT_START] < new_slot[TIMESLOT_END]) and
            (slot[TIMESLOT_END] >= new_slot[TIMESLOT_END]))


def combine_slots(slots):
    slots_combined = []
    slots_done = []

    while True:
        flag = True
        slot = slots.pop(0)
        if not slots:
            slots_done.append(slot)
            break
        for i, _slot in enumerate(slots):
            if _slot['start'] == slot['end']:
                slot['end'] = _slot['end']
                slots_combined.append(slot)
                slots.pop(i)
                flag = False
                break
            if _slot['end'] == slot['start']:
                slot['start'] = _slot['start']
                slots_combined.append(slot)
                slots.pop(i)
                flag = False
                break
        if flag:
            slots_done.append(slot)
        slots = slots + slots_combined
        slots_combined = []
    return slots_done


def is_old_date(date):
    now = datetime.utcnow()

    return now > date


def minute():
    return timedelta(seconds=60)


def get_current_time():
    return datetime.utcnow()


def get_midnight(day):
    return datetime.combine(day, time(23, 59, 59, 999999))


def utc_minus_offset():
    return timedelta(hours=UTC_MINUS_OFFSET)


def utc_plus_offset():
    return timedelta(hours=UTC_PLUS_OFFSET)


def millisecond():
    return timedelta(milliseconds=1)


def string_to_datetime(date):
    return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ')


def datetime_to_string(date):
    return date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

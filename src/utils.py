import struct
import json
import jwt
import glob
import os
import time
import socket


NODETYPES_FILE = 'nodetypes.xml'
LOCATIONS_FILE = 'locations.xml'

ERASE_IMAGES_PATH = 'images/erase'

GATEWAY_ISALIVE = 'ISALIVE'
GATEWAY_NODES_FLASH = 'GNF'.encode()
GATEWAY_NODES_RESET = 'GNR'.encode()
GATEWAY_NODES_ERASE = 'GNE'.encode()

NODES_GET = 'NGE'.encode()
NODES_FLASH = 'NFL'.encode()
NODES_RESET = 'NRS'.encode()
NODES_ERASE = 'NER'.encode()

TIMESLOTS_SAVE = 'TSA'.encode()
TIMESLOTS_GET_DAYSLOTS = 'TGD'.encode()
TIMESLOTS_GET_USERSLOTS = 'TGU'.encode()

USERS_SIGNUP = 'USU'.encode()
USERS_LOGIN = 'ULI'.encode()

NODETYPES_GET = 'NTG'.encode()

IMAGE_SAVE = 'IMS'.encode()
IMAGES_GET = 'IMG'.encode()
IMAGE_DELETE = 'IMD'.encode()

DEBUG_START = 'DST'.encode()
DEBUG_END = 'DEN'.encode()
DEBUG_GATEWAY = 'DGA'.encode()
DEBUG_CLEAR_LOG = 'DCL'.encode()
DEBUG_GET_LOG = 'DGL'.encode()

FLASHED = 'FLASHED'
ERASED = 'ERASED'
ERROR = 'ERROR'

# Size in bytes
SIZE_ID = 8
SIZE_IP = 16
SIZE_ACTION = 3
SIZE_OF_DATA = 2
SIZE_PORT = 2
SIZE_SEED = 2

SOCK_BUFSIZE = 1024


def segment_packet(pck, action=None):
    """Segment a packet"""

    if action == GATEWAY_ISALIVE:
        pck_id = struct.unpack('!' + str(SIZE_ID) + 's', bytes(pck[:SIZE_ID]))
        pck_ip = struct.unpack('!' + str(SIZE_IP) + 's', bytes(pck[SIZE_ID:SIZE_ID + SIZE_IP]))
        pck_port = struct.unpack('!H', bytes(pck[SIZE_ID + SIZE_IP: SIZE_ID + SIZE_IP + SIZE_PORT]))
        pck_seed = struct.unpack('!H',
                                 bytes(pck[SIZE_ID + SIZE_IP + SIZE_PORT: SIZE_ID + SIZE_IP + SIZE_PORT + SIZE_SEED]))

        return (pck_id[0].decode().split('\x00', 1)[0],
                pck_ip[0].decode().split('\x00', 1)[0],
                pck_port[0],
                pck_seed[0])
    elif action == DEBUG_GATEWAY:
        pck_id = struct.unpack('!' + str(SIZE_ID) + 's', bytes(pck[:SIZE_ID]))
        pck_action = struct.unpack('!' + str(SIZE_ACTION) + 's', bytes(pck[SIZE_ID:SIZE_ID + SIZE_ACTION]))
        pck_size = struct.unpack('!H', bytes(pck[SIZE_ID + SIZE_ACTION:SIZE_ID + SIZE_ACTION + SIZE_OF_DATA]))
        return (pck_action[0],
                json.loads(pck[SIZE_ACTION + SIZE_OF_DATA:
                               SIZE_ACTION + SIZE_OF_DATA + pck_size[0]]))
    else:
        pck_action = struct.unpack('!' + str(SIZE_ACTION) + 's', bytes(pck[:SIZE_ACTION]))
        pck_size = struct.unpack('!H', bytes(pck[SIZE_ACTION:SIZE_ACTION + SIZE_OF_DATA]))
        return (pck_action[0],
                json.loads(pck[SIZE_ACTION + SIZE_OF_DATA:
                               SIZE_ACTION + SIZE_OF_DATA + pck_size[0]]))


def create_request_packet(action, data):
    """Create a packet"""
    pck = bytearray()

    pck.extend(struct.pack('!' + str(SIZE_ACTION) + 's', action))
    pck.extend(struct.pack('!H', len(data)))
    pck.extend(data)

    return pck


def create_response_packet(data):
    """Create a packet"""
    pck = bytearray()

    pck.extend(struct.pack('!H', len(data)))
    pck.extend(data)

    return pck


def data_size_to_bytes(size):
    pck = bytearray()

    pck.extend(struct.pack('!H', size))

    return pck


def read_data_from_socket(s):
    buffer = b''

    while True:
        try:
            data = s.recv(SOCK_BUFSIZE)
            if data:
                buffer = buffer + data
                if len(buffer) >= SIZE_ACTION + SIZE_OF_DATA:
                    data_size = struct.unpack('!H', bytes(buffer[SIZE_ACTION:SIZE_ACTION + SIZE_OF_DATA]))[0]
                    while data_size + SIZE_ACTION + SIZE_OF_DATA > len(buffer):
                        data = s.recv(SOCK_BUFSIZE)
                        if data:
                            buffer = buffer + data
                        else:
                            break
                    return buffer
            else:
                break
        except socket.timeout as e:
            print('Socket timeout', e)
            break
        except BlockingIOError as e:
            print(e)
            break
        except ConnectionResetError as e:
            print(e)
            break

    return buffer


def send_invalid_token_error(s):
    pck = create_response_packet(
        json.dumps({'message': 'INVALID TOKEN', 'status': 401}).encode()
    )

    # { message, status: 401 }
    s.sendall(pck)


def send_invalid_slot_error(s):
    pck = create_response_packet(
        json.dumps({'message': 'INVALID SLOT', 'status': 403}).encode()
    )

    # { message, status: 403 }
    s.sendall(pck)


def decode_auth_token(token):
    try:
        return jwt.decode(token.encode(), 'secret', algorithms=['HS256'])
    except jwt.InvalidTokenError as e:
        # Base exception when decode() fails on a token (multiple reasons included)
        # https://pyjwt.readthedocs.io/en/latest/api.html?highlight=InvalidTokenError#jwt.exceptions.InvalidTokenError
        print(e)
        return ''


def separate_by_gateway_id(data):
    result = []

    gateway_ids = {}
    i = 0
    for item in data:
        if item['gateway_id'] not in gateway_ids:
            gateway_ids[item['gateway_id']] = i
            result.append([item['gateway_id']])
            result[i].append(item['node_uid'])
            i += 1
        else:
            index = gateway_ids[item['gateway_id']]
            result[index].append(item['node_uid'])

    return result


def get_nodetypes_images(user_id):
    path = os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id + '/'

    nodetypes_images = []
    for (root, dirs, files) in os.walk(path):
        if not dirs:
            nodetype_id = os.path.basename(root)
            nodetypes_images.append({'nodetype_id': nodetype_id, 'images': files})

    return nodetypes_images


def save_image(user_id, nodetype, name, data):
    path = os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id + '/' + nodetype + '/'
    if not os.path.exists(path):
        os.makedirs(path)

    f = open(path + name, 'w')
    f.write(data)
    f.flush()


def delete_image(user_id, name, nodetype):
    image_path = os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id + '/' + nodetype + '/' + name

    if os.path.exists(image_path):
        os.remove(image_path)
        check_and_delete_empty_folder(os.path.dirname(os.path.abspath(__file__)) +
                                      '/images/' + user_id + '/' + nodetype)
        check_and_delete_empty_folder(os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id)
        return {'status': 204}
    else:
        print("The image [%s] does not exist", image_path)
        return {'status': 404}


def check_and_delete_empty_folder(path):
    if not os.listdir(path):
        os.rmdir(path)


def get_nodetype_by_user_and_image_name(user_id, name):
    path = os.path.dirname(os.path.abspath(__file__)) + '/images/' + user_id + '/'

    _dirs = []
    for (root, dirs, files) in os.walk(path):
        _dirs.extend(dirs)

    for _dir in _dirs:
        _path = path + _dir
        for (root, dirs, files) in os.walk(_path):
            if name in files:
                return _dir


def delete_old_logs(max_time, experiment_dir):
    logs = glob.iglob(os.path.dirname(os.path.abspath(__file__)) + '/' + experiment_dir + '/**', recursive=True)

    for log in logs:
        if os.path.isfile(log):
            if (time.time() - os.path.getmtime(log)) > max_time:
                try:
                    os.remove(log)
                except OSError as e:
                    print("Error: %s - %s." % (e.filename, e.strerror))


def remove_from_list(_list, item):
    try:
        _list.remove(item)
        return 0
    except ValueError:
        return 1


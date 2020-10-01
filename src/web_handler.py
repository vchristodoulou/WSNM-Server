import threading
import socket
import select
import sys
import os
import ftplib
import logging.config
import json

import ftp
import utils
import db.utils as db_utils
import timeoutwatch
import perpetual_timer


class WebHandler(threading.Thread):
    def __init__(self, db_connector, server_cfg, stop_thread_event):
        threading.Thread.__init__(self)
        self.dbConnector = db_connector
        self.server_cfg = server_cfg
        self.slotsStartWatch = timeoutwatch.TimeoutWatch(float(self.server_cfg['timeout_slots_start']))
        self.slotsEndWatch = timeoutwatch.TimeoutWatch(float(self.server_cfg['timeout_slots_end']))
        self.experiment_dir = self.server_cfg['experiment_dir']
        self._stop_thread_event = stop_thread_event

        self.sock_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock_tcp.setblocking(False)
        self.sock_tcp.bind((self.server_cfg['public_ip'], int(self.server_cfg['public_port'])))
        self.sock_tcp.listen(5)
        self.inputs = [self.sock_tcp]

        self.gateway_sockets = []  # List of lists with pending requests (flash, erase, reset)
        self.gateway_sockets_info = []  # [{web_socket, data, image_name}]
        self.experiment_info = {}
        self.sock_debug = None
        self._debug_lock = threading.Lock()

        self.log_timer = perpetual_timer.PerpetualTimer(float(self.server_cfg['timeout_log_file']),
                                                        utils.delete_old_logs,
                                                        (float(self.server_cfg['timer_log_file']), self.experiment_dir))
        self.log_timer.start()

        logging.config.fileConfig(os.path.dirname(os.path.abspath(__file__)) + '/' + 'logging.conf')
        self.logger = logging.getLogger('web')

    def run(self):
        self.slotsStartWatch.start()
        self.slotsEndWatch.start()

        while not self.stopped_thread():
            self.check_timeouts()
            new_timeout = self.get_next_timeout()
            readable, writable, exceptional = select.select(self.inputs, [], self.inputs, new_timeout)

            for s in readable:
                if s is self.sock_tcp:
                    (connection, address) = self.sock_tcp.accept()
                    connection.setblocking(False)
                    self.logger.info('TCP CON (%s, %d)' % (address[0], address[1]))
                    self.inputs.append(connection)
                else:
                    buffer = utils.read_data_from_socket(s)
                    if buffer:
                        self.logger.debug('Req_data = %s\t client = (%s, %d)'
                                          % (buffer, s.getpeername()[0], s.getpeername()[1]))
                        action, data = utils.segment_packet(buffer)

                        if action == utils.GATEWAY_NODES_FLASH:
                            image_name = self.get_image_name(s)
                            result = []
                            for node in data[db_utils.NODES]:
                                if node['status'] == utils.FLASHED:
                                    gateway_id = self.dbConnector.find_gateway_by_addr(s.getpeername())
                                    node_uid = self.dbConnector.get_node_uid_by_gateway_id_and_node_id(
                                        gateway_id, node['node_id'])
                                    self.dbConnector.node_update_flash_info(node_uid, 'FINISHED', image_name)
                                    _node = {'_id': node_uid, 'status': node['status']}
                                else:   # node['status'] = utils.ERROR
                                    gateway_id = self.dbConnector.find_gateway_by_addr(s.getpeername())
                                    node_uid = self.dbConnector.get_node_uid_by_gateway_id_and_node_id(
                                        gateway_id, node['node_id'])
                                    _node = {'_id': node_uid, 'status': node['status']}
                                result.append(_node)

                            self.handle_gateway_request(s, result)
                            self.inputs.remove(s)
                            s.close()

                        elif action == utils.GATEWAY_NODES_ERASE:
                            result = []
                            for node in data[db_utils.NODES]:
                                if node['status'] == utils.ERASED:
                                    gateway_id = self.dbConnector.find_gateway_by_addr(s.getpeername())
                                    node_uid = self.dbConnector.get_node_uid_by_gateway_id_and_node_id(
                                        gateway_id, node['node_id'])
                                    self.dbConnector.node_update_flash_info(node_uid, 'NOT_STARTED', None)
                                    _node = {'_id': node_uid, 'status': node['status']}
                                else:   # node['status'] = utils.ERROR
                                    gateway_id = self.dbConnector.find_gateway_by_addr(s.getpeername())
                                    node_uid = self.dbConnector.get_node_uid_by_gateway_id_and_node_id(
                                        gateway_id, node['node_id'])
                                    _node = {'_id': node_uid, 'status': node['status']}
                                result.append(_node)

                            self.handle_gateway_request(s, result)
                            self.inputs.remove(s)
                            s.close()

                        elif action == utils.GATEWAY_NODES_RESET:
                            result = []
                            for node in data[db_utils.NODES]:
                                gateway_id = self.dbConnector.find_gateway_by_addr(s.getpeername())
                                node_uid = self.dbConnector.get_node_uid_by_gateway_id_and_node_id(
                                    gateway_id, node['node_id'])
                                _node = {'_id': node_uid, 'status': node['status']}
                                result.append(_node)

                            self.handle_gateway_request(s, result)
                            self.inputs.remove(s)
                            s.close()

                        elif action == utils.IMAGES_GET:  # { token }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                nodetypes_images = utils.get_nodetypes_images(decoded_token[db_utils.USER])
                                pck = utils.create_response_packet(json.dumps({'data': nodetypes_images, 'status': 200})
                                                                   .encode())

                                # OnSuccess: { data, status: 200 }
                                s.sendall(pck)

                        elif action == utils.IMAGE_SAVE:  # { token, image_name, image_data, nodetype_id }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                utils.save_image(decoded_token[db_utils.USER], data[db_utils.NODETYPE_ID],
                                                 data[db_utils.IMAGE_NAME], data[db_utils.IMAGE_DATA])
                                pck = utils.create_response_packet(json.dumps({'status': 200}).encode())

                                # OnSuccess: { status: 200 }
                                s.sendall(pck)

                        elif action == utils.IMAGE_DELETE:  # { token, image_name }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                nodetype_id = utils.get_nodetype_by_user_and_image_name(decoded_token[db_utils.USER],
                                                                                        data[db_utils.IMAGE_NAME])
                                res = utils.delete_image(decoded_token[db_utils.USER],
                                                         data[db_utils.IMAGE_NAME],
                                                         nodetype_id)
                                pck = utils.create_response_packet(json.dumps(res).encode())

                                # OnSuccess: { status: 204 }
                                # OnError  : { status: 404 }
                                s.sendall(pck)

                        elif action == utils.NODES_GET:  # { token }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                nodes = self.dbConnector.get_nodes()
                                pck = utils.create_response_packet(json.dumps({'nodes': nodes, 'status': 200}).encode())

                                # OnSuccess: { nodes, status: 200 }
                                s.sendall(pck)

                        elif action == utils.NODES_FLASH:  # { token, slot_id, image_name, node_uids}
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                gateway_socks = self.send_flash_request(decoded_token[db_utils.USER],
                                                                        data[db_utils.IMAGE_NAME],
                                                                        data[db_utils.NODE_UIDS])
                                self.inputs.extend(gateway_socks)
                                self.gateway_sockets.append(gateway_socks)
                                self.gateway_sockets_info.append({'web_socket': s, 'data': [],
                                                                  db_utils.IMAGE_NAME: data[db_utils.IMAGE_NAME]})

                        elif action == utils.NODES_ERASE:  # { token, slot_id, node_uids }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                gateway_socks = self.send_erase_request(data[db_utils.NODE_UIDS])
                                self.inputs.extend(gateway_socks)
                                self.gateway_sockets.append(gateway_socks)
                                self.gateway_sockets_info.append({'web_socket': s, 'data': [], db_utils.IMAGE_NAME: ''})

                        elif action == utils.NODES_RESET:  # { token, slot_id, node_uids }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                gateway_socks = self.send_reset_request(data[db_utils.NODE_UIDS])
                                self.inputs.extend(gateway_socks)
                                self.gateway_sockets.append(gateway_socks)
                                self.gateway_sockets_info.append({'web_socket': s, 'data': [], db_utils.IMAGE_NAME: ''})

                        elif action == utils.TIMESLOTS_SAVE:  # { token, slots: [{start, end}] }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                slots = db_utils.convert_isoformat_to_datetime(data[db_utils.SLOTS])
                                slots_saved = self.dbConnector.save_timeslots(decoded_token[db_utils.USER], slots)
                                slots = db_utils.convert_datetime_to_isoformat(slots_saved)
                                pck = utils.create_response_packet(json.dumps({'slots': slots, 'status': 200}).encode())

                                # OnSuccess: { slots: [{start, end}], status: 200 }
                                s.sendall(pck)

                        elif action == utils.TIMESLOTS_GET_DAYSLOTS:  # { token, date }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                slots_day = self.dbConnector.get_day_slots(data[db_utils.DATE])
                                slots = db_utils.convert_datetime_to_isoformat(slots_day)
                                pck = utils.create_response_packet(json.dumps({'slots': slots, 'status': 200}).encode())

                                # OnSuccess: { slots: [{start, end, user_id}], status: 200 }
                                s.sendall(pck)

                        elif action == utils.TIMESLOTS_GET_USERSLOTS:  # { token }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                user_slots = self.dbConnector.get_user_slots(decoded_token[db_utils.USER])
                                slots = db_utils.convert_datetime_to_isoformat(user_slots)
                                pck = utils.create_response_packet(json.dumps({'slots': slots, 'status': 200}).encode())

                                # OnSuccess: { slots: [{slot_id, start, end}], status: 200 }
                                s.sendall(pck)

                        elif action == utils.NODETYPES_GET:  # { token }
                            token = data[db_utils.TOKEN]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            else:
                                nodetypes = self.dbConnector.get_nodetypes()
                                pck = utils.create_response_packet(
                                    json.dumps({'nodetypes': nodetypes, 'status': 200}).encode()
                                )

                                # OnSuccess: { nodetypes, status: 201 }
                                s.sendall(pck)

                        elif action == utils.USERS_SIGNUP:  # { email, username, password }
                            res = self.dbConnector.create_user(data)
                            pck = utils.create_response_packet(json.dumps(res).encode())

                            # OnSuccess: { status: 201 }
                            # OnError  : { message, status: 403 }
                            s.sendall(pck)

                        elif action == utils.USERS_LOGIN:  # { email, username }
                            res = self.dbConnector.login_user(data)
                            pck = utils.create_response_packet(json.dumps(res).encode())

                            # OnSuccess: { token, status: 200}
                            # OnError  : { message, status: 401 }
                            s.sendall(pck)

                        elif action == utils.DEBUG_START:  # { token, slot_id }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                if self.sock_debug:
                                    utils.remove_from_list(self.inputs, self.sock_debug)
                                    self.sock_debug.close()
                                log_data = ['=== DEBUG CHANNEL START ===\n===========================\n']
                                pck = utils.create_response_packet(json.dumps({'data': log_data}).encode())
                                self.sock_debug = s
                                self.sock_debug.sendall(pck)

                        elif action == utils.DEBUG_END:  # { token, slot_id }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                log_data = ['=== DEBUG CHANNEL END ===\n=========================\n']
                                if self.sock_debug:
                                    self.experiment_info = {}
                                    pck = utils.create_response_packet(json.dumps({'data': log_data,
                                                                                   'message': 'STOP DEBUG'}).encode())
                                    self.sock_debug.sendall(pck)

                                    utils.remove_from_list(self.inputs, self.sock_debug)
                                    self.sock_debug.close()
                                    self.sock_debug = None

                                    # { status: 204 }
                                    pck = utils.create_response_packet(json.dumps({'status': 204}).encode())
                                    s.sendall(pck)

                        elif action == utils.DEBUG_CLEAR_LOG:  # { token, slot_id }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                self.clear_debug_log(decoded_token[db_utils.USER], slot_id)
                                pck = utils.create_response_packet(json.dumps({'status': 204}).encode())

                                # OnSuccess: { status: 204 }
                                s.sendall(pck)

                        elif action == utils.DEBUG_GET_LOG:  # { token, slot_id }
                            token = data[db_utils.TOKEN]
                            slot_id = data[db_utils.TIMESLOT_ID]
                            decoded_token = utils.decode_auth_token(token)
                            if not decoded_token:
                                utils.send_invalid_token_error(s)
                            elif not self.dbConnector.get_slot_by_id(slot_id):
                                utils.send_invalid_slot_error(s)
                            else:
                                self.send_debug_log(s, decoded_token[db_utils.USER], slot_id)

                        elif action == utils.DEBUG_GATEWAY:  # [ TIMESTAMP, NODE_ID, DATA ]
                            print(data[0], '|', data[1], '|', data[2])
                            if self.experiment_info:
                                self.write_debug_log(data)
                            if self.sock_debug:
                                pck = utils.create_response_packet(json.dumps({'data': data}).encode())
                                self.sock_debug.sendall(pck)

                    else:
                        self.logger.info('TCP DISCON (%s, %d)' % (s.getpeername()[0], s.getpeername()[1]))
                        self.inputs.remove(s)
                        s.close()

            for s in exceptional:
                self.inputs.remove(s)
                s.close()

        for sock in self.inputs:
            self.logger.debug('Exiting. . . Closing [%s]' % sock)
            sock.close()
        self.log_timer.cancel()
        self.sock_tcp.close()
        sys.exit('Exiting. . .')

    def get_image_name(self, s):
        for idx, sublist in enumerate(self.gateway_sockets):
            if s in sublist:
                return self.gateway_sockets_info[idx]['image_name']

    def handle_gateway_request(self, s, data):
        for idx, sublist in enumerate(self.gateway_sockets):
            if s in sublist:
                sublist.remove(s)
                if not sublist:
                    del self.gateway_sockets[idx]
                    self.gateway_sockets_info[idx]['data'].extend(data)
                    web_socket = self.gateway_sockets_info[idx]['web_socket']
                    if web_socket:
                        pck = utils.create_response_packet(json.dumps({'data': self.gateway_sockets_info[idx]['data']})
                                                           .encode())
                        web_socket.sendall(pck)
                    del self.gateway_sockets_info[idx]
                    break
                else:
                    self.gateway_sockets_info[idx]['data'].extend(data)

    def send_flash_request(self, user_id, image_name, node_uids):
        nodetype_id = utils.get_nodetype_by_user_and_image_name(user_id, image_name)

        gateway_info = self.get_gateway_info(node_uids)

        gateways_sockets = []
        for gateway_id, node_uids in gateway_info.items():
            gateway_addr = self.dbConnector.get_gateway_addr(gateway_id)
            ftp.upload_image(gateway_addr[0], image_name, user_id, nodetype_id)

            sock_tcp_gateway = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock_tcp_gateway.connect((gateway_addr[0], gateway_addr[1]))

            data = {db_utils.IMAGE_NAME: image_name, db_utils.NODE_IDS: []}
            for node_uid in node_uids:
                node_id = self.dbConnector.get_node_id_by_uid(node_uid)
                data[db_utils.NODE_IDS].append(node_id)
            pck = utils.create_request_packet(utils.NODES_FLASH, json.dumps(data).encode())
            sock_tcp_gateway.sendall(pck)

            gateways_sockets.append(sock_tcp_gateway)

        return gateways_sockets

        # if self.prompt_flag:
        #   self.prompt.update_node_state()

    def send_erase_request(self, node_uids):
        gateway_info = self.get_gateway_info(node_uids)

        gateways_sockets = []
        for gateway_id, node_uids in gateway_info.items():
            gateway_addr = self.dbConnector.get_gateway_addr(gateway_id)

            sock_tcp_gateway = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock_tcp_gateway.connect((gateway_addr[0], gateway_addr[1]))

            data = {db_utils.NODE_IDS: []}
            for node_uid in node_uids:
                node_id = self.dbConnector.get_node_id_by_uid(node_uid)
                data[db_utils.NODE_IDS].append(node_id)
            pck = utils.create_request_packet(utils.NODES_ERASE, json.dumps(data).encode())
            sock_tcp_gateway.sendall(pck)

            gateways_sockets.append(sock_tcp_gateway)

        return gateways_sockets

    def send_reset_request(self, node_uids):
        gateway_info = self.get_gateway_info(node_uids)

        gateways_sockets = []
        for gateway_id, node_uids in gateway_info.items():
            gateway_addr = self.dbConnector.get_gateway_addr(gateway_id)

            sock_tcp_gateway = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock_tcp_gateway.connect((gateway_addr[0], gateway_addr[1]))

            data = {db_utils.NODE_IDS: []}
            for node_uid in node_uids:
                node_id = self.dbConnector.get_node_id_by_uid(node_uid)
                data[db_utils.NODE_IDS].append(node_id)
            pck = utils.create_request_packet(utils.NODES_RESET, json.dumps(data).encode())
            sock_tcp_gateway.sendall(pck)

            gateways_sockets.append(sock_tcp_gateway)

        return gateways_sockets

    def get_gateway_info(self, node_uids):
        # { gateway_id: [node_uids] }
        gateway_info = {}
        for node_uid in node_uids:
            gateway_id = self.dbConnector.get_gateway_id_by_node_uid(node_uid)
            if gateway_id in gateway_info:
                gateway_info[gateway_id].append(node_uid)
            else:
                gateway_info[gateway_id] = [node_uid]

        return gateway_info

    def init_debug(self, slot_id):
        self.experiment_info[db_utils.TIMESLOT_ID] = slot_id
        self.experiment_info[db_utils.USER_ID] = self.dbConnector.get_slot_by_id(slot_id)[db_utils.USER_ID]
        _dir = os.path.dirname(os.path.abspath(__file__)) + '/' + \
               self.experiment_dir + '/' + \
               self.experiment_info[db_utils.USER_ID] + '/'

        if not os.path.exists(_dir):
            os.makedirs(_dir)

        # Create an empty log for the experiment
        open(_dir + self.experiment_info[db_utils.TIMESLOT_ID] + '.log', 'a').close()

    def write_debug_msg(self, data):
        _dir = os.path.dirname(os.path.abspath(__file__)) + \
               '/' + self.experiment_dir + '/' + \
               self.experiment_info[db_utils.USER_ID] + '/'

        with open(_dir + self.experiment_info[db_utils.TIMESLOT_ID] + '.log', 'a') as f:
            f.write(f'{data[0]}')

    def write_debug_log(self, data):
        _dir = os.path.dirname(os.path.abspath(__file__)) + \
               '/' + self.experiment_dir + '/' + \
               self.experiment_info[db_utils.USER_ID] + '/'

        with open(_dir + self.experiment_info[db_utils.TIMESLOT_ID] + '.log', 'a') as f:
            f.write(f'{data[0]} | {data[1]:35} | {data[2]}\n')

    def clear_debug_log(self, user_id, slot_id):
        _dir = os.path.dirname(os.path.abspath(__file__)) + \
               '/' + self.experiment_dir + '/' + \
               user_id + '/'

        # Erase contents
        with open(_dir + slot_id + '.log', 'w'):
            pass

    def send_debug_log(self, s, user_id, slot_id):
        _dir = os.path.dirname(os.path.abspath(__file__)) + \
               '/' + self.experiment_dir + '/' + \
               user_id + '/'

        file_size = os.path.getsize(_dir + slot_id + '.log')

        with open(_dir + slot_id + '.log', 'rb') as f:
            data = utils.data_size_to_bytes(file_size) + f.read(1022)
            while data:
                s.sendall(data)
                data = f.read(1024)

    def check_timeouts(self):
        slots_start_timeout = self.slotsStartWatch.time_remaining
        if slots_start_timeout < 0:
            slot_start_id = self.dbConnector.check_slots_start()
            if slot_start_id:
                self.init_debug(slot_start_id)
            self.slotsStartWatch.refresh()
        slots_end_timeout = self.slotsEndWatch.time_remaining
        if slots_end_timeout < 0:
            slot_end_id = self.dbConnector.check_slots_end()
            if slot_end_id:
                self.dbConnector.delete_slot_by_id(slot_end_id)
                self.slot_ended()
            self.slotsEndWatch.refresh()

    def get_next_timeout(self):
        slots_start_timeout = self.slotsStartWatch.time_remaining
        slots_end_timeout = self.slotsEndWatch.time_remaining

        new_timeout = min(slots_start_timeout, slots_end_timeout)
        if new_timeout < 0:
            return 0
        return new_timeout

    def slot_ended(self):
        nodes = self.dbConnector.get_nodes()
        if nodes:
            node_uids = []
            for node in nodes:
                node_uids.append(node['_id'])
            gateway_socks = self.send_erase_request(node_uids)
            self.inputs.extend(gateway_socks)
            self.gateway_sockets.append(gateway_socks)
            self.gateway_sockets_info.append(
                {'web_socket': '', 'data': []})

    def stop_thread(self):
        self._stop_thread_event.set()

    def stopped_thread(self):
        return self._stop_thread_event.is_set()

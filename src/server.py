import os
import sys
import socket
import select
import time
import threading
import configparser
import logging.config
from operator import attrgetter

import xml_handler
import gateway
import ftp
import utils
from db import db_connector
import web_handler
import timeoutwatch


class Server:
    """Server class"""

    def __init__(self, gateways_xml_dir, config):
        self.gateways_xml_dir = gateways_xml_dir
        self.gateways_info = {}
        self._stop_thread_event = threading.Event()

        logging.config.fileConfig(os.path.dirname(os.path.abspath(__file__)) + '/' + 'logging.conf')
        self.logger = logging.getLogger('server')

        self.server_cfg = self.read_config(config)
        self.timeouts = [timeoutwatch.TimeoutWatch(float(self.server_cfg['timeout_gateway'])),
                         timeoutwatch.TimeoutWatch(float(self.server_cfg['timeout_nodetypes'])),
                         timeoutwatch.TimeoutWatch(float(self.server_cfg['timeout_locations']))]

        try:
            self.nodetypesMtime = os.path.getmtime(os.path.dirname(os.path.abspath(__file__)) + '/' +
                                                   utils.NODETYPES_FILE)
            self.locationsMtime = os.path.getmtime(os.path.dirname(os.path.abspath(__file__)) + '/' +
                                                   utils.LOCATIONS_FILE)
        except OSError as e:
            sys.exit(e)

        self.dbConnector = db_connector.DBConnector(self.server_cfg['db_ip'], int(self.server_cfg['db_port']))
        if not self.dbConnector.check_connection():
            sys.exit('Could not connect to DB')
        self.dbConnector.insert_nodetypes(os.path.dirname(os.path.abspath(__file__)) + '/' + utils.NODETYPES_FILE)

        self.sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_udp.bind((self.server_cfg['public_ip'], int(self.server_cfg['public_port'])))

        self.parser = xml_handler.XmlParser()

        self._web_handler = web_handler.WebHandler(self.dbConnector, self.server_cfg, self._stop_thread_event)
        self._web_handler.start()

    @staticmethod
    def read_config(config_file):
        server_info = {}
        config = configparser.ConfigParser()

        if not os.path.isfile(config_file):
            sys.exit('Config file not exists\n\tFile path given: ' + config_file)
        else:
            config.read(config_file)

        try:
            for key in config['SERVER']:
                server_info[key] = config['SERVER'][key]
        except KeyError as e:
            sys.exit('Error in config file\n\tKey Error: ' + str(e))

        return server_info

    def run_forever(self):
        inputs = [self.sock_udp]

        for timeout in self.timeouts:
            timeout.start()

        while inputs:
            try:
                self.check_timeouts()
                new_timeout = self.get_next_timeout()
                readable, writable, exceptional = select.select(inputs, [], inputs, new_timeout)

                for s in readable:
                    if s is self.sock_udp:
                        rcv_pck, gateway_addr = self.sock_udp.recvfrom(1024)
                        self.handle_isalive_gateway(rcv_pck, gateway_addr[0])
                for s in exceptional:
                    if s is self.sock_udp:
                        inputs.remove(self.sock_udp)
                        self.sock_udp.close()
            except KeyboardInterrupt:
                self.logger.debug('Exiting. . .')
                self.sock_udp.close()
                self.stop_thread()
                self._web_handler.join()
                sys.exit('Exiting. . .')

    def check_timeouts(self):
        for num, timeout in enumerate(self.timeouts):
            if timeout.time_remaining < 0:
                if num == 0:
                    self.check_gateways_timers()
                elif num == 1:
                    res = self.check_last_modified(utils.NODETYPES_FILE)
                    if res:
                        self.dbConnector.insert_nodetypes(os.path.dirname(os.path.abspath(__file__)) + '/'
                                                          + utils.NODETYPES_FILE)
                        self.send_file_to_gateways(utils.NODETYPES_FILE)
                else:
                    res = self.check_last_modified(utils.LOCATIONS_FILE)
                    if res:
                        self.send_file_to_gateways(utils.LOCATIONS_FILE)
                timeout.refresh()

    def check_gateways_timers(self):
        gateway_ids_to_delete = []
        for _gateway in self.gateways_info:
            if time.time() - self.gateways_info[_gateway].timer > float(self.server_cfg['timer_gateway']):
                gateway_ids_to_delete.append(_gateway)
        if gateway_ids_to_delete:
            for gateway_id in gateway_ids_to_delete:
                _gateway = self.gateways_info.pop(gateway_id, None)
                if _gateway is not None:
                    self.dbConnector.delete_gateway(_gateway.id)

    def check_last_modified(self, file_name):
        try:
            last_modified = os.path.getmtime(os.path.dirname(os.path.abspath(__file__)) + '/' + file_name)
            if (file_name == utils.NODETYPES_FILE) and (last_modified > self.nodetypesMtime):
                self.nodetypesMtime = last_modified
                return True
            elif (file_name == utils.LOCATIONS_FILE) and (last_modified > self.locationsMtime):
                self.locationsMtime = last_modified
                return True
            return False
        except OSError as e:
            print(e)
            return False

    def send_file_to_gateways(self, file_name):
        for _gateway in self.gateways_info:
            addr = self.dbConnector.get_gateway_addr(self.gateways_info[_gateway].id)
            ftp.upload_file(addr, os.path.dirname(os.path.abspath(__file__)) + '/', file_name)

    def get_next_timeout(self):
        _timeout = min(self.timeouts, key=attrgetter('time_remaining'))
        if _timeout.time_remaining < 0:
            return 0
        return _timeout.time_remaining

    def handle_isalive_gateway(self, pck, gateway_ip):
        flag_create = False
        _id, ip, port, seed = utils.segment_packet(pck, utils.GATEWAY_ISALIVE)

        if _id not in self.gateways_info:
            flag_create = True
            self.gateways_info[_id] = gateway.GatewayInfo(_id, time.time())

        flag_update = self.check_seed(_id, seed)
        if flag_update:
            xml_filename = _id + '.xml'
            ftp.download_xml(gateway_ip, self.gateways_xml_dir, xml_filename)
            _gateway = gateway.Gateway(_id, (ip, port))
            gateway_location, nodes = self.parser.get_xml_info(self.gateways_xml_dir + xml_filename)
            for node in nodes:
                node.gateway_id = _id

            if flag_create:     # ( Send_seed = 1 ) > ( local_seed = 0 )
                self.gateways_info[_id].id = _id
                self.dbConnector.insert_gateway(_gateway, gateway_location, nodes)
                # self.dbConnector.update_gateway_location(_id, gateway_location)
                ftp.upload_file(ip, os.path.dirname(os.path.abspath(__file__)) + '/', utils.NODETYPES_FILE)
                ftp.upload_file(ip, os.path.dirname(os.path.abspath(__file__)) + '/', utils.LOCATIONS_FILE)
                self.upload_erase_images(ip)
            else:
                self.dbConnector.update_gateway_nodes(_gateway, nodes)

        self.gateways_info[_id].timer = time.time()

    def check_seed(self, _id, seed):
        try:
            prev_seed = self.gateways_info[_id].seed
        except KeyError:
            return False
        if prev_seed >= seed:
            return False

        self.logger.info('[%s] seed changed (%d) prev (%d)' % (_id, seed, prev_seed))
        self.gateways_info[_id].seed = seed
        return True

    @staticmethod
    def upload_erase_images(ip):
        path = os.path.dirname(os.path.abspath(__file__)) + '/' + utils.ERASE_IMAGES_PATH + '/'
        erase_images = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
        for image in erase_images:
            ftp.upload_erase_image(ip, path, image)

    def stop_thread(self):
        self._stop_thread_event.set()

    def stopped_thread(self):
        return self._stop_thread_event.is_set()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--dir', '-d', default=os.path.dirname(os.path.abspath(__file__)) + '/gateways/',
                        help='Specify alternative output directory')
    parser.add_argument('--config', '-c', default=os.path.dirname(os.path.abspath(__file__)) + '/server.cfg',
                        help='Specify alternative config file')
    args = parser.parse_args()

    if not os.path.exists(args.dir):
        os.makedirs(args.dir)

    server = Server(gateways_xml_dir=args.dir, config=args.config)
    server.run_forever()

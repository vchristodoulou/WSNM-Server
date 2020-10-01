import xml.etree.ElementTree as ET

import node
import db.utils as db_utils
import utils


class XmlParser:
    """XML Parser class"""

    def __init__(self):
        pass

    def get_xml_info(self, xml_file):
        root = self.read_xml(xml_file)
        gateway_location = self.get_gateway_location(root)
        nodes_info = self.get_nodes_info(root)

        return gateway_location, nodes_info

    @staticmethod
    def read_xml(xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        return root

    @staticmethod
    def get_gateway_location(root):
        gateway_location = {}

        for item in root[0]:
            gateway_location[item.tag] = item.text

        return gateway_location

    @staticmethod
    def get_nodes_info(root):
        """Get id, nodetype_id and location of nodes"""
        nodes_info = []
        location = {}
        for _node in root[1]:
            node_type_id = _node.find(db_utils.NODETYPE_ID).text
            node_id = _node.attrib[db_utils.NODE_ID]
            node_location = _node.find(db_utils.LOCATION)
            for item in node_location:
                location[item.tag] = item.text
            nodes_info.append(node.Node(node_id, node_type_id, location))

        return nodes_info


def get_nodetypes(nodetypes_file):
    tree = ET.parse(nodetypes_file)
    root = tree.getroot()

    nodetypes = []
    for key in root:
        nodetype = {}

        nodetype_id = key[0]
        nodetype['_' + nodetype_id.tag] = nodetype_id.text

        platform = key[1]
        nodetype[platform.tag] = platform.text

        processor = key[2]
        nodetype[processor.tag] = processor.text

        memory = key[3]
        _memory = {}
        for item in memory:
            _memory[item.tag] = item.text
        nodetype[memory.tag] = _memory

        radio = key[4]
        _radio = {}
        for item in radio:
            _radio[item.tag] = item.text
        nodetype[radio.tag] = _radio

        sensors = key[5]
        _sensors = []
        for sensor in sensors:
            types = []
            for i in range(len(sensor) - 1):
                types.append(sensor[i + 1].text)
            _sensors.append({sensor[0].tag: sensor[0].text, sensor[1].tag: types})
        nodetype[sensors.tag] = _sensors

        commands = key[6]
        _commands = []
        for command in commands:
            _commands.append({command.tag: command.text})
        nodetype[commands.tag] = _commands

        nodetypes.append(nodetype)

    return nodetypes


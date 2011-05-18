# -*- coding: utf-8 -*-
"""
test_handoff_server.py

test the handoff server process
"""
from base64 import b64encode
import os
import os.path
import shutil
import random
import sys
import time
import unittest
import uuid

from gevent_zeromq import zmq

from diyapi_tools.standard_logging import initialize_logging
from diyapi_tools.greenlet_zeromq_pollster import GreenletZeroMQPollster
from diyapi_tools.greenlet_resilient_client import GreenletResilientClient
from diyapi_tools.greenlet_pull_server import GreenletPULLServer
from diyapi_tools.deliverator import Deliverator

from diyapi_web_server.data_writer_handoff_client import \
        DataWriterHandoffClient

from unit_tests.util import random_string, \
        generate_key, \
        start_database_server,\
        start_data_writer, \
        start_data_reader, \
        start_handoff_server, \
        poll_process, \
        terminate_process

_log_path = "/var/log/pandora/test_handoff_server.log"
_test_dir = os.path.join("/tmp", "handoff_server_test_dir")
_node_count = 10
_database_server_base_port = 8000
_data_writer_base_port = 8100
_data_reader_base_port = 8300
_handoff_server_base_port = 8700

def _generate_node_name(node_index):
    return "node-sim-%02d" % (node_index, )

_local_node_index = 0
_local_node_name = _generate_node_name(_local_node_index)
_disconnected_data_writer_node_index = 3
_node_names = [_generate_node_name(i) for i in range(_node_count)]

_database_server_addresses = [
    "tcp://127.0.0.1:%s" % (_database_server_base_port+i, ) \
    for i in range(_node_count)
]
_database_server_local_addresses = [
    "ipc:///tmp/spideroak-diyapi-database-server-%s/socket" % (
        _generate_node_name( i ),
    ) \
    for i in range(_node_count)
]
_data_writer_addresses = [
    "tcp://127.0.0.1:%s" % (_data_writer_base_port+i, ) \
    for i in range(_node_count)
]
_data_writer_pipeline_addresses = [
    "ipc:///tmp/spideroak-diyapi-data-writer-pipeline-%s/socket" % (
        _generate_node_name( i ),
    ) \
    for i in range(_node_count)
]
_data_reader_addresses = [
    "tcp://127.0.0.1:%s" % (_data_reader_base_port+i, ) \
    for i in range(_node_count)
]
_data_reader_pipeline_addresses = [
    "ipc:///tmp/spideroak-diyapi-data-reader-pipeline-%s/socket" % (
        _generate_node_name( i ),
    ) \
    for i in range(_node_count)
]
_handoff_server_addresses = [
    "ipc:///tmp/spideroak-diyapi-handoff_server-%s/socket" % (
        _generate_node_name( i ),
    ) \
    for i in range(_node_count)
]
_handoff_server_pipeline_addresses = [
    "tcp://127.0.0.1:%s" % (_handoff_server_base_port+i, ) \
    for i in range(_node_count)
]
_client_address = "tcp://127.0.0.1:8900"

def _repository_path(node_name):
    return os.path.join(_test_dir, node_name)

class TestHandoffServer(unittest.TestCase):
    """test message handling in handoff server"""

    def setUp(self):
        self.tearDown()
        self._key_generator = generate_key()

        self._database_server_processes = list()
        self._data_writer_processes = list()
        self._data_reader_processes = list()

        for i in xrange(_node_count):
            node_name = _generate_node_name(i)
            repository_path = _repository_path(node_name)
            os.makedirs(repository_path)
            
            print >> sys.stderr, "starting database server", node_name
            process = start_database_server(
                node_name, 
                _database_server_addresses[i], 
                _database_server_local_addresses[i], 
                repository_path
            )
            poll_result = poll_process(process)
            self.assertEqual(poll_result, None)
            self._database_server_processes.append(process)
            time.sleep(1.0)

            if i == _disconnected_data_writer_node_index:
                print >> sys.stderr, "NOT starting data writer", node_name
            else:
                print >> sys.stderr, "starting data writer", node_name
                process = start_data_writer(
                    node_name, 
                    _data_writer_addresses[i],
                    _data_writer_pipeline_addresses[i],
                    _database_server_addresses[i],
                    repository_path
                )
                poll_result = poll_process(process)
                self.assertEqual(poll_result, None)
                self._data_writer_processes.append(process)
                time.sleep(1.0)

            if i == _disconnected_data_writer_node_index:
                print >> sys.stderr, "NOT starting data reader", node_name
            else:
                print >> sys.stderr, "starting data reader", node_name
                process = start_data_reader(
                    node_name, 
                    _data_reader_addresses[i],
                    _data_reader_pipeline_addresses[i],
                    _database_server_addresses[i],
                    repository_path
                )
                poll_result = poll_process(process)
                self.assertEqual(poll_result, None)
                self._data_reader_processes.append(process)
                time.sleep(1.0)

        self._handoff_server_process = start_handoff_server(
            _node_names,
            _local_node_name, 
            _handoff_server_addresses[_local_node_index],
            _handoff_server_pipeline_addresses[_local_node_index],
            _data_reader_addresses,
            _data_writer_addresses,
            _repository_path(_local_node_name)
        )
        poll_result = poll_process(self._handoff_server_process)
        self.assertEqual(poll_result, None)

        self._context = zmq.context.Context()
        self._pollster = GreenletZeroMQPollster()
        self._deliverator = Deliverator()

        self._pull_server = GreenletPULLServer(
            self._context, 
            _client_address,
            self._deliverator
        )
        self._pull_server.register(self._pollster)

        available_nodes = _node_names[:]
        del available_nodes[_disconnected_data_writer_node_index]
        backup_nodes = random.sample(available_nodes, 2),

        resilient_clients = list()        
        for node_name, address in zip(_node_names, _data_writer_addresses):
            if not node_name in backup_nodes:
                continue
            resilient_client = GreenletResilientClient(
                self._context,
                self._pollster,
                node_name,
                address,
                _local_node_name,
                _client_address,
                self._deliverator,
            )
            resilient_clients.append(resilient_client)

        self._handoff_client = GreenletResilientClient(
            self._context, 
            self._pollster,
            _node_names[_local_node_index],
            _handoff_server_addresses[_local_node_index],
            _local_node_name,
            _client_address,
            self._deliverator,
        )

        self._data_writer_handoff_client = DataWriterHandoffClient(
            _node_names[_disconnected_data_writer_node_index],
            resilient_clients,
            self._handoff_client
        )

        self._pollster.start()

    def tearDown(self):
        if hasattr(self, "_handoff_server_process") \
        and self._handoff_server_process is not None:
            terminate_process(self._handoff_server_process)
            self._handoff_server_process = None
        if hasattr(self, "_data_writer_processes") \
        and self._data_writer_processes is not None:
            for process in self._data_writer_processes:
                terminate_process(process)
            self._data_writer_processes = None
        if hasattr(self, "_data_reader_processes") \
        and self._data_reader_processes is not None:
            for process in self._data_reader_processes:
                terminate_process(process)
            self._data_reader_processes = None
        if hasattr(self, "_database_server_processes") \
        and self._database_server_processes is not None:
            for process in self._database_server_processes:
                terminate_process(process)
            self._database_server_processes = None

        if hasattr(self, "_pollster") \
        and self._pollster is not None:
            self._pollster.kill()
            self._pollster.join(timeout=3.0)
            self._pollster = None
        
        if hasattr(self, "_handoff_client") \
        and self._handoff_client is not None:
            self._handoff_client.close()
            self._handoff_client = None

        if hasattr(self, "_pull_server") \
        and self._pull_server is not None:
            self._pull_server.close()
            self._pull_server = None
 
        if hasattr(self, "_context") \
        and self._context is not None:
            self._context.term()
            self._context = None

        if os.path.exists(_test_dir):
            shutil.rmtree(_test_dir)

    def test_handoff_small_content(self):
        """test retrieving content that fits in a single message"""
        avatar_id = 1001
        key  = self._key_generator.next()
        version_number = 0
        segment_number = 5
        content_size = 64 * 1024
        content_item = random_string(content_size) 
        archive_message_id = uuid.uuid1().hex
        timestamp = time.time()

        total_size = content_size - 42
        file_adler32 = -42
        file_md5 = "ffffffffffffffff"
        segment_adler32 = 32
        segment_md5 = "1111111111111111"

        message = {
            "message-type"      : "archive-key-entire",
            "message-id"        : archive_message_id,
            "avatar-id"         : avatar_id,
            "timestamp"         : timestamp,
            "key"               : key, 
            "version-number"    : version_number,
            "segment-number"    : segment_number,
            "total-size"        : total_size,
            "file-adler32"      : file_adler32,
            "file-md5"          : b64encode(file_md5),
            "segment-adler32"   : segment_adler32,
            "segment-md5"       : b64encode(segment_md5),
        }
        completion_channel = \
            self._data_writer_handoff_client.queue_message_for_send(
                message, data=content_item
            )
        reply, _ = completion_channel.get()
        self.assertEqual(reply["message-type"], "archive-key-final-reply")
        self.assertEqual(reply["result"], "success")
        self.assertEqual(reply["previous-size"], 0)

#    def test_retrieve_large_content(self):
#        """test retrieving content that fits in a multiple messages"""
#        segment_size = 120 * 1024
#        chunk_count = 10
#        total_size = int(1.2 * segment_size * chunk_count)
#        avatar_id = 1001
#        test_data = [random_string(segment_size) for _ in range(chunk_count)]
#        key  = self._key_generator.next()
#        version_number = 0
#        segment_number = 5
#        sequence = 0
#        archive_message_id = uuid.uuid1().hex
#        timestamp = time.time()
#
#        file_adler32 = -42
#        file_md5 = "ffffffffffffffff"
#        segment_adler32 = 32
#        segment_md5 = "1111111111111111"
#
#        message = {
#            "message-type"      : "archive-key-start",
#            "message-id"        : archive_message_id,
#            "avatar-id"         : avatar_id,
#            "timestamp"         : timestamp,
#            "sequence"          : sequence,
#            "key"               : key, 
#            "version-number"    : version_number,
#            "segment-number"    : segment_number,
#            "segment-size"      : segment_size,
#        }
#        reply = send_request_and_get_reply(
#            _node_names[_local_node_index], 
#            _data_writer_addresses[_local_node_index], 
#            _local_node_name,
#            _client_address,
#            message, 
#            data=test_data[sequence]
#        )
#        self.assertEqual(reply["message-id"], archive_message_id)
#        self.assertEqual(reply["message-type"], "archive-key-start-reply")
#        self.assertEqual(reply["result"], "success")
#
#        for content_item in test_data[1:-1]:
#            sequence += 1
#            message = {
#                "message-type"      : "archive-key-next",
#                "message-id"        : archive_message_id,
#                "avatar-id"         : avatar_id,
#                "key"               : key,
#                "sequence"          : sequence,
#            }
#            reply = send_request_and_get_reply(
#                _node_names[_local_node_index], 
#                _data_writer_addresses[_local_node_index], 
#                _local_node_name,
#                _client_address,
#                message, 
#                data=content_item
#            )
#            self.assertEqual(reply["message-id"], archive_message_id)
#            self.assertEqual(reply["message-type"], "archive-key-next-reply")
#            self.assertEqual(reply["result"], "success")
#        
#        sequence += 1
#        message = {
#            "message-type"      : "archive-key-final",
#            "message-id"        : archive_message_id,
#            "avatar-id"         : avatar_id,
#            "key"               : key,
#            "sequence"          : sequence,
#            "total-size"        : total_size,
#            "file-adler32"      : file_adler32,
#            "file-md5"          : b64encode(file_md5),
#            "segment-adler32"   : segment_adler32,
#            "segment-md5"       : b64encode(segment_md5),
#        }
#        reply = send_request_and_get_reply(
#            _node_names[_local_node_index], 
#            _data_writer_addresses[_local_node_index], 
#            _local_node_name,
#            _client_address,
#            message, 
#            data=test_data[sequence]
#        )
#        self.assertEqual(reply["message-id"], archive_message_id)
#        self.assertEqual(reply["message-type"], "archive-key-final-reply")
#        self.assertEqual(reply["result"], "success")
#        self.assertEqual(reply["previous-size"], 0)

if __name__ == "__main__":
    initialize_logging(_log_path)
    unittest.main()


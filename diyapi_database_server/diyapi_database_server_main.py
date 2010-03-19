# -*- coding: utf-8 -*-
"""
diyapi_database_server_main.py

Responds db key lookup requests (mostly from Data Reader)
Responds to db key insert requests (from Data Writer)
Responds to db key list requests from (web components)
Keeps LRU cache of databases open during normal operations.
Databases are simple  key/value stores. 
Every value either points to data or a tombstone and timestamp. 
Every data pointer includes
a timestamp, segment number, size of the segment, 
the combined size of the assembled segments and decoded segments, 
adler32 of the segment, 
and the md5 of the segment.
"""
import sys

from tools import message_driven_process as process
from messages.database_key_insertimport DatabaseKeyInsert

_log_path = u"/var/log/pandora/diyapi_database_server.log"
_queue_name = "database_server"
_routing_key_binding = "database_server.*"

def _handle_key_insert(state, connection, message_body):
    log = logging.getLogger("_handle_key_insert")
    message = DatabaseKeyInsert.unmarshall(message_body)
    log.info("key = %s" % (message.key, ))

_dispatch_table = {
    DatabaseKeyInsert.routing_key : _handle_key_insert
}

if __name__ == "__main__":
    sys.exit(
        process.main(
            _log_path, _queue_name, _routing_key_binding, _dispatch_table
        )
    )

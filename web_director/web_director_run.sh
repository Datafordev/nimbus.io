#!/bin/bash

PROG_DIR="$(cd $(dirname $0) ; pwd)"

exec tproxy -b ${NIMBUS_IO_SERVICE_DOMAIN:?}:${NIMBUSIO_WEB_PUBLIC_READER_PORT:?} \
    $PROG_DIR/web_director_main.py 2>&1

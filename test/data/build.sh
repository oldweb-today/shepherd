#!/bin/bash
CURR_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
echo $CURR_DIR
docker build -t test-shepherd/alpine -f $CURR_DIR/Dockerfile.alpine $CURR_DIR
docker build -t test-shepherd/busybox -f $CURR_DIR/Dockerfile.busybox $CURR_DIR
docker build -t test-shepherd/alpine-derived -f $CURR_DIR/Dockerfile.alpine-derived $CURR_DIR


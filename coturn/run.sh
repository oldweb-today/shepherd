#!/bin/bash

DOCKER_IP=$(tail -n 1 /etc/hosts | cut -f 1)

turnserver --verbose --listening-port=33478 --relay-ip=$DOCKER_IP --realm=dat.webrecorder.io --use-auth-secret --static-auth-secret=TURNSECRET --rest-api-separator=. --fingerprint --no-dtls


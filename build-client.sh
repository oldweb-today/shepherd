#!/bin/bash

CURR_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )

cd $CURR_DIR/shepherd-client
yarn install
yarn run build-dev
cp ./dist/shepherd-client.bundle.js ../shepherd/static_base/

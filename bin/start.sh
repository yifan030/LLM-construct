#!/bin/bash
CURRENT_PATH=`cd $(dirname $0);pwd`
cd ${CURRENT_PATH}/..
nohup  python service/kbqa_service.py > /dev/null 2>&1 &

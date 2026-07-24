#!/bin/bash
PIDS=$(ps -aef | grep kbqa_service.py | grep -v grep | awk '{print $2}')
for pid in $PIDS; do
  echo "service pid: $pid"
  kill -9 $pid
done


#!/bin/bash
set -euo pipefail
exec 3<>/dev/tcp/127.0.0.1/8317
printf 'GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3
read -r -t 3 status <&3
[[ "$status" == *" 200 "* ]]

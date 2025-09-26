#!/bin/bash

detected_ip=$(wget -qO- https://ipecho.net/plain)

if [ -z "$detected_ip" ]; then
    exit 0
fi

if test -f /tmp/public_ip; then
    previous_ip=$(cat /tmp/public_ip)
else
    previous_ip="0.0.0.0"
fi

if [ "$detected_ip" != "$previous_ip" ]; then
    curl --user moonpie.dedyn.io:th8xxpESfJWUeDoRFrQ5WkQDbMb9 https://update.dedyn.io/
    echo "$detected_ip" > /tmp/public_ip
fi

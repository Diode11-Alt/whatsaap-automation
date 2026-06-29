#!/bin/bash

echo "Starting DIODE WhatsApp Bridge..."
cd whatsapp-bridge
./bridge &
BRIDGE_PID=$!

echo "Waiting for bridge to initialize..."
sleep 3

echo "Starting DIODE WhatsApp Auto-Reply Bot..."
cd ..
PYTHONUNBUFFERED=1 python3 auto_reply.py

echo "Bot exited. Killing bridge..."
kill $BRIDGE_PID

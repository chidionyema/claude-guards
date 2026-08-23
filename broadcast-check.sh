#!/bin/bash
# Broadcast to all active Claude sessions via their MCP environment

BROADCAST_FILE="/Users/chidionyema/.claude/BROADCAST_URGENT.txt"

if [ -f "$BROADCAST_FILE" ]; then
  echo "🔴 URGENT BROADCAST RECEIVED"
  echo ""
  cat "$BROADCAST_FILE"
  echo ""
  echo "Action required: read above and ACK on ESTATE_BOARD.jsonl"
fi

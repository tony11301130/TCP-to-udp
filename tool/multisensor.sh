#!/bin/bash

PORT=5005
IFACE="ens192"

echo "[INFO] 啟動 UDP 多來源監控器..."
prev_errors=$(netstat -su | grep "packet receive errors" | awk '{print $1}')
prev_received=$(netstat -su | grep "packets received" | awk '{print $1}')
prev_rx_dropped=$(ethtool -S $IFACE 2>/dev/null | grep -w 'rx_dropped' | awk '{print $2}')
prev_rx_missed=$(ethtool -S $IFACE 2>/dev/null | grep -w 'rx_missed' | awk '{print $2}')

# 若無法取得 ethtool 統計，設為 0
prev_rx_dropped=${prev_rx_dropped:-0}
prev_rx_missed=${prev_rx_missed:-0}

while true; do
  sleep 1

  cur_errors=$(netstat -su | grep "packet receive errors" | awk '{print $1}')
  cur_received=$(netstat -su | grep "packets received" | awk '{print $1}')
  cur_rx_dropped=$(ethtool -S $IFACE 2>/dev/null | grep -w 'rx_dropped' | awk '{print $2}')
  cur_rx_missed=$(ethtool -S $IFACE 2>/dev/null | grep -w 'rx_missed' | awk '{print $2}')
  cur_rx_dropped=${cur_rx_dropped:-0}
  cur_rx_missed=${cur_rx_missed:-0}

  error_diff=$((cur_errors - prev_errors))
  pps=$((cur_received - prev_received))
  drop_diff=$((cur_rx_dropped - prev_rx_dropped))
  miss_diff=$((cur_rx_missed - prev_rx_missed))

  # RX Queue 從 /proc/net/udp 取出（單一 port）
  rxq_hex=$(grep -i ":$(printf '%04X' $PORT)" /proc/net/udp | awk '{print $5}' | cut -d':' -f2)
  if [[ -n "$rxq_hex" ]]; then
    rxq=$((16#$rxq_hex))
  else
    rxq=0
  fi

  prev_errors=$cur_errors
  prev_received=$cur_received
  prev_rx_dropped=$cur_rx_dropped
  prev_rx_missed=$cur_rx_missed

  timestamp=$(date +"%H:%M:%S")

  if [[ "$error_diff" -gt 0 ]]; then
    echo -e "\033[0;31m[$timestamp] ERROR↑ | RXQ: ${rxq}B | PPS: $pps | ΔERR: +$error_diff | ΔDrop: +$drop_diff | ΔMiss: +$miss_diff\033[0m"
  else
    echo "[$timestamp] OK     | RXQ: ${rxq}B | PPS: $pps | ΔERR: +$error_diff | ΔDrop: +$drop_diff | ΔMiss: +$miss_diff"
  fi
done

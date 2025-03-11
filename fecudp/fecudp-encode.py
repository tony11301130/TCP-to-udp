import socket
import threading
import time
import logging
import reedsolo

"""
FEC UDP 傳輸（使用 Reed-Solomon 編碼）

此程式碼實作了一個 UDP 代理伺服器，從來源接收 UDP 封包，並應用 Reed-Solomon
前向錯誤更正（FEC）來提高數據的可靠性，然後將原始封包和編碼封包轉發到目標地址。

### 功能:
1. 監聽 UDP 套接字以接收封包。
2. 緩存封包，當累積到指定數量或超時後進行 FEC 編碼。
3. 使用 Reed-Solomon 編碼來生成冗餘封包進行錯誤更正。
4. 拆分過大的封包以避免超過 UDP MTU 大小。
5. 將原始和編碼封包一起轉發到指定的目標 IP 和端口。

### 設定:
- `UDP_LISTEN_IP` – 監聽封包的 IP 地址。
- `UDP_LISTEN_PORT` – 監聽封包的端口。
- `UDP_FORWARD_IP` – 目標封包轉發的 IP 地址。
- `UDP_FORWARD_PORT` – 目標封包轉發的端口。
- `FEC_ORIGINAL_PACKETS` – 累積多少個封包後觸發 FEC 編碼。
- `FEC_REDUNDANT_PACKETS` – 用於錯誤更正的冗餘封包數量。
- `FEC_TIMEOUT` – 超時（秒），在超時後自動觸發 FEC 編碼。

### 使用方式:
1. 確認已安裝 `reedsolo` 套件:
   ```bash
   pip install reedsolo
   ```
2. 執行程式:
   ```bash
   python fec_udp_proxy.py
   ```
3. 發送 UDP 封包至 `UDP_LISTEN_IP:UDP_LISTEN_PORT`
4. 程式將把封包轉發到 `UDP_FORWARD_IP:UDP_FORWARD_PORT`
"""

# === 設定 ===
UDP_LISTEN_IP = '127.0.0.1'  # 監聽所有網路介面
UDP_LISTEN_PORT = 5000
UDP_FORWARD_IP = '172.16.1.92'
UDP_FORWARD_PORT = 7000
LOCAL_UDP_IP = '172.16.1.91'

# FEC 參數
FEC_ORIGINAL_PACKETS = 10  # 累積多少個封包後觸發 FEC 編碼
FEC_REDUNDANT_PACKETS = 10  # 生成多少個冗餘封包
FEC_BATCH_SIZE = FEC_ORIGINAL_PACKETS
FEC_TIMEOUT = 0.1  # 最多等待多少秒觸發 FEC 編碼

# 初始化 Reed-Solomon 編碼器
fec = reedsolo.RSCodec(FEC_REDUNDANT_PACKETS)

# 建立 socket 並綁定到監聽地址
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))

# 儲存封包的緩存
packets = []
packets_lock = threading.Lock()
last_send_time = [time.time()]

# === FEC 計時器 (處理超時) ===
def fec_timer_trigger():
    """
    定期檢查是否達到超時。
    如果超時，則發送當前緩存的封包（必要時補零）。
    """
    while True:
        time.sleep(0.01)  # 每 10 毫秒檢查一次
        elapsed_time = time.time() - last_send_time[0]

        if elapsed_time > FEC_TIMEOUT:
            with packets_lock:
                if packets:
                    logging.debug(f"FEC 超時，當前封包數量: {len(packets)}")
                    fec_encode_and_send()
                    packets.clear()
                    last_send_time[0] = time.time()

# === FEC 編碼與傳輸 ===
def fec_encode_and_send():
    """
    使用 Reed-Solomon 對累積封包進行編碼。
    如果累積的封包數量不足，則補零。
    通過 UDP 轉發原始封包和編碼封包。
    """
    with packets_lock:
        if len(packets) < FEC_BATCH_SIZE:
            missing = FEC_BATCH_SIZE - len(packets)
            logging.debug(f"補充 {missing} 個封包")
            packets.extend([b'\x00' * len(packets[0])] * missing)

        try:
            # Reed-Solomon 編碼
            encoded_data = fec.encode(b"".join(packets))

            # 將編碼數據切分成封包
            udp_packets = packets + [encoded_data[i:i + len(packets[0])] for i in range(0, len(encoded_data), len(packets[0]))]

            # 通過 UDP 傳輸封包
            for packet in udp_packets:
                if len(packet) > 1472:
                    for i in range(0, len(packet), 1472):
                        udp_socket.sendto(packet[i:i+1472], (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                else:
                    udp_socket.sendto(packet, (UDP_FORWARD_IP, UDP_FORWARD_PORT))

            logging.debug(f"已發送 {len(udp_packets)} 個 FEC 封包")

        except Exception as e:
            logging.error(f"FEC 編碼或發送時發生錯誤: {e}")

# === 封包處理 ===
def handle_udp_packet():
    """
    監聽來自 UDP 的封包。
    當達到指定數量時觸發 FEC 編碼。
    """
    while True:
        data, addr = udp_socket.recvfrom(4096)
        logging.debug(f"收到來自 {addr} 的封包，大小: {len(data)}")

        with packets_lock:
            packets.append(data)
            logging.debug(f"緩存封包數量: {len(packets)}")

            if len(packets) >= FEC_BATCH_SIZE:
                logging.debug(f"FEC 被觸發: {len(packets)} 個封包")
                fec_encode_and_send()
                packets.clear()
                last_send_time[0] = time.time()

# === 啟動執行緒 ===
threading.Thread(target=fec_timer_trigger, daemon=True).start()
threading.Thread(target=handle_udp_packet, daemon=True).start()

# === 保持程式運行 ===
logging.info(f"正在監聽 {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}，並轉發到 {UDP_FORWARD_IP}:{UDP_FORWARD_PORT}")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logging.info("正在關閉...")
    udp_socket.close()

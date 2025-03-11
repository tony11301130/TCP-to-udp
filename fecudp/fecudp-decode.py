import socket
import logging
import reedsolo

"""
FEC UDP 解碼器（使用 Reed-Solomon）

此程式碼實作了一個 UDP 伺服器，接收來自 FEC 編碼的封包，並使用 Reed-Solomon 進行解碼，
以還原丟失或損壞的封包，然後將解碼後的封包轉發到另一個指定的 IP 和端口。

### 功能:
1. 監聽 UDP 套接字來接收封包。
2. 使用 Reed-Solomon 來進行 FEC 解碼。
3. 處理封包損壞或丟失的情況，並嘗試還原原始數據。
4. 顯示解碼後的封包內容。
5. 成功解碼後，將封包通過 UDP 轉發到另一個指定的目標 IP 和端口。

### 設定:
- `UDP_LISTEN_IP` – 監聽封包的 IP 地址。
- `UDP_LISTEN_PORT` – 監聽封包的端口。
- `FEC_ORIGINAL_PACKETS` – 原始封包數量。
- `FEC_REDUNDANT_PACKETS` – 冗餘封包數量。
- `UDP_FORWARD_IP` – 轉發封包的目標 IP 地址。
- `UDP_FORWARD_PORT` – 轉發封包的目標端口。

### 使用方式:
1. 確認已安裝 `reedsolo` 套件:
   ```bash
   pip install reedsolo
   ```
2. 執行程式:
   ```bash
   python fec_udp_decoder.py
   ```
3. 監聽 UDP 封包並解碼，成功後自動轉發到目標 IP。
"""

# === 設定 ===
UDP_LISTEN_IP = '0.0.0.0'
UDP_LISTEN_PORT = 7000
FEC_ORIGINAL_PACKETS = 10
FEC_REDUNDANT_PACKETS = 10

# 轉發目標設定
UDP_FORWARD_IP = '172.16.1.93'  # 目標 IP
UDP_FORWARD_PORT = 5000          # 目標端口

# 初始化 Reed-Solomon 編碼器
fec = reedsolo.RSCodec(FEC_REDUNDANT_PACKETS)

# 設定日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 建立 socket 並綁定到監聽地址
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))

# 建立用於轉發的 socket
forward_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# === 解碼處理 ===
def handle_udp_packet():
    packets = []
    logging.info("等待封包中...")
    while True:
        try:
            logging.debug("等待接收封包...")
            data, addr = udp_socket.recvfrom(4096)
            logging.info(f"✔️ 收到來自 {addr} 的封包，大小: {len(data)} bytes")

            packets.append(data)
            logging.debug(f"當前緩存封包數量: {len(packets)}")

            if len(packets) >= FEC_ORIGINAL_PACKETS + FEC_REDUNDANT_PACKETS:
                try:
                    logging.info("🔎 收集到足夠封包，開始進行 FEC 解碼...")
                    # 將封包合併進行解碼
                    decoded_data = fec.decode(b"".join(packets))
                    logging.info(f"✅ 解碼成功，原始數據大小: {len(decoded_data)} bytes")

                    # 在這裡處理解碼後的數據
                    print(f"[DECODED DATA]: {decoded_data}")

                    # === 轉發解碼後的封包 ===
                    logging.debug("➡️ 開始轉發封包...")
                    if len(decoded_data) > 1472:
                        for i in range(0, len(decoded_data), 1472):
                            forward_socket.sendto(decoded_data[i:i+1472], (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                            logging.debug(f"已轉發封包切片: {i}-{i+1472} bytes")
                    else:
                        forward_socket.sendto(decoded_data, (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                        logging.debug(f"已轉發完整封包，大小: {len(decoded_data)} bytes")

                    logging.info(f"✅ 成功轉發封包至 {UDP_FORWARD_IP}:{UDP_FORWARD_PORT}")

                    packets.clear()
                except reedsolo.ReedSolomonError as e:
                    logging.error(f"❌ FEC 解碼失敗: {e}")
                    packets.clear()

        except Exception as e:
            logging.error(f"❗ 收包或解碼過程中發生錯誤: {e}")

# 啟動解碼器
logging.info(f"🚀 正在監聽 {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}...")
try:
    handle_udp_packet()
except KeyboardInterrupt:
    logging.info("🛑 關閉解碼器...")
    udp_socket.close()
    forward_socket.close()

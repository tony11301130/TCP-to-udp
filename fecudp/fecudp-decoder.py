import socket
import logging
import reedsolo
import struct

# === 設定 ===
UDP_LISTEN_IP = '0.0.0.0'
UDP_LISTEN_PORT = 7000
FEC_ORIGINAL_PACKETS = 1
FEC_REDUNDANT_PACKETS = 1

# 轉發目標設定
UDP_FORWARD_IP = '192.168.1.94'
UDP_FORWARD_PORT = 5000

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
    packets = {}
    logging.info("等待封包中...")
    while True:
        try:
            logging.debug("等待接收封包...")
            data, addr = udp_socket.recvfrom(4096)
            logging.info(f"✔️ 收到來自 {addr} 的封包，大小: {len(data)} bytes")

            if len(data) < 4:
                logging.warning("封包長度過短，丟棄該封包")
                continue

            # 解析序號 (使用前 4 個位元組作為序號)
            seq_num = struct.unpack('!I', data[:4])[0]
            payload = data[4:]

            packets[seq_num] = payload
            logging.debug(f"封包序號: {seq_num}, 當前緩存封包數量: {len(packets)}")

            # 當封包數量達到 FEC 原始封包 + 冗餘封包時觸發解碼
            if len(packets) >= FEC_ORIGINAL_PACKETS + FEC_REDUNDANT_PACKETS:
                try:
                    logging.info("🔎 收集到足夠封包，開始進行 FEC 解碼...")

                    # 依照序號排序封包
                    sorted_packets = [packets[i] for i in sorted(packets.keys())]

                    # FEC decode 回傳 tuple，取出第一個元素作為解碼結果
                    decoded_result = fec.decode(b"".join(sorted_packets))
                    if isinstance(decoded_result, tuple) and len(decoded_result) > 0:
                        decoded_data = decoded_result[0].strip(b'\x00')
                    else:
                        decoded_data = decoded_result.strip(b'\x00')

                    logging.info(f"✅ 解碼成功，原始數據大小: {len(decoded_data)} bytes")

                    # === 轉發解碼後的封包 ===
                    logging.debug("➡️ 開始轉發封包...")

                    if len(decoded_data) > 1472:
                        for i in range(0, len(decoded_data), 1472):
                            forward_socket.sendto(decoded_data[i:i + 1472] + b'\n', (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                            logging.debug(f"已轉發封包切片: {i}-{i + 1472} bytes")
                    elif len(decoded_data) > 0:
                        forward_socket.sendto(decoded_data + b'\n', (UDP_FORWARD_IP, UDP_FORWARD_PORT))
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

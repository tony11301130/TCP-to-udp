import socket
import threading
import time
import logging
import reedsolo
import struct
import copy

# 設定日誌輸出
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# === 設定 ===
UDP_LISTEN_IP = '0.0.0.0'
UDP_LISTEN_PORT = 5000
UDP_FORWARD_IP = '172.16.1.92'
UDP_FORWARD_PORT = 7000

# FEC 參數
FEC_ORIGINAL_PACKETS = 2
FEC_REDUNDANT_PACKETS = 1
FEC_BATCH_SIZE = FEC_ORIGINAL_PACKETS
FEC_TIMEOUT = 0.1

fec = reedsolo.RSCodec(FEC_REDUNDANT_PACKETS)

# 建立 socket
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))

packets = []
packets_lock = threading.Lock()
last_send_time = [time.time()]
packet_counter = 0

# === FEC 計時器 ===
def fec_timer_trigger():
    while True:
        time.sleep(0.01)
        elapsed_time = time.time() - last_send_time[0]

        if elapsed_time > FEC_TIMEOUT:
            with packets_lock:
                if len(packets) > 0:
                    logging.debug(f"FEC 超時觸發，封包數量: {len(packets)}")
                    try:
                        temp_packets = copy.deepcopy(packets)
                        fec_encode_and_send(temp_packets)
                        packets.clear()
                        last_send_time[0] = time.time()
                    except Exception as e:
                        logging.error(f"FEC 編碼或發送過程中出現錯誤: {e}")

# === FEC 編碼與傳輸 ===
def fec_encode_and_send(temp_packets):
    # 取得最大封包大小
    max_size = max(len(packet) for packet in temp_packets)
    
    # 將封包補齊到相同長度
    for i in range(len(temp_packets)):
        if len(temp_packets[i]) < max_size:
            padding = max_size - len(temp_packets[i])
            temp_packets[i] += b'\x00' * padding

    # 若封包不足 X 個，補充空封包
    if len(temp_packets) < FEC_BATCH_SIZE:
        missing = FEC_BATCH_SIZE - len(temp_packets)
        temp_packets.extend([b'\x00' * max_size] * missing)
        logging.debug(f"補充 {missing} 個封包，大小: {max_size}")

    try:
        logging.debug("開始 FEC 編碼")
        encoded_packets = fec.encode(b"".join(temp_packets))
        packet_size = max_size

        # 分割成每個封包大小
        encoded_packets = [
            encoded_packets[i:i + packet_size] for i in range(0, len(encoded_packets), packet_size)
        ]

        # 合併原始封包 + 冗餘封包
        udp_packets = temp_packets[:FEC_ORIGINAL_PACKETS] + encoded_packets[:FEC_REDUNDANT_PACKETS]

        # 發送封包
        sent_count = 0
        for i, packet in enumerate(udp_packets):
            seq_num = struct.pack('!I', i)
            packet = seq_num + packet

            udp_socket.sendto(packet, (UDP_FORWARD_IP, UDP_FORWARD_PORT))
            sent_count += 1
            logging.debug(f"發送封包序號 {i}，大小: {len(packet)}")

        logging.info(f"✅ 成功發送 {sent_count} 個封包 (應為 {FEC_ORIGINAL_PACKETS + FEC_REDUNDANT_PACKETS})")

    except Exception as e:
        logging.error(f"FEC 編碼或發送時發生錯誤: {e}")

# === 封包處理 ===
def handle_udp_packet():
    global packet_counter
    logging.info("開始接收 UDP 封包...")
    while True:
        try:
            data, addr = udp_socket.recvfrom(4096)
            logging.debug(f"收到來自 {addr} 的封包，大小: {len(data)}")

            with packets_lock:
                if packets and len(data) != len(packets[0]):
                    logging.warning(f"封包大小不同，將其補齊 (收到: {len(data)}, 預期: {len(packets[0])})")
                    data += b'\x00' * (len(packets[0]) - len(data))

                # 加入序號
                seq_num = struct.pack('!I', packet_counter)
                packet_counter += 1

                packets.append(data)
                logging.debug(f"封包緩存數量: {len(packets)}")

                # 收集到 X 個封包時觸發 FEC 編碼
                if len(packets) >= FEC_BATCH_SIZE:
                    logging.debug(f"FEC 觸發 (封包數量: {len(packets)})")
                    try:
                        temp_packets = copy.deepcopy(packets)
                        fec_encode_and_send(temp_packets)
                        packets.clear()
                        last_send_time[0] = time.time()
                    except Exception as e:
                        logging.error(f"封包處理與發送時發生錯誤: {e}")

        except Exception as e:
            logging.error(f"接收封包時發生錯誤: {e}")

# === 啟動執行緒 ===
threading.Thread(target=fec_timer_trigger, daemon=True).start()
threading.Thread(target=handle_udp_packet, daemon=True).start()

# === 保持程式運行 ===
logging.info(f"正在監聽 {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}，並轉發到 {UDP_FORWARD_IP}:{UDP_FORWARD_PORT}")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logging.info("正在關閉fec encoder...")
    udp_socket.close()

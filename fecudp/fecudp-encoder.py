import socket
import threading
import time
import logging
import reedsolo
import copy
import struct

# 設定日誌輸出
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# === 設定 ===
UDP_LISTEN_IP = '0.0.0.0'  # 監聽所有網路介面
UDP_LISTEN_PORT = 5000
UDP_FORWARD_IP = '172.16.1.92'
UDP_FORWARD_PORT = 7000
LOCAL_UDP_IP = '172.16.1.91'

# FEC 參數
FEC_ORIGINAL_PACKETS = 1
FEC_REDUNDANT_PACKETS = 1
FEC_BATCH_SIZE = FEC_ORIGINAL_PACKETS
FEC_TIMEOUT = 0.1

fec = reedsolo.RSCodec(FEC_REDUNDANT_PACKETS)

udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    udp_socket.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))
    logging.info(f"成功綁定到 {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}")
except Exception as e:
    logging.error(f"無法綁定到 {UDP_LISTEN_IP}:{UDP_LISTEN_PORT}: {e}")

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
                if packets:
                    logging.debug(f"FEC 超時觸發，封包數量: {len(packets)}")
                    try:
                        temp_packets = copy.deepcopy(packets)
                        fec_encode_and_send(temp_packets)
                        packets.clear()
                        last_send_time[0] = time.time()
                        logging.debug("FEC 編碼與發送完成")
                    except Exception as e:
                        logging.error(f"FEC 編碼或發送過程中出現錯誤: {e}")
                else:
                    logging.debug("FEC 超時觸發但無封包需要處理")

# === FEC 編碼與傳輸 ===
def fec_encode_and_send(temp_packets):
    if len(temp_packets) < FEC_BATCH_SIZE:
        missing = FEC_BATCH_SIZE - len(temp_packets)
        packet_size = len(temp_packets[0]) if temp_packets else 0
        logging.debug(f"補充 {missing} 個封包 (每個大小: {packet_size})")
        if packet_size > 0:
            temp_packets.extend([b'\x00' * packet_size] * missing)
        else:
            logging.warning("無法補充封包，因為封包大小為 0")

    try:
        logging.debug("開始 FEC 編碼")
        encoded_data = fec.encode(b"".join(temp_packets))
        encoded_packets = [encoded_data[i:i + len(temp_packets[0])] for i in range(0, len(encoded_data), len(temp_packets[0]))]

        # 限制封包發送數量為 FEC_ORIGINAL_PACKETS + FEC_REDUNDANT_PACKETS
        udp_packets = temp_packets[:FEC_ORIGINAL_PACKETS] + encoded_packets[:FEC_REDUNDANT_PACKETS]

        sent_count = 0
        for i, packet in enumerate(udp_packets):
            # 加入序號 (使用 struct 封裝成 4 個位元組)
            seq_num = struct.pack('!I', i)
            packet = seq_num + packet

            if len(packet) > 1472:
                for j in range(0, len(packet), 1472):
                    udp_socket.sendto(packet[j:j+1472], (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                    sent_count += 1
            else:
                udp_socket.sendto(packet, (UDP_FORWARD_IP, UDP_FORWARD_PORT))
                sent_count += 1

        logging.debug(f"成功發送 {sent_count} 個封包 (應為 {FEC_ORIGINAL_PACKETS + FEC_REDUNDANT_PACKETS})")

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
                    logging.warning(f"封包大小不同，仍將其加入緩存 (收到: {len(data)}, 預期: {len(packets[0])})")

                # 加入序號
                seq_num = struct.pack('!I', packet_counter)
                packet_counter += 1

                packets.append(seq_num + data)
                logging.debug(f"封包緩存數量: {len(packets)}")

                if len(packets) >= FEC_BATCH_SIZE:
                    logging.debug(f"FEC 觸發 (封包數量: {len(packets)})")
                    try:
                        temp_packets = copy.deepcopy(packets)
                        fec_encode_and_send(temp_packets)
                        packets.clear()
                        last_send_time[0] = time.time()
                        logging.debug("封包處理與發送完成")
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
    logging.info("正在關閉...")
    udp_socket.close()

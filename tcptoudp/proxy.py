import socket
import threading
import struct
import reedsolo  # Reed-Solomon FEC
import time
import logging

# 設定日誌記錄
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 設定參數
TCP_HOST = '0.0.0.0'  # 監聽所有網路介面
TCP_PORT = 5000        # TCP 伺服器監聽的埠號
UDP_HOST = '172.16.1.92'  # 目標 UDP 伺服器的 IP 地址
UDP_PORT = 6000        # 目標 UDP 伺服器的埠號
LOCAL_UDP_IP = '172.16.1.91'  # 指定使用 ens192（本機 IP）

# FEC 參數（可調整）
FEC_ORIGINAL_PACKETS = 10  # 原始封包數量
FEC_REDUNDANT_PACKETS = 5  # 冗餘封包數量
FEC_BATCH_SIZE = FEC_ORIGINAL_PACKETS  # FEC 需要多少個封包才觸發
FEC_TIMEOUT = 0.1  # 最多等待 100ms，如果沒湊齊 FEC_BATCH_SIZE 個封包就直接發送

# 初始化 Reed-Solomon FEC
fec = reedsolo.RSCodec(FEC_REDUNDANT_PACKETS)

def fec_timer_trigger(packets, last_send_time, udp_socket):
    """ 獨立執行緒定期檢查 FEC 是否超時 """
    while True:
        time.sleep(0.01)  # 每 10ms 檢查一次
        elapsed_time = time.time() - last_send_time[0]
        if packets and elapsed_time > FEC_TIMEOUT:
            logging.debug("FEC Timeout reached, sending packets")
            fec_encode_and_send(packets, udp_socket)
            packets.clear()
            last_send_time[0] = time.time()

def fec_encode_and_send(packets, udp_socket):
    """ 執行 FEC 編碼並發送 UDP 封包，若封包不足則補零 """
    missing_packets = FEC_BATCH_SIZE - len(packets)
    if missing_packets > 0:
        logging.debug(f"Padding {missing_packets} empty packets to meet FEC requirement")
        for _ in range(missing_packets):
            packets.append(b'\x00' * len(packets[0]))  # 補零

    fec_encoded_packets = fec.encode(b"".join(packets))  # 產生冗餘數據
    udp_packets = packets + [fec_encoded_packets[i:i+len(packets[0])] for i in range(0, len(fec_encoded_packets), len(packets[0]))]
    for udp_packet in udp_packets:
        if len(udp_packet) > 1472:
            for i in range(0, len(udp_packet), 1472):
                udp_socket.sendto(udp_packet[i:i+1472], (UDP_HOST, UDP_PORT))
        else:
            udp_socket.sendto(udp_packet, (UDP_HOST, UDP_PORT))
    logging.debug("Sent FEC protected packets")

# 處理 TCP 連線並將資料轉發至 UDP
def handle_tcp_client(client_socket, udp_socket, packets, last_send_time):
    try:
        buffer = b""  # 用來處理分批 TCP 數據
        seq_num = 0  # 初始化序號
        
        logging.debug("Started handling new TCP connection")
        while True:
            data = client_socket.recv(4096)  # 增加接收緩衝區大小
            if not data:
                logging.debug("TCP connection closed by client")
                break  # 連線關閉

            buffer += data  # 將接收的 TCP 數據追加到緩衝區
            logging.debug(f"Received data: {data}")

            while b"\n" in buffer:
                packet, buffer = buffer.split(b"\n", 1)  # 擷取完整封包
                logging.debug(f"Processing packet: {packet}")

                # 建立 TCP 標頭
                tcp_header = struct.pack("!I I H H H H H H", 
                                         seq_num,  
                                         0,  
                                         5 << 12,  
                                         0b101000,  
                                         1024,  
                                         0,  
                                         0,  
                                         len(packet))  

                full_packet = tcp_header + packet
                packets.append(full_packet)  # 儲存封包
                seq_num += 1
                logging.debug(f"Buffered {len(packets)} packets")

                # 當達到批次大小時，立即發送
                if len(packets) >= FEC_BATCH_SIZE:
                    logging.debug(f"FEC triggered by batch size: {len(packets)} packets")
                    fec_encode_and_send(packets, udp_socket)
                    packets.clear()
                    last_send_time[0] = time.time()
    except Exception as e:
        logging.error(f"Error: {e}")
    finally:
        client_socket.close()  # 關閉 TCP 連線

# 啟動 TCP 轉 UDP 代理伺服器
def start_proxy():
    # 建立 UDP Socket，並綁定到特定網卡（ens192）
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind((LOCAL_UDP_IP, 0))  # 指定 UDP 來源 IP
    
    # 建立 TCP 伺服器 Socket
    tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_server.bind((TCP_HOST, TCP_PORT))  # 綁定 TCP 地址與埠號
    tcp_server.listen(5)  # 設定最大佇列長度
    logging.info(f"TCP to UDP proxy running on {TCP_HOST}:{TCP_PORT}, forwarding to {UDP_HOST}:{UDP_PORT} via {LOCAL_UDP_IP}")
    
    packets = []  # 全域 FEC 封包緩存
    last_send_time = [time.time()]  # 使用可變數確保多執行緒可更新

    # 啟動獨立執行緒來監控 FEC 超時
    threading.Thread(target=fec_timer_trigger, args=(packets, last_send_time, udp_socket), daemon=True).start()
    
    while True:
        client_socket, addr = tcp_server.accept()  # 接受新的 TCP 連線
        logging.info(f"Accepted connection from {addr}")
        client_handler = threading.Thread(target=handle_tcp_client, args=(client_socket, udp_socket, packets, last_send_time))
        client_handler.start()  # 啟動新執行緒來處理 TCP 連線

if __name__ == "__main__":
    start_proxy()  # 啟動代理伺服器

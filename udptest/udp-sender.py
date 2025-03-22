import socket
import time

# ========== 設定區 ==========
TARGET_IP = '192.168.1.91'
TARGET_PORT = 5000
PACKET_SIZE = 1400       # 封包大小（byte）
PACKET_COUNT = 10000     # 發送封包總數
INTERVAL = 0.00044       # 發送間隔時間（秒） -> 2200 封包/秒 (約26 Mbps)
# ===========================

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

success_count = 0
packet_data = b'X' * PACKET_SIZE  # 模擬 1400 bytes 封包

print(f"Sending {PACKET_COUNT} UDP packets to {TARGET_IP}:{TARGET_PORT} at ~26 Mbps")

start_time = time.time()

for i in range(PACKET_COUNT):
    try:
        sock.sendto(packet_data, (TARGET_IP, TARGET_PORT))
        success_count += 1
        time.sleep(INTERVAL)
    except Exception as e:
        print(f"Failed to send packet {i + 1}: {e}")

sock.close()

end_time = time.time()
duration = end_time - start_time

print(f"Sent {success_count}/{PACKET_COUNT} packets successfully")
print(f"Total duration: {duration:.2f} seconds")
print(f"Average rate: {success_count / duration:.2f} packets/sec (~{(success_count * PACKET_SIZE * 8) / (duration * 1_000_000):.2f} Mbps)")

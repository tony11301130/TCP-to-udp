import socket
import time

# ========== 設定區 ==========
LISTEN_IP = '0.0.0.0'     # 綁定所有網卡
LISTEN_PORT = 5000
EXPECTED_PACKETS = 10000   # 預期封包總數（需與發送端對應）
# ===========================

def receive_packets():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))

    received_count = 0
    start_time = None

    try:
        while True:
            # 直接阻塞等待封包進來（無限等待）
            data, addr = sock.recvfrom(1400)

            if start_time is None:
                # 第一次收到封包時才開始計時
                start_time = time.time()

            received_count += 1

            # 可選：列印封包內容（測試用）
            # print(f"Received: {data.decode()} from {addr}")

            # 當收到指定數量的封包後，停止接收
            if received_count >= EXPECTED_PACKETS:
                break

    except KeyboardInterrupt:
        print("\nStopped by user")
        sock.close()
        exit()

    finally:
        sock.close()

        if start_time is not None:
            end_time = time.time()
            duration = end_time - start_time
            loss_count = EXPECTED_PACKETS - received_count
            loss_rate = (loss_count / EXPECTED_PACKETS) * 100

            # === 顯示結果 ===
            print("\n=== Result ===")
            print(f"Expected packets: {EXPECTED_PACKETS}")
            print(f"Received packets: {received_count}")
            print(f"Lost packets: {loss_count}")
            print(f"Loss rate: {loss_rate:.2f}%")
            print(f"Duration: {duration:.2f} seconds")
            print("----------------------------\n")

if __name__ == "__main__":
    try:
        while True:
            receive_packets()  # 持續等待和處理封包
    except KeyboardInterrupt:
        print("\nReceiver stopped by user. Exiting...")

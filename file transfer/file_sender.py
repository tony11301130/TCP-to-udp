import os
import time
import socket
import hashlib

# 設定參數
UPLOAD_DIR = "/home/tony/code/file-transfer/upload"
SENT_DIR = "/home/tony/code/file-transfer/sent"
CHUNK_SIZE = 1024
DEST_IP = "192.168.1.91"
DEST_PORT = 5005
PACKET_INTERVAL = 0.001  # 每個封包傳送間隔 (秒)

# 檢查檔案是否在一定時間內保持大小穩定
def wait_until_stable(filepath, wait_time=1, retries=5):
    for i in range(retries):
        size1 = os.path.getsize(filepath)
        time.sleep(wait_time)
        if not os.path.exists(filepath):
            print(f"⚠️  檔案在等待過程中消失：{filepath}")
            return False
        size2 = os.path.getsize(filepath)
        if size1 == size2:
            return True
        else:
            print(f"⏳ 嘗試第 {i+1}/{retries} 次：檔案大小仍在變動")
    return False

# 傳送單一檔案
def send_file(filepath, sock):
    filename = os.path.basename(filepath).encode()
    filename_len = len(filename)

    with open(filepath, "rb") as f:
        data = f.read()

    total_chunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
    if total_chunks >= 2**32:
        raise ValueError("❌ 檔案太大，無法處理（超過 4GB / 4 billion chunks）")

    sha256 = hashlib.sha256(data).hexdigest().encode()

    # metadata 封包：type=0x00 | total_chunks (4 bytes) | filename_len (1 byte) | filename | sha256
    metadata = (
        b"\x00" +
        total_chunks.to_bytes(4, 'big') +
        bytes([filename_len]) +
        filename +
        sha256
    )
    sock.sendto(metadata, (DEST_IP, DEST_PORT))
    print(f"📤 傳送 metadata：{filepath} ({total_chunks} chunks)")
    time.sleep(0.1)

    for seq in range(total_chunks):
        start = seq * CHUNK_SIZE
        end = start + CHUNK_SIZE
        chunk = data[start:end]
        packet = b"\x01" + seq.to_bytes(4, 'big') + chunk
        sock.sendto(packet, (DEST_IP, DEST_PORT))
        time.sleep(PACKET_INTERVAL)

    print(f"✅ 傳送完成：{filepath} ({total_chunks} chunks)")

# 監控 upload 資料夾，並傳送新檔案
def watch_folder():
    os.makedirs(SENT_DIR, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"📡 正在監控資料夾：'{UPLOAD_DIR}'")
    while True:
        try:
            files = [f for f in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, f))]
            for fname in files:
                src = os.path.join(UPLOAD_DIR, fname)
                print(f"\n🔍 檢查檔案：{fname}")

                if not os.path.exists(src):
                    print(f"⚠️  檔案不存在，跳過：{fname}")
                    continue

                if not wait_until_stable(src):
                    print(f"🕒 檔案未穩定，跳過：{fname}")
                    continue

                try:
                    send_file(src, sock)
                    dst = os.path.join(SENT_DIR, fname)
                    os.rename(src, dst)
                    print(f"📦 檔案已移動到 sent：{dst}")
                except Exception as e:
                    print(f"❌ 傳送失敗：{src}\n   錯誤：{e}")
        except Exception as main_loop_error:
            print(f"💥 主循環錯誤：{main_loop_error}")
        time.sleep(1)

if __name__ == "__main__":
    watch_folder()

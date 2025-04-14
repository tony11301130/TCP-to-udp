import asyncio
import hashlib
import os
import socket
from concurrent.futures import ThreadPoolExecutor

# 接收檔案儲存目錄
RECEIVE_DIR = "/tmp/received"
CHUNK_SIZE = 1024

os.makedirs(RECEIVE_DIR, exist_ok=True)

class FileBuffer:
    def __init__(self, filename, total_chunks, sha256):
        self.filename = filename
        self.total = total_chunks
        self.sha256 = sha256
        self.received = set()
        self.buffer = {}
        self.expected = 0
        self.filepath = os.path.join(RECEIVE_DIR, filename + ".tmp")
        self.file = open(self.filepath, 'wb')

    def write_chunk(self, seq, data):
        if seq in self.received:
            return
        self.buffer[seq] = data
        self.flush_buffer()

    def flush_buffer(self):
        while self.expected in self.buffer:
            data = self.buffer.pop(self.expected)
            self.file.seek(self.expected * CHUNK_SIZE)
            self.file.write(data)
            self.received.add(self.expected)
            self.expected += 1

    def is_complete(self):
        return len(self.received) == self.total

    def finalize(self):
        self.file.close()
        real_path = os.path.join(RECEIVE_DIR, self.filename)
        os.rename(self.filepath, real_path)
        with open(real_path, 'rb') as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        return actual_hash == self.sha256

file_map = {}
executor = ThreadPoolExecutor(max_workers=16)  # 增加 worker 數量以提升寫入效能

# 非同步封包處理邏輯
async def process_packet(packet):
    if packet[0] == 0x00:
        file_id = packet[1:5]
        total = int.from_bytes(packet[5:9], 'big')
        name_len = packet[9]
        filename = packet[10:10 + name_len].decode()
        sha256 = packet[10 + name_len:].decode()
        file_map[file_id] = FileBuffer(filename, total, sha256)
        print(f"📘 Metadata received: {filename}, total chunks: {total}")

    elif packet[0] == 0x01:
        file_id = packet[1:5]
        seq = int.from_bytes(packet[5:9], 'big')
        data = packet[9:]
        buf = file_map.get(file_id)
        if buf:
            await asyncio.get_running_loop().run_in_executor(executor, buf.write_chunk, seq, data)
            if buf.is_complete():
                success = await asyncio.get_running_loop().run_in_executor(executor, buf.finalize)
                if success:
                    print(f"✅ File {buf.filename} received and verified.")
                else:
                    print(f"❌ Hash mismatch for {buf.filename}")
                del file_map[file_id]

# 使用非同步 socket loop 接收封包（取代 DatagramProtocol）
async def receive_loop():
    print("🟢 Starting high-speed UDP socket receiver loop on port 5005...")
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024 * 1024)  # 設定接收 buffer 大小
    sock.setblocking(False)
    sock.bind(('0.0.0.0', 5005))

    while True:
        try:
            data, addr = await loop.sock_recvfrom(sock, CHUNK_SIZE + 100)
            asyncio.create_task(process_packet(data))
        except Exception as e:
            print(f"❌ Socket error: {e}")

if __name__ == '__main__':
    asyncio.run(receive_loop())

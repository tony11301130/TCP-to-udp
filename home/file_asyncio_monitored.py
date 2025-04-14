import asyncio
import hashlib
import os
import socket
from concurrent.futures import ThreadPoolExecutor

# 接收資料夾與參數設定
RECEIVE_DIR = "/tmp/received"
CHUNK_SIZE = 1024
QUEUE_MAXSIZE = 65536

os.makedirs(RECEIVE_DIR, exist_ok=True)

# 封包處理資料結構
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

# 全域變數
file_map = {}
executor = ThreadPoolExecutor(max_workers=8)
packet_queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
dropped_packets = 0

# 封包處理邏輯
async def process_packet(packet):
    if packet[0] == 0x00:
        file_id = packet[1:5]
        total = int.from_bytes(packet[5:9], 'big')
        name_len = packet[9]
        filename = packet[10:10 + name_len].decode()
        sha256 = packet[10 + name_len:].decode()
        file_map[file_id] = FileBuffer(filename, total, sha256)
        print(f"📘 Metadata received: {filename}, chunks: {total}")

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

# 主動 worker：從 queue 中取出封包處理
async def packet_worker():
    while True:
        packet = await packet_queue.get()
        try:
            await process_packet(packet)
        except Exception as e:
            print(f"❌ 處理封包時發生錯誤: {e}")
        finally:
            packet_queue.task_done()

# 非同步 socket 收封包
async def receive_loop():
    global dropped_packets
    print("🟢 啟動封包接收器，監聽 UDP port 5005...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024 * 1024)
    sock.setblocking(False)
    sock.bind(('0.0.0.0', 5005))
    loop = asyncio.get_running_loop()

    while True:
        try:
            data, _ = await loop.sock_recvfrom(sock, CHUNK_SIZE + 100)
            try:
                packet_queue.put_nowait(data)
            except asyncio.QueueFull:
                dropped_packets += 1
        except Exception as e:
            print(f"❌ Socket recv error: {e}")

# 監控 queue 狀態（每 2 秒一次）
async def queue_monitor():
    while True:
        usage = packet_queue.qsize()
        percent = (usage / QUEUE_MAXSIZE) * 100
        print(f"[MONITOR] Queue 使用率：{usage}/{QUEUE_MAXSIZE} ({percent:.1f}%) | Dropped: {dropped_packets}")
        await asyncio.sleep(2)

# 啟動主程式
async def main():
    asyncio.create_task(packet_worker())   # 單一主動 worker
    asyncio.create_task(queue_monitor())   # 加入 queue 監控
    await receive_loop()

if __name__ == '__main__':
    asyncio.run(main())

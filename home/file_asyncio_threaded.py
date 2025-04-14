import asyncio
import hashlib
import os
import socket
import threading
import janus
from concurrent.futures import ThreadPoolExecutor

RECEIVE_DIR = "/tmp/received"
CHUNK_SIZE = 1024
QUEUE_MAXSIZE = 65536
RECEIVE_PORT = 5005

os.makedirs(RECEIVE_DIR, exist_ok=True)

# 檔案快取與寫入邏輯
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
executor = ThreadPoolExecutor(max_workers=8)
packet_queue = janus.Queue(maxsize=QUEUE_MAXSIZE)
dropped_packets = 0

# 封包處理主邏輯
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

# 封包消費 worker
async def packet_worker():
    while True:
        packet = await packet_queue.async_q.get()
        try:
            await process_packet(packet)
        except Exception as e:
            print(f"❌ Packet error: {e}")
        finally:
            packet_queue.async_q.task_done()

# Queue 監控
async def queue_monitor():
    while True:
        usage = packet_queue.async_q.qsize()
        percent = (usage / QUEUE_MAXSIZE) * 100
        print(f"[MONITOR] Queue: {usage}/{QUEUE_MAXSIZE} ({percent:.1f}%) | Dropped: {dropped_packets}")
        await asyncio.sleep(2)

# Blocking thread 版本的封包接收器
def receiver_thread(sock, sync_queue):
    global dropped_packets
    while True:
        try:
            data, _ = sock.recvfrom(CHUNK_SIZE + 100)
            try:
                sync_queue.put_nowait(data)
            except:
                dropped_packets += 1
        except Exception as e:
            print(f"❌ recvfrom error: {e}")

# 主程式
async def main():
    # 建立 UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024 * 1024)
    sock.bind(('0.0.0.0', RECEIVE_PORT))

    # 啟動封包接收 thread（不阻塞 asyncio loop）
    threading.Thread(target=receiver_thread, args=(sock, packet_queue.sync_q), daemon=True).start()

    # 啟動 async packet worker 與監控器
    asyncio.create_task(packet_worker())
    asyncio.create_task(queue_monitor())

    print(f"🟢 Running threaded receiver on port {RECEIVE_PORT}...")
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    asyncio.run(main())

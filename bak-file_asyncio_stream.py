import asyncio
import hashlib
import os
import struct
from concurrent.futures import ThreadPoolExecutor

RECEIVE_DIR = "/home/tony/code/file-transfer/received"
CHUNK_SIZE = 1024
UNIX_SOCKET_PATH = "/tmp/udp_to_py.sock"

os.makedirs(RECEIVE_DIR, exist_ok=True)
if os.path.exists(UNIX_SOCKET_PATH):
    os.remove(UNIX_SOCKET_PATH)

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
executor = ThreadPoolExecutor(max_workers=16)

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

async def handle_stream(reader, writer):
    print(f"🟢 Python stream socket listener started at {UNIX_SOCKET_PATH}")
    try:
        while True:
            header = await reader.readexactly(4)
            length = struct.unpack("I", header)[0]
            data = await reader.readexactly(length)
            asyncio.create_task(process_packet(data))
    except asyncio.IncompleteReadError:
        print("❌ 對方關閉連線")
    except Exception as e:
        print(f"❌ Stream error: {e}")

async def unix_stream_server():
    server = await asyncio.start_unix_server(handle_stream, path=UNIX_SOCKET_PATH)
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(unix_stream_server())

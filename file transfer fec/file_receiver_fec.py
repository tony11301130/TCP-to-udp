# === RECEIVER ===
import os
import socket
import hashlib
import time

RECEIVE_DIR = "/home/tony/code/file-transfer/received"
CHUNK_SIZE = 1024
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5005

file_buffers = {}


def save_file(filename, chunks, expected_hash):
    os.makedirs(RECEIVE_DIR, exist_ok=True)
    path = os.path.join(RECEIVE_DIR, filename)

    ordered_chunks = [chunks[i] for i in sorted(chunks)]
    with open(path, 'wb') as f:
        for chunk in ordered_chunks:
            f.write(chunk)

    with open(path, 'rb') as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()

    if actual_hash == expected_hash:
        print(f"✅ File '{filename}' saved and verified.")
    else:
        print(f"❌ File '{filename}' hash mismatch! Expected {expected_hash}, got {actual_hash}")


def handle_packet(packet):
    global file_buffers
    packet_type = packet[0]

    if packet_type == 0x00:
        total = int.from_bytes(packet[1:5], 'big')
        name_len = packet[5]
        filename = packet[6:6 + name_len].decode()
        sha256 = packet[6 + name_len:].decode()

        file_buffers[filename] = {
            'chunks': {},
            'total': total,
            'hash': sha256
        }
        print(f"📥 Metadata received: {filename} ({total} chunks)")

    elif packet_type == 0x01:
        seq = int.from_bytes(packet[1:5], 'big')
        data = packet[5:]

        for fname, info in file_buffers.items():
            if seq not in info['chunks'] and len(info['chunks']) < info['total']:
                info['chunks'][seq] = data
                print(f"📦 Chunk {seq} received for '{fname}'")
                if len(info['chunks']) == info['total']:
                    save_file(fname, info['chunks'], info['hash'])
                    del file_buffers[fname]
                break


def start_receiver():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.bind((LISTEN_IP, LISTEN_PORT))

    print(f"🟢 Listening on UDP {LISTEN_PORT}...")

    while True:
        packet, addr = sock.recvfrom(CHUNK_SIZE + 100)
        handle_packet(packet)


if __name__ == "__main__":
    start_receiver()

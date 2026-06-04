"""RTP loopback echo (receive -> retransmit)."""

from __future__ import annotations

import socket
import struct
import threading
import time

import numpy as np

from audio_worker import EchoSource, RTPReceiver, RTPSender, wire_rtp_loopback
from utils.g711 import pcmu_encode_from_float32


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_echo_source_fifo():
    src = EchoSource(8000)
    tone = np.full(160, 0.25, dtype=np.float32)
    src.push(tone)
    out = src.read(160)
    assert out.shape == (160,)
    assert np.allclose(out, 0.25)


def test_wire_rtp_loopback_roundtrip():
    """Send one RTP packet into RX; loopback TX should emit PCMU back."""
    rx = RTPReceiver(worker=None, bind_ip="127.0.0.1", port=_free_udp_port())
    rx.start()

    captured: list[bytes] = []
    done = threading.Event()

    def sniff():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", _free_udp_port()))
        sock.settimeout(2.0)
        port = sock.getsockname()[1]
        tx = RTPSender("127.0.0.1", port, ptime_ms=20, payload_type=0)
        tx.start()
        wire_rtp_loopback(rx, tx, sr=8000)
        try:
            while not done.is_set():
                try:
                    data, _ = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                captured.append(data)
                done.set()
        finally:
            sock.close()
            tx.stop()

    t = threading.Thread(target=sniff, daemon=True)
    t.start()
    time.sleep(0.05)

    pcm = np.full(160, 0.3, dtype=np.float32)
    payload = pcmu_encode_from_float32(pcm)
    header = struct.pack("!BBHII", 0x80, 0, 1, 160, 0x12345678)
    rx.sock.sendto(header + payload, ("127.0.0.1", rx.port))

    assert done.wait(timeout=3.0), "loopback TX did not emit RTP"
    rx.stop()
    t.join(timeout=2.0)

    assert captured, "no RTP captured from loopback sender"
    pkt = captured[0]
    assert len(pkt) >= 12
    pt = pkt[1] & 0x7F
    assert pt == 0
    echoed = pkt[12:]
    assert len(echoed) == 160

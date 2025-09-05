import wave, threading, numpy as np
import sounddevice as sd
import queue
from typing import Callable, Optional
import os
from utils.g711 import pcmu_decode_to_float32, pcma_decode_to_float32
import socket
import struct
import time
import random
from collections import deque


def db_to_lin(db: float) -> float:
    return float(10.0 ** (db / 20.0)) if db else 1.0


# class OldLoopingAudioWorker:
#     """
#     Single-owner audio engine:
#       - One RawOutputStream (float32 mono)
#       - Background render thread
#       - Commands via queue (no cross-thread audio calls)
#       - Per-line looping tones + one-shots
#     """
#     def __init__(
#         self,
#         samplerate: int = 44100,
#         channels: int = 1,
#         blocksize: int = 1024,
#         device=None,
#         tone_resolver: Optional[Callable[[int], Optional[str]]] = None,  # tone_id -> file path
#         master_gain_db: float = 0.0,
#     ):
#         self.samplerate = samplerate
#         self.channels = channels
#         self.blocksize = blocksize
#         self.device = device
#         self.tone_resolver = tone_resolver or (lambda tone_id: None)
#         self.master_gain = db_to_lin(master_gain_db)
#
#         # audio
#         self.stream = sd.RawOutputStream(
#             samplerate=self.samplerate,
#             channels=self.channels,
#             dtype="float32",
#             blocksize=0,
#             device=self.device,
#         )
#
#         # state
#         self.cmd_q: queue.Queue = queue.Queue()
#         self.stop_ev = threading.Event()
#         self.tone_cache: dict[int, np.ndarray] = {}        # tone_id -> float32 mono @ samplerate
#         self.active: dict[int, dict] = {}                  # line -> {"buf": np.ndarray, "pos": int, "gain": float}
#         self.oneshots: list[dict] = []                     # [{"buf": np.ndarray, "pos": int, "gain": float}, ...]
#
#         self._thr = threading.Thread(target=self._run, name="LoopingAudioWorker", daemon=True)
#
#     # ---------- public API (thread-safe) ----------
#     def start(self):
#         self.stream.start()
#         self._thr.start()
#
#     def close(self):
#         self.stop_ev.set()
#         self.cmd_q.put(("__quit__", None))
#         self._thr.join(timeout=1.0)
#         try: self.stream.stop()
#         except Exception: pass
#         try: self.stream.close()
#         except Exception: pass
#
#     def set_master_gain_db(self, db: float):
#         self.cmd_q.put(("master_gain", db))
#
#     def set_tone(self, line: int, tone_id: int, gain_db: float = 0.0):
#         """Start/replace looping tone on a line."""
#         self.cmd_q.put(("set_tone", (line, tone_id, gain_db)))
#
#     def clear_tone(self, line: int):
#         """Stop looping tone on a line."""
#         self.cmd_q.put(("clear_tone", line))
#
#     def clear_all(self):
#         self.cmd_q.put(("clear_all", None))
#
#     def play_wav_once(self, path: str, gain_db: float = 0.0):
#         """Queue a one-shot WAV (for key beeps)."""
#         self.cmd_q.put(("play_wav_once", (path, gain_db)))
#
#     def play_bytes_once(self, buf_f32_mono: bytes, gain_db: float = 0.0):
#         """Queue a one-shot (float32 mono)."""
#         self.cmd_q.put(("play_bytes_once", (buf_f32_mono, gain_db)))
#
#     # ---------- internals ----------
#     def _load_wav_float32(self, path: str) -> np.ndarray:
#         with wave.open(path, "rb") as wf:
#             nchan, sampwidth, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
#             raw = wf.readframes(wf.getnframes())
#         if sampwidth != 2:
#             raise ValueError(f"{os.path.basename(path)} must be 16-bit PCM WAV")
#         data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
#         if nchan > 1:
#             data = data.reshape(-1, nchan).mean(axis=1)  # downmix
#         if sr != self.samplerate:
#             # fast nearest-neighbor (fine for tones); swap in a real resampler if needed
#             ratio = self.samplerate / sr
#             idx = (np.arange(int(len(data) * ratio)) / ratio).astype(np.int64)
#             data = data[idx]
#         if data.size == 0:
#             data = np.zeros(1, dtype=np.float32)
#         return data
#
#     def _ensure_tone_loaded(self, tone_id: int) -> Optional[np.ndarray]:
#         if tone_id in self.tone_cache:
#             return self.tone_cache[tone_id]
#         path = self.tone_resolver(tone_id)
#         if not path or not os.path.exists(path):
#             return None
#         buf = self._load_wav_float32(path)
#         self.tone_cache[tone_id] = buf
#         return buf
#
#     def _apply_cmd(self, cmd, payload):
#         if cmd == "master_gain":
#             self.master_gain = db_to_lin(payload or 0.0)
#         elif cmd == "set_tone":
#             line, tone_id, gain_db = payload
#             buf = self._ensure_tone_loaded(tone_id)
#             if buf is None:
#                 # silently ignore unknown tone ids
#                 self.active.pop(line, None)
#             else:
#                 self.active[line] = {"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)}
#         elif cmd == "clear_tone":
#             self.active.pop(payload, None)
#         elif cmd == "clear_all":
#             self.active.clear()
#             self.oneshots.clear()
#         elif cmd == "play_wav_once":
#             path, gain_db = payload
#             try:
#                 buf = self._load_wav_float32(path)
#                 self.oneshots.append({"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)})
#             except Exception:
#                 pass
#         elif cmd == "play_bytes_once":
#             buf_bytes, gain_db = payload
#             # interpret bytes as float32 mono
#             buf = np.frombuffer(buf_bytes, dtype=np.float32)
#             self.oneshots.append({"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)})
#
#     def _mix_block(self) -> bytes:
#         n = self.blocksize
#         out = np.zeros(n, dtype=np.float32)
#
#         # looped tones (per line)
#         if self.active:
#             for line, st in list(self.active.items()):
#                 buf, pos, g = st["buf"], st["pos"], st["gain"]
#                 L = buf.shape[0]
#                 if L == 0:
#                     continue
#                 if pos + n <= L:
#                     chunk = buf[pos:pos+n]
#                     pos += n
#                 else:
#                     # wrap
#                     r = L - pos
#                     chunk = np.empty(n, dtype=np.float32)
#                     if r > 0:
#                         chunk[:r] = buf[pos:]
#                     chunk[r:] = buf[:(n - r)]
#                     pos = (pos + n) - L
#                 out += g * chunk
#                 st["pos"] = pos  # write back
#         # one-shots
#         if self.oneshots:
#             keep = []
#             for st in self.oneshots:
#                 buf, pos, g = st["buf"], st["pos"], st["gain"]
#                 L = buf.shape[0]
#                 if pos >= L:
#                     continue
#                 take = min(n, L - pos)
#                 chunk = np.zeros(n, dtype=np.float32)
#                 if take > 0:
#                     chunk[:take] = buf[pos:pos+take]
#                     st["pos"] = pos + take
#                 out += g * chunk
#                 if st["pos"] < L:
#                     keep.append(st)
#             self.oneshots = keep
#
#         # master gain + clip
#         if self.master_gain != 1.0:
#             out *= self.master_gain
#         np.clip(out, -1.0, 1.0, out=out)
#         return out.tobytes()
#
#     def _run(self):
#         while not self.stop_ev.is_set():
#             # drain all pending commands quickly
#             while True:
#                 try:
#                     cmd, payload = self.cmd_q.get_nowait()
#                 except queue.Empty:
#                     break
#                 if cmd == "__quit__":
#                     return
#                 self._apply_cmd(cmd, payload)
#
#             # render & write one block (blocking write paces the loop)
#             try:
#                 buf = self._mix_block()
#                 self.stream.write(buf)
#             except Exception:
#                 # if backend hiccups, keep trying instead of crashing
#                 pass


class LoopingAudioWorker:
    """
    Single-owner audio engine:
      - One RawOutputStream (float32 mono)
      - Background render thread
      - Commands via queue (no cross-thread audio calls)
      - Per-line looping tones + one-shots
    """
    def __init__(
        self,
        samplerate: int = 44100,
        channels: int = 1,
        blocksize: int = 1024,
        device=None,
        tone_resolver: Optional[Callable[[int], Optional[str]]] = None,  # tone_id -> file path
        master_gain_db: float = 0.0,
    ):
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize
        self.device = device
        self.tone_resolver = tone_resolver or (lambda tone_id: None)
        self.master_gain = db_to_lin(master_gain_db)
        self.cmd_q = queue.Queue()
        self.stop_ev = threading.Event()
        self.blocksize = 1024  # choose; 1024 at 44.1kHz ≈ 23 ms blocks
        self.streams = {}  # source_id -> {"buf": np.ndarray(float32), "gain": float}
        self.lock = threading.Lock()

        # audio
        self.stream = sd.RawOutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            blocksize=0,
            device=self.device,
        )

        # state
        self.cmd_q: queue.Queue = queue.Queue()
        self.stop_ev = threading.Event()
        self.tone_cache: dict[int, np.ndarray] = {}        # tone_id -> float32 mono @ samplerate
        self.active: dict[int, dict] = {}                  # line -> {"buf": np.ndarray, "pos": int, "gain": float}
        self.oneshots: list[dict] = []                     # [{"buf": np.ndarray, "pos": int, "gain": float}, ...]

        self._thr = threading.Thread(target=self._run, name="LoopingAudioWorker", daemon=True)

    # ---------- public API (thread-safe) ----------
    def start(self):
        self.stream.start()
        self._thr.start()

    def close(self):
        self.stop_ev.set()
        self.cmd_q.put(("__quit__", None))
        self._thr.join(timeout=1.0)
        with self.lock:
            try: self.stream.stop()
            except Exception: pass
            try: self.stream.close()
            except Exception: pass

    def set_master_gain_db(self, db: float):
        self.cmd_q.put(("master_gain", db))

    def set_tone(self, line: int, tone_id: int, gain_db: float = 0.0):
        """Start/replace looping tone on a line."""
        self.cmd_q.put(("set_tone", (line, tone_id, gain_db)))

    def clear_tone(self, line: int):
        """Stop looping tone on a line."""
        self.cmd_q.put(("clear_tone", line))

    def clear_all(self):
        self.cmd_q.put(("clear_all", None))

    def play_wav_once(self, path: str, gain_db: float = 0.0):
        """Queue a one-shot WAV (for key beeps)."""
        self.cmd_q.put(("play_wav_once", (path, gain_db)))

    def play_bytes_once(self, buf_f32_mono: bytes, gain_db: float = 0.0):
        """Queue a one-shot (float32 mono)."""
        self.cmd_q.put(("play_bytes_once", (buf_f32_mono, gain_db)))

    def add_stream(self, source_id: str, gain_db: float = 0.0):
        self.cmd_q.put(("add_stream", (source_id, gain_db)))

    def remove_stream(self, source_id: str):
        self.cmd_q.put(("remove_stream", source_id))

    def feed_stream(self, source_id: str, pcm_f32: np.ndarray, src_rate: int):
        """Thread-safe: enqueue PCM to be mixed; we resample if needed on the audio thread."""
        # Send the numpy array bytes to avoid cross-thread numpy object sharing if you prefer.
        self.cmd_q.put(("feed_stream", (source_id, pcm_f32, src_rate)))

    def set_stream_gain_db(self, source_id: str, gain_db: float):
        self.cmd_q.put(("stream_gain", (source_id, gain_db)))

    # ---------- internals ----------
    def _resample_nearest(self, data: np.ndarray, src_rate: int) -> np.ndarray:
        if src_rate == self.samplerate or data.size == 0:
            return data
        ratio = self.samplerate / float(src_rate)
        idx = (np.arange(int(len(data) * ratio)) / ratio).astype(np.int64)
        return data[idx]

    def _load_wav_float32(self, path: str) -> np.ndarray:
        with wave.open(path, "rb") as wf:
            nchan, sampwidth, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sampwidth != 2:
            raise ValueError(f"{os.path.basename(path)} must be 16-bit PCM WAV")
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if nchan > 1:
            data = data.reshape(-1, nchan).mean(axis=1)  # downmix
        if sr != self.samplerate:
            # fast nearest-neighbor (fine for tones); swap in a real resampler if needed
            ratio = self.samplerate / sr
            idx = (np.arange(int(len(data) * ratio)) / ratio).astype(np.int64)
            data = data[idx]
        if data.size == 0:
            data = np.zeros(1, dtype=np.float32)
        return data

    def _ensure_tone_loaded(self, tone_id: int) -> Optional[np.ndarray]:
        if tone_id in self.tone_cache:
            return self.tone_cache[tone_id]
        path = self.tone_resolver(tone_id)
        if not path or not os.path.exists(path):
            return None
        buf = self._load_wav_float32(path)
        self.tone_cache[tone_id] = buf
        return buf

    def _apply_cmd(self, cmd, payload):
        if cmd == "__quit__":
            return
        if cmd == "add_stream":
            sid, gdb = payload
            self.streams[sid] = {"buf": np.zeros(0, dtype=np.float32), "gain": 10 ** (gdb / 20.0)}
        elif cmd == "remove_stream":
            self.streams.pop(payload, None)
        elif cmd == "stream_gain":
            sid, gdb = payload
            if sid in self.streams:
                self.streams[sid]["gain"] = 10 ** (gdb / 20.0)
        elif cmd == "feed_stream":
            sid, pcm, src_rate = payload
            # ensure float32 mono
            if pcm.dtype != np.float32:
                pcm = pcm.astype(np.float32, copy=False)
            pcm = self._resample_nearest(pcm, src_rate)
            st = self.streams.get(sid)
            if st is None:
                # auto-create with 0 dB gain if not present
                self.streams[sid] = {"buf": pcm.copy(), "gain": 1.0}
            else:
                st["buf"] = np.concatenate([st["buf"], pcm], axis=0)
        elif cmd == "master_gain":
            self.master_gain = db_to_lin(payload or 0.0)
        elif cmd == "set_tone":
            line, tone_id, gain_db = payload
            buf = self._ensure_tone_loaded(tone_id)
            if buf is None:
                # silently ignore unknown tone ids
                self.active.pop(line, None)
            else:
                self.active[line] = {"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)}
        elif cmd == "clear_tone":
            self.active.pop(payload, None)
        elif cmd == "clear_all":
            self.active.clear()
            self.oneshots.clear()
        elif cmd == "play_wav_once":
            path, gain_db = payload
            try:
                buf = self._load_wav_float32(path)
                self.oneshots.append({"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)})
            except Exception:
                pass
        elif cmd == "play_bytes_once":
            buf_bytes, gain_db = payload
            # interpret bytes as float32 mono
            buf = np.frombuffer(buf_bytes, dtype=np.float32)
            self.oneshots.append({"buf": buf, "pos": 0, "gain": db_to_lin(gain_db)})

    def _mix_streams(self, out: np.ndarray):
        # mix up to blocksize samples from each active stream
        n = out.shape[0]
        for sid, st in list(self.streams.items()):
            buf = st["buf"]
            if buf.size == 0:
                continue
            take = min(n, buf.size)
            out[:take] += st["gain"] * buf[:take]
            # consume
            if take == buf.size:
                st["buf"] = np.zeros(0, dtype=np.float32)
            else:
                st["buf"] = buf[take:]

    def _mix_tones(self, out: np.ndarray):
        n = out.shape[0]
        if not self.active:
            return
        for line, st in list(self.active.items()):
            buf, pos, g = st["buf"], st["pos"], st["gain"]
            L = buf.shape[0]
            if L == 0:
                continue
            if pos + n <= L:
                chunk = buf[pos:pos + n]
                pos += n
            else:
                r = L - pos
                chunk = np.empty(n, dtype=np.float32)
                if r > 0:
                    chunk[:r] = buf[pos:]
                chunk[r:] = buf[:(n - r)]
                pos = (pos + n) - L
            out += g * chunk
            st["pos"] = pos  # write back

    def _mix_oneshots(self, out: np.ndarray):
        n = out.shape[0]
        if not self.oneshots:
            return
        keep = []
        for st in self.oneshots:
            buf, pos, g = st["buf"], st["pos"], st["gain"]
            L = buf.shape[0]
            if pos >= L:
                continue
            take = min(n, L - pos)
            if take > 0:
                out[:take] += g * buf[pos:pos + take]
                st["pos"] = pos + take
            if st["pos"] < L:
                keep.append(st)
        self.oneshots = keep

    def _run(self):
        while not self.stop_ev.is_set():
            # drain all pending commands quickly
            while True:
                try:
                    cmd, payload = self.cmd_q.get_nowait()
                except queue.Empty:
                    break
                if cmd == "__quit__":
                    return
                self._apply_cmd(cmd, payload)

            # render one block (start with zeros)
            out = np.zeros(self.blocksize, dtype=np.float32)

            # (if you kept tone/oneshot logic, mix them here first)
            self._mix_tones(out)
            self._mix_oneshots(out)

            # mix RTP/PCM streams
            self._mix_streams(out)

            # clip & write
            np.clip(out, -1.0, 1.0, out=out)
            try:
                with self.lock:
                    self.stream.write(out.tobytes())
            except Exception:
                # keep the engine alive even if backend momentarily hiccups
                pass


class RTPReceiver:
    """
    Minimal RTP receiver -> float32 mono -> AudioWorker.feed_stream().
    Supports PT=0 (PCMU μ-law) and PT=8 (PCMA A-law).
    """
    def __init__(self, worker, bind_ip="0.0.0.0", port=0, source_id="rx", log=None):
        self.worker = worker
        self.source_id = source_id
        self.log = log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, port))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._run, name=f"RTPReceiver:{self.port}", daemon=True)

    def start(self):
        # ensure stream exists in worker
        self.worker.add_stream(self.source_id, gain_db=0.0)
        self._thr.start()

    def stop(self):
        self._stop.set()
        try: self.sock.close()
        except Exception: pass
        self.worker.remove_stream(self.source_id)

    def _decode_payload(self, pt: int, payload: bytes) -> np.ndarray:
        if pt == 0:   # PCMU
            return pcmu_decode_to_float32(payload)
        if pt == 8:   # PCMA
            return pcma_decode_to_float32(payload)
        # unknown codec: drop
        return np.zeros(0, dtype=np.float32)

    def _run(self):
        if self.log: self.log.info(f"[RTP RX] listening on {self.port}")
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < 12:
                continue
            # RTP header
            b0, b1, seq, ts, ssrc = struct.unpack("!BBHII", data[:12])
            version = (b0 >> 6) & 0x03
            cc = b0 & 0x0F
            pt = b1 & 0x7F
            header_len = 12 + (cc * 4)
            if version != 2 or len(data) <= header_len:
                continue
            payload = data[header_len:]
            pcm = self._decode_payload(pt, payload)
            if pcm.size:
                # RTP telephony is 8kHz typically
                self.worker.feed_stream(self.source_id, pcm, src_rate=8000)


class _BaseSource:
    def start(self): pass
    def stop(self): pass
    def read(self, n: int) -> np.ndarray:  # float32 mono @ target sr
        return np.zeros(n, dtype=np.float32)

class SilenceSource(_BaseSource):
    def __init__(self, sr: int): self.sr = sr
    # read() inherited (zeros)

class WavSource(_BaseSource):
    """Preload a 16-bit PCM wav, downmix to mono, resample if needed, loopable."""
    def __init__(self, path: str, target_sr: int, loop: bool = False, gain_db: float = 0.0):
        self.loop = loop
        self.gain = 10 ** (gain_db / 20.0)
        with wave.open(path, "rb") as wf:
            nchan, sampwidth, sr = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sampwidth != 2:
            raise ValueError(f"{os.path.basename(path)} must be 16-bit PCM WAV")
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if nchan > 1:
            pcm = pcm.reshape(-1, nchan).mean(axis=1)  # downmix
        if sr != target_sr:
            # quick nearest resample (good enough for prompts/tones)
            ratio = target_sr / float(sr)
            idx = (np.arange(int(len(pcm) * ratio)) / ratio).astype(np.int64)
            pcm = pcm[idx]
        self.buf = pcm if pcm.size else np.zeros(1, dtype=np.float32)
        self.pos = 0

    def read(self, n: int) -> np.ndarray:
        if n <= 0: return np.zeros(0, dtype=np.float32)
        out = np.zeros(n, dtype=np.float32)
        L = self.buf.size
        if L == 0: return out
        pos = self.pos
        if pos >= L and not self.loop:
            return out
        if self.loop:
            # wrap as needed
            first = min(n, L - (pos % L))
            out[:first] = self.buf[pos % L : (pos % L) + first]
            remain = n - first
            while remain > 0:
                take = min(remain, L)
                out[n - remain : n - remain + take] = self.buf[:take]
                remain -= take
            self.pos = (pos + n) % L
        else:
            take = min(n, L - pos)
            if take > 0:
                out[:take] = self.buf[pos : pos + take]
                self.pos = pos + take
        return self.gain * out

class MicSource(_BaseSource):
    """Capture mono float32 at target_sr into a small deque buffer."""
    def __init__(self, target_sr: int, device=None, blocksize: int = None):
        self.sr = target_sr
        self.device = device
        self.blocksize = blocksize
        self._buf = deque()
        self._lock = threading.Lock()
        self._stream = None
        self._stopped = True

    def start(self):
        if self._stream is not None: return
        # Import here to avoid requiring sounddevice unless needed
        import sounddevice as sd
        self._stopped = False

        def cb(indata, frames, time_info, status):
            if self._stopped: return
            # indata shape: (frames, channels). Force mono average if >1.
            x = indata.astype(np.float32, copy=False)
            if x.ndim == 2 and x.shape[1] > 1:
                x = x.mean(axis=1)
            else:
                x = x.reshape(-1)
            with self._lock:
                self._buf.append(x.copy())
                # cap ~ 400 ms
                total = sum(arr.size for arr in self._buf)
                max_samples = int(self.sr * 0.4)
                while total > max_samples and self._buf:
                    dropped = self._buf.popleft()
                    total -= dropped.size

        self._stream = sd.InputStream(
            samplerate=self.sr,
            channels=1,
            dtype='float32',
            device=self.device,
            blocksize=self.blocksize,
            callback=cb,
        )
        self._stream.start()

    def stop(self):
        self._stopped = True
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            self._buf.clear()

    def read(self, n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.float32)
        with self._lock:
            i = 0
            while i < n and self._buf:
                chunk = self._buf[0]
                take = min(n - i, chunk.size)
                out[i:i+take] = chunk[:take]
                if take == chunk.size:
                    self._buf.popleft()
                else:
                    self._buf[0] = chunk[take:]
                i += take
        return out

# ---------- ulaw / alaw encoders ----------
# (fast, branchy µ/A-law from float32; matches your PCMU/PCMA decoders’ expectations)
def pcmu_encode_from_float32(x: np.ndarray) -> bytes:
    # clamp to [-1,1], scale to 16-bit, then encode
    x = np.clip(x, -1.0, 1.0) * 32767.0
    s = x.astype(np.int16, copy=False)
    # µ-law constants
    BIAS = 0x84
    CLIP = 32635
    out = bytearray(s.size)
    for i, sample in enumerate(s):
        sign = 0x00
        v = sample
        if v < 0:
            v = -v - 1
            sign = 0x80
        if v > CLIP: v = CLIP
        v = v + BIAS
        # exponent
        exp = 7
        mask = 0x4000
        while (v & mask) == 0 and exp > 0:
            mask >>= 1; exp -= 1
        mant = (v >> (exp + 3)) & 0x0F
        out[i] = (~(sign | (exp << 4) | mant)) & 0xFF
    return bytes(out)

def pcma_encode_from_float32(x: np.ndarray) -> bytes:
    x = np.clip(x, -1.0, 1.0) * 32767.0
    s = x.astype(np.int16, copy=False)
    out = bytearray(s.size)
    for i, sample in enumerate(s):
        sign = 0x00 if sample >= 0 else 0x80
        if sample < 0: sample = -sample - 1
        sample >>= 4
        if sample > 0x1FFF: sample = 0x1FFF
        if sample >= 0x1000:
            exp = 7
        elif sample >= 0x800:
            exp = 6
        elif sample >= 0x400:
            exp = 5
        elif sample >= 0x200:
            exp = 4
        elif sample >= 0x100:
            exp = 3
        elif sample >= 0x80:
            exp = 2
        elif sample >= 0x40:
            exp = 1
        else:
            exp = 0
        mant = (sample >> (exp + 1)) & 0x0F
        out[i] = (sign | (exp << 4) | mant) ^ 0x55
    return bytes(out)


class RTPSender:
    """
    RTP sender with selectable source:
      - silence (default)
      - WAV file (16-bit PCM; optional loop)
      - Microphone (sounddevice)
    Encodes to PCMU (PT=0) or PCMA (PT=8) at self.sr with self.ptime_ms packets.
    """
    def __init__(self, remote_ip: str, remote_port: int,
                 ptime_ms: int = 20, samplerate: int = 8000, payload_type: int = 0, log=None):
        self.addr = (remote_ip, remote_port)
        self.ptime_ms = int(ptime_ms)
        self.sr = int(samplerate)
        self.pt = int(payload_type)   # 0=PCMU, 8=PCMA
        self.log = log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = random.randint(0, 65535)
        self.ts = random.randint(0, 2**32 - 1)
        self.ssrc = random.getrandbits(32)
        self._stop = threading.Event()
        self._thr = threading.Thread(target=self._run, name="RTPSender", daemon=True)

        # source management
        self._src_lock = threading.Lock()
        self._source: _BaseSource = SilenceSource(self.sr)

    # ---- public selection APIs ----
    def send_silence(self):
        self._swap_source(SilenceSource(self.sr))

    def send_wav(self, path: str, loop: bool = False, gain_db: float = 0.0):
        self._swap_source(WavSource(path, target_sr=self.sr, loop=loop, gain_db=gain_db))

    def send_microphone(self, device=None):
        # match packet blocksize to reduce jitter
        blocksize = int(self.sr * self.ptime_ms / 1000)
        src = MicSource(target_sr=self.sr, device=device, blocksize=blocksize)
        self._swap_source(src)

    def _swap_source(self, new_src: _BaseSource):
        with self._src_lock:
            old = self._source
            try:
                new_src.start()
            except Exception:
                # do not lose the old source if new failed to start
                if self.log: self.log.exception("[RTP TX] failed to start new source")
                raise
            self._source = new_src
            # stop old after swap (avoid gap)
            try:
                old.stop()
            except Exception:
                pass
        if self.log:
            name = type(new_src).__name__
            self.log.info(f"[RTP TX] source -> {name}")

    # ---- lifecycle ----
    def start(self):
        if self.log: self.log.info(f"[RTP TX] -> {self.addr[0]}:{self.addr[1]} PT={self.pt} ptime={self.ptime_ms}ms sr={self.sr}")
        self._thr.start()

    def stop(self):
        self._stop.set()
        # stop source first to release devices
        with self._src_lock:
            try: self._source.stop()
            except Exception: pass
        try: self.sock.close()
        except Exception: pass

    # ---- internals ----
    def _packet(self, payload: bytes) -> bytes:
        vpxcc = (2 << 6) | 0  # V=2,P=0,X=0,CC=0
        m_pt = self.pt & 0x7F
        header = struct.pack("!BBHII", vpxcc, m_pt, self.seq & 0xFFFF, self.ts & 0xFFFFFFFF, self.ssrc)
        self.seq = (self.seq + 1) & 0xFFFF
        return header + payload

    def _encode(self, f32: np.ndarray) -> bytes:
        if self.pt == 0:
            return pcmu_encode_from_float32(f32)
        elif self.pt == 8:
            return pcma_encode_from_float32(f32)
        else:
            # default to µ-law if unknown
            return pcmu_encode_from_float32(f32)

    def _run(self):
        samples_per_packet = int(self.sr * self.ptime_ms / 1000)
        next_send = time.perf_counter()
        while not self._stop.is_set():
            # 1) pull from current source
            with self._src_lock:
                src = self._source
            f32 = src.read(samples_per_packet)
            if f32.size != samples_per_packet:
                # zero-fill any underrun
                tmp = np.zeros(samples_per_packet, dtype=np.float32)
                take = min(f32.size, samples_per_packet)
                if take > 0: tmp[:take] = f32[:take]
                f32 = tmp
            # 2) encode -> payload
            payload = self._encode(f32)
            # 3) send
            try:
                self.sock.sendto(self._packet(payload), self.addr)
            except Exception:
                break
            # 4) advance RTP clock
            self.ts = (self.ts + samples_per_packet) & 0xFFFFFFFF
            # 5) pacing
            next_send += self.ptime_ms / 1000.0
            sleep_time = next_send - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # fell behind; catch up
                next_send = time.perf_counter()

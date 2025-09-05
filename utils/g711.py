import numpy as np


def pcmu_decode_to_float32(data: bytes) -> np.ndarray:
    """RTP PT=0 (μ-law) -> float32 mono [-1, 1]."""
    u = np.frombuffer(data, dtype=np.uint8) ^ 0xFF  # invert bits
    sign = (u & 0x80).astype(np.int16)
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    mag = ((mantissa.astype(np.int16) << 3) + 0x84) << exponent
    pcm16 = np.where(sign != 0, -mag, mag).astype(np.int16)
    return (pcm16.astype(np.float32) / 32768.0)


def pcma_decode_to_float32(data: bytes) -> np.ndarray:
    """RTP PT=8 (A-law) -> float32 mono [-1, 1]."""
    a = np.frombuffer(data, dtype=np.uint8) ^ 0x55
    sign = a & 0x80
    exponent = (a & 0x70) >> 4
    mantissa = a & 0x0F
    # magnitude
    mag = np.where(
        exponent > 0,
        ((mantissa.astype(np.int16) << 4) + 0x108) << (exponent - 1),
        (mantissa.astype(np.int16) << 4) + 8
    )
    pcm16 = np.where(sign != 0, -mag, mag).astype(np.int16)
    return (pcm16.astype(np.float32) / 32768.0)


def pcmu_encode_from_float32(x: np.ndarray) -> bytes:
    """float32 [-1,1] -> μ-law bytes (RTP PT=0)."""
    # clamp to int16
    s = np.clip(x, -1.0, 1.0)
    s = (s * 32767.0).astype(np.int16)

    # μ-law encode
    # based on the inverse of decode above
    s16 = s.astype(np.int16)
    sign = (s16 < 0).astype(np.int16)
    mag = np.abs(s16).astype(np.int32)
    mag = np.clip(mag + 0x84, 0, 0x7FFF)
    exponent = np.zeros_like(mag)
    # find exponent as position of msb among bits [7..13]
    tmp = mag.copy()
    for e in range(7):
        mask = (tmp > 0x7F)
        exponent[mask] += 1
        tmp[mask] >>= 1
    mantissa = (mag >> (exponent + 3)) & 0x0F
    u = (~((sign << 7) | (exponent << 4) | mantissa)).astype(np.uint8)
    return u.tobytes()

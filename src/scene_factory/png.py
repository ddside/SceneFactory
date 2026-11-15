"""Bounded validation of non-interlaced PNG structure and full zlib image stream."""
from pathlib import Path
import struct
import zlib


def verify_png(path, resolution):
    data = Path(path).read_bytes()
    if len(data) > 32 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Invalid PNG artifact: {path}")
    offset, chunks, image, header, ended = 8, [], bytearray(), None, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("PNG truncated chunk header")
        length = struct.unpack(">I", data[offset:offset+4])[0]
        kind = data[offset+4:offset+8]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG truncated chunk data")
        payload = data[offset+8:offset+8+length]
        crc = struct.unpack(">I", data[offset+8+length:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError("PNG chunk CRC mismatch")
        if kind == b"IHDR":
            if chunks or length != 13:
                raise ValueError("PNG invalid IHDR")
            header = struct.unpack(">IIBBBBB", payload)
        elif not chunks:
            raise ValueError("PNG missing initial IHDR")
        if kind == b"IDAT":
            image.extend(payload)
        if kind == b"IEND":
            if length or end != len(data):
                raise ValueError("PNG invalid IEND/trailing bytes")
            ended = True
        chunks.append(kind)
        offset = end
    if not ended or header is None or not image:
        raise ValueError("PNG missing header, image data or IEND")
    width, height, bits, color, compression, filtering, interlace = header
    expected_size=(resolution,resolution) if type(resolution) is int else tuple(resolution)
    if (width, height) != expected_size:
        raise ValueError("Preview resolution mismatch")
    channels = {0:1, 2:3, 3:1, 4:2, 6:4}.get(color)
    if not channels or bits not in (1,2,4,8,16) or compression or filtering or interlace:
        raise ValueError("PNG unsupported encoding (requires non-interlaced PNG)")
    if color in (2,4,6) and bits not in (8,16):
        raise ValueError("PNG invalid bit depth")
    if color == 3 and (bits == 16 or b"PLTE" not in chunks):
        raise ValueError("PNG invalid palette")
    stride = (width * channels * bits + 7) // 8 + 1
    expected = stride * height
    decoder = zlib.decompressobj()
    try:
        pixels = decoder.decompress(bytes(image), expected + 1)
    except zlib.error as exc:
        raise ValueError(f"PNG corrupt zlib stream: {exc}") from exc
    if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG incomplete or oversized decoded image data")
    if any(pixels[i] > 4 for i in range(0, len(pixels), stride)):
        raise ValueError("PNG invalid scanline filter")

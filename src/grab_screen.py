#!/usr/bin/env python3
"""Grab the live framebuffer from a running Swiss over HTTP.

Swiss answers GET /screen.bin with a 16-byte little-endian header followed by
the raw 16bpp XFB:

    0  char[4]  "SWSC"
    4  u16      width
    6  u16      height
    8  u32      format (0 = raw 16bpp, colour space not specified)
   12  u32      payload size

The XFB is produced by GX_CopyDisp, so the pixels are either YUY2 (VI YUV mode)
or RGB565. We cannot tell from the header, so both decodes are written out and
you keep the one that looks sane.

Usage: python tools/grab_screen.py 192.168.1.2 [outdir]
"""
import os
import socket
import struct
import sys


def fetch(host, path="/screen.bin", port=80, timeout=20):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    raw = b"".join(chunks)
    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        raise RuntimeError("no HTTP header in response")
    return raw[sep + 4:]


def write_bmp(path, width, height, rgb_rows):
    stride = (width * 3 + 3) & ~3
    pad = stride - width * 3
    data = bytearray()
    for y in range(height - 1, -1, -1):
        row = rgb_rows[y]
        data += row
        data += b"\x00" * pad
    with open(path, "wb") as fh:
        fh.write(b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54))
        # rows were emitted bottom-up, so declare a positive (bottom-up) height
        fh.write(struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0,
                             len(data), 2835, 2835, 0, 0))
        fh.write(data)


def clamp(v):
    return 0 if v < 0 else (255 if v > 255 else v)


def decode_yuy2(buf, w, h):
    rows = []
    for y in range(h):
        base = y * w * 2
        row = bytearray()
        for x in range(0, w, 2):
            y0, u, y1, v = buf[base + x * 2: base + x * 2 + 4]
            for yy in (y0, y1):
                c = yy - 16
                r = (298 * c + 409 * (v - 128) + 128) >> 8
                g = (298 * c - 100 * (u - 128) - 208 * (v - 128) + 128) >> 8
                b = (298 * c + 516 * (u - 128) + 128) >> 8
                row += bytes((clamp(b), clamp(g), clamp(r)))  # BMP is BGR
        rows.append(row)
    return rows


def decode_rgb565(buf, w, h, big_endian=True):
    rows = []
    for y in range(h):
        base = y * w * 2
        row = bytearray()
        for x in range(w):
            off = base + x * 2
            v = (buf[off] << 8 | buf[off + 1]) if big_endian else (buf[off + 1] << 8 | buf[off])
            r = ((v >> 11) & 0x1F) * 255 // 31
            g = ((v >> 5) & 0x3F) * 255 // 63
            b = (v & 0x1F) * 255 // 31
            row += bytes((b, g, r))
        rows.append(row)
    return rows


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "out")
    os.makedirs(outdir, exist_ok=True)

    payload = fetch(host)
    if len(payload) < 16 or payload[:4] != b"SWSC":
        print(f"unexpected response ({len(payload)} bytes): {payload[:32]!r}")
        return 1

    w, h, fmt, size = struct.unpack("<HHII", payload[4:16])
    body = payload[16:16 + size]
    print(f"header: {w}x{h} fmt={fmt} size={size} (got {len(body)} bytes)")

    # Confirmed on real hardware: the XFB that GX_CopyDisp produces here is
    # YUY2. The RGB565 decodes are kept behind --all for future video modes.
    p1 = os.path.join(outdir, "screen.bmp")
    write_bmp(p1, w, h, decode_yuy2(body, w, h))
    print("wrote", p1)

    if "--all" in sys.argv:
        p2 = os.path.join(outdir, "screen_rgb565.bmp")
        write_bmp(p2, w, h, decode_rgb565(body, w, h, big_endian=True))
        print("wrote", p2)
        p3 = os.path.join(outdir, "screen_rgb565le.bmp")
        write_bmp(p3, w, h, decode_rgb565(body, w, h, big_endian=False))
        print("wrote", p3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import struct
import zlib
from pathlib import Path


def write_png(path: Path, size: int):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            dx = x - size / 2
            dy = y - size / 2
            radius = (dx * dx + dy * dy) ** 0.5
            if radius < size * 0.38:
                color = (22, 134, 232, 255)
            elif radius < size * 0.44:
                color = (214, 228, 240, 255)
            else:
                color = (255, 255, 255, 0)
            if abs(dx) < size * 0.045 and dy < -size * 0.05 and radius < size * 0.34:
                color = (255, 255, 255, 255)
            if abs(dy) < size * 0.045 and radius < size * 0.22:
                color = (255, 255, 255, 255)
            row.extend(color)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    payload += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main():
    root = Path(__file__).resolve().parents[1]
    write_png(root / "fpk" / "ICON.PNG", 64)
    write_png(root / "fpk" / "ICON_256.PNG", 256)
    write_png(root / "fpk" / "app" / "ui" / "images" / "icon_64.png", 64)
    write_png(root / "fpk" / "app" / "ui" / "images" / "icon_256.png", 256)
    write_png(root / "fpk" / "app" / "ui" / "images" / "icon.png", 64)
    write_png(root / "fpk" / "app" / "ui" / "images" / "icon-64.png", 64)
    write_png(root / "fpk" / "app" / "ui" / "images" / "icon-256.png", 256)


if __name__ == "__main__":
    main()

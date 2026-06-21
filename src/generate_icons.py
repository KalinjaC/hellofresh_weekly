"""Generates simple PNG icons for the PWA manifest. Run once."""
import struct, zlib, io

def _png_chunk(tag, data):
    c = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', c)

def make_png(size, bg=(152, 194, 64), text_char='🍽'):
    # Simple solid-color PNG with no text (emoji rendering is platform-specific)
    w = h = size
    raw = b''
    for _ in range(h):
        row = b'\x00'  # filter byte
        for _ in range(w):
            row += bytes(bg) + b'\xff'  # RGBA
        raw += row
    compressed = zlib.compress(raw)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', ihdr)
        + _png_chunk(b'IDAT', compressed)
        + _png_chunk(b'IEND', b'')
    )

if __name__ == '__main__':
    from pathlib import Path
    static = Path(__file__).parent.parent / 'static'
    for size in (192, 512):
        (static / f'icon-{size}.png').write_bytes(make_png(size))
        print(f'Generated icon-{size}.png')

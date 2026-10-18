"""Set the frame rate in a SWF header.  python set_fps.py in.swf out.swf 60"""
import struct, sys, zlib

src, dst, fps = sys.argv[1], sys.argv[2], float(sys.argv[3])
d = open(src, "rb").read()
assert d[:3] == b"CWS", "expected zlib-compressed SWF"
body = bytearray(zlib.decompress(d[8:]))
rect = (5 + 4 * (body[0] >> 3) + 7) // 8          # RECT size in bytes
body[rect:rect + 2] = struct.pack("<H", round(fps * 256))  # 8.8 fixed point
# FileLength is the UNCOMPRESSED size; AIR refuses to load the file otherwise
open(dst, "wb").write(d[:4] + struct.pack("<I", 8 + len(body)) + zlib.compress(bytes(body), 9))
print(f"{dst}: {fps} fps")

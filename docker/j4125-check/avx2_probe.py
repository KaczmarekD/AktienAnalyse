"""Gegenprobe der J4125-Pruefung: fuehrt genau eine AVX2-Instruktion aus.

Unter QEMU mit -cpu Denverton muss der Prozess mit SIGILL sterben (Exit-Code 132).
Laeuft er durch, faengt die Emulation AVX2 nicht ab und die Pruefung waere wertlos.
Aufruf nur ueber run.sh.
"""

import ctypes
import mmap

# vpaddd ymm0, ymm0, ymm0 ; vzeroupper ; ret
CODE = bytes([0xC5, 0xFD, 0xFE, 0xC0, 0xC5, 0xF8, 0x77, 0xC3])

page = mmap.mmap(-1, mmap.PAGESIZE, prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
page.write(CODE)
ctypes.CFUNCTYPE(None)(ctypes.addressof(ctypes.c_char.from_buffer(page)))()
print("AVX2-Instruktion ausgefuehrt")

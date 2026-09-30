#!/bin/sh
# J4125-Pruefung (ADR-0008), Einstieg der Stufe j4125-check im Dockerfile.
# Argumente gehen an Python unter der Emulation (Standard: check_imports.py).
set -u

QEMU="qemu-x86_64 -cpu Denverton,-xsavec"

# Gegenprobe: Eine AVX2-Instruktion muss unter der Emulation mit SIGILL enden (128+4).
# Sonst faengt QEMU AVX2 nicht ab und ein gruenes Ergebnis waere wertlos.
# stderr weg: QEMU meldet dabei erwartungsgemaess "uncaught target signal 4".
$QEMU /usr/local/bin/python3 /opt/j4125/avx2_probe.py 2>/dev/null
status=$?
if [ "$status" -ne 132 ]; then
    echo "FEHLER: AVX2-Gegenprobe endete mit Exit-Code $status statt 132 (SIGILL)" >&2
    exit 1
fi
echo "Gegenprobe ok: AVX2 endet unter der Emulation mit SIGILL"

exec $QEMU /usr/local/bin/python3 "$@"

# J4125-Pruefung (ADR-0008): fuehrt Python im App-Image unter QEMU mit einem CPU-Modell
# ohne AVX/AVX2 aus. Denverton (Goldmont) ist das naechste QEMU-Modell zum J4125
# (Goldmont Plus): x86-64-v2, SSE4.2, kein AVX.
# Nutzung: make check-j4125
ARG APP_IMAGE=value-analyzer:local
FROM ${APP_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends qemu-user \
    && rm -rf /var/lib/apt/lists/*

COPY docker/j4125-check/check_imports.py /opt/j4125/check_imports.py

# -xsavec: Die Emulation (TCG) bildet XSAVEC nicht nach und wuerde sonst bei jedem
# Prozessstart warnen; fuer die AVX-Frage spielt es keine Rolle.
ENTRYPOINT ["qemu-x86_64", "-cpu", "Denverton,-xsavec", "/usr/local/bin/python3"]
CMD ["/opt/j4125/check_imports.py"]

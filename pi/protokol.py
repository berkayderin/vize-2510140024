"""ESP32 <-> Pi satır protokolü.

Biçim: $GOVDE*HH\\r\\n  —  HH, '$' ile '*' arasındaki karakterlerin XOR'unun iki haneli onaltılık hâli.
Örnek: kodla("LED,1") -> b"$LED,1*50\\r\\n"
"""


class ProtokolHatasi(Exception):
    """neden: 'BICIM' (satır yapısı bozuk) veya 'CHECKSUM' (XOR tutmuyor)."""

    def __init__(self, neden, satir=b""):
        super().__init__(f"{neden}: {satir!r}")
        self.neden = neden
        self.satir = satir


def xor_toplami(govde: str) -> int:
    x = 0
    for karakter in govde.encode("ascii"):
        x ^= karakter
    return x


def kodla(govde: str) -> bytes:
    return f"${govde}*{xor_toplami(govde):02X}\r\n".encode("ascii")


def coz(ham: bytes) -> list:
    """Bir satırı doğrular ve alanlara ayırır: b'$ACK,LED,1*35\\r\\n' -> ['ACK', 'LED', '1']"""
    try:
        satir = ham.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ProtokolHatasi("BICIM", ham)
    if not satir.startswith("$") or satir.count("*") != 1:
        raise ProtokolHatasi("BICIM", ham)
    govde, hh = satir[1:].split("*")
    if len(hh) != 2:
        raise ProtokolHatasi("BICIM", ham)
    try:
        beklenen = int(hh, 16)
    except ValueError:
        raise ProtokolHatasi("BICIM", ham)
    if xor_toplami(govde) != beklenen:
        raise ProtokolHatasi("CHECKSUM", ham)
    return govde.split(",")


def imu_coz(alanlar: list) -> dict:
    """['IMU', t, ax, ay, az, gx, gy, gz] -> sözlük (ivme g, dönü °/s)"""
    if len(alanlar) != 8 or alanlar[0] != "IMU":
        raise ProtokolHatasi("BICIM")
    try:
        t = int(alanlar[1])
        ax, ay, az, gx, gy, gz = (float(a) for a in alanlar[2:])
    except ValueError:
        raise ProtokolHatasi("BICIM")
    return {"t_ms": t, "ax": ax, "ay": ay, "az": az, "gx": gx, "gy": gy, "gz": gz}


if __name__ == "__main__":
    # küçük kendi kendine deneme: python protokol.py
    assert kodla("LED,1") == b"$LED,1*50\r\n"
    assert kodla("HIZ,50") == b"$HIZ,50*72\r\n"
    assert coz(b"$ACK,LED,1*35\r\n") == ["ACK", "LED", "1"]
    for bozuk, neden in [(b"$LED,1*51\r\n", "CHECKSUM"), (b"LED,1*50\r\n", "BICIM"), (b"$LED,1\r\n", "BICIM")]:
        try:
            coz(bozuk)
        except ProtokolHatasi as h:
            assert h.neden == neden, (bozuk, h.neden)
        else:
            raise AssertionError(bozuk)
    print("protokol.py: tüm denemeler geçti")

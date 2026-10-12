"""Encodeur protobuf minimal — construit les fixtures de tests.

Le protocole down_module_day_data n'a pas de .proto public : la structure a été
déduite par rétro-ingénierie (voir references/hoymiles-cloud-day-data-protobuf.md).
Ces fonctions reproduisent exactement ce que le parseur attend, ce qui permet de
tester hoymiles_api.parse_day_data et backfill.parse_day_series sans réseau.
"""
import struct


def varint(value):
    out = b""
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out += bytes([b | 0x80])
        else:
            out += bytes([b])
            return out


def tag(field, wire):
    return varint((field << 3) | wire)


def vfield(field, value):
    """Champ varint (wire 0)."""
    return tag(field, 0) + varint(value)


def ld(field, payload):
    """Champ length-delimited (wire 2)."""
    return tag(field, 2) + varint(len(payload)) + payload


def f32(field, value):
    """Champ fixed32 contenant un float IEEE-754 little-endian (wire 5)."""
    return tag(field, 5) + struct.pack("<f", value)


def f32_raw(field, raw):
    """Champ fixed32 contenant un uint32 brut (utilisé pour watt/énergie)."""
    return tag(field, 5) + struct.pack("<I", raw)


def fseries(field, values):
    """Série de floats (wire 2, packed)."""
    return ld(field, struct.pack(f"<{len(values)}f", *values))


def i16series(field, values):
    """Série int16 (wire 2, packed) — champs d'alarme 8/9."""
    return ld(field, struct.pack(f"<{len(values)}h", *values))


def point(up, ip, watt, energy=None):
    """Point d'un port : 1=up(V) 2=ip(A) 3=watt(W) 4=énergie cumulée jour(Wh)."""
    out = f32(1, up) + f32(2, ip) + f32(3, watt)
    if energy is not None:
        out += f32(4, energy)
    return out


def port_msg(port, points):
    """Message port : 1 = numéro de port, 2 = batch (1 = points répétés)."""
    batch = b"".join(ld(1, p) for p in points)
    return vfield(1, port) + ld(2, batch)


def micro_msg(micro_id, times, ports, freq=None, temp=None, uac=None, alarms=None):
    """Message micro : 1 = id, 2 = main (times, ports, séries AC, alarmes)."""
    main = b""
    for t in times:
        main += ld(2, t.encode())
    for pnum, points in ports.items():
        main += ld(4, port_msg(pnum, points))
    if freq is not None:
        main += fseries(5, freq)
    if temp is not None:
        main += fseries(6, temp)
    if uac is not None:
        main += fseries(7, uac)
    if alarms is not None:
        main += i16series(8, alarms)
    return vfield(1, micro_id) + ld(2, main)


def day_blob(sid, date, micros):
    """Blob complet : 1 = sid, 2 = date, 3 = micros répétés."""
    out = vfield(1, sid) + ld(2, date.encode())
    for m in micros:
        out += ld(3, m)
    return out

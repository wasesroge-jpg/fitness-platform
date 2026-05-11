"""Minimal FIT file writer for weekly workout plans.

The FIT format is a binary protocol from Garmin/ANT+. This module writes a
syntactically valid FIT file containing a `file_id` message and one
`workout` + `workout_step` per planned session. Apps like Garmin Connect
accept these as scheduled workouts.

Implementation is intentionally minimal — only the fields we need are
encoded, not the entire FIT profile.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Iterable


FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]


def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF]
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xF]
    return crc & 0xFFFF


def _fit_timestamp(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int((dt - FIT_EPOCH).total_seconds())


# FIT base types: (number, size, struct fmt, invalid)
TYPE_UINT8 = (0x02, 1, "B", 0xFF)
TYPE_UINT16 = (0x84, 2, "H", 0xFFFF)
TYPE_UINT32 = (0x86, 4, "I", 0xFFFFFFFF)
TYPE_STRING = (0x07, 1, "s", 0x00)
TYPE_ENUM = (0x00, 1, "B", 0xFF)


SPORT_MAP = {
    "running": 1,
    "cycling": 2,
    "swimming": 5,
    "walking": 11,
    "rowing": 15,
    "training": 10,
    "other": 0,
}


def _definition_msg(local_type: int, global_num: int, fields: list[tuple[int, tuple]]) -> bytes:
    """Build a FIT definition message.

    fields: list of (field_def_number, base_type)
    """
    header = bytes([0x40 | (local_type & 0x0F)])
    reserved = b"\x00"
    arch = b"\x00"  # little-endian
    global_num_b = struct.pack("<H", global_num)
    nfields = bytes([len(fields)])
    field_defs = b""
    for fdn, (type_num, size, _, _) in fields:
        field_defs += bytes([fdn, size, type_num])
    return header + reserved + arch + global_num_b + nfields + field_defs


def _data_msg(local_type: int, fields: list[tuple[tuple, object]]) -> bytes:
    header = bytes([local_type & 0x0F])
    payload = b""
    for (type_num, size, fmt, invalid), value in fields:
        if fmt == "s":
            if not isinstance(value, str):
                value = "" if value is None else str(value)
            data = value.encode("utf-8")[: size - 1]
            data += b"\x00" * (size - len(data))
            payload += data
        else:
            if value is None:
                value = invalid
            payload += struct.pack("<" + fmt, value)
    return header + payload


def build_fit(week_plan: Iterable[dict]) -> bytes:
    """Build a FIT file from a list of planned workouts.

    Each dict needs: name, sport, distance_km, duration_min, scheduled_at (datetime).
    """
    plan = list(week_plan)
    body = b""
    now_ts = _fit_timestamp(datetime.now(timezone.utc))

    # ----- file_id (global #0) -----
    file_id_fields = [
        (3, TYPE_UINT32),  # serial_number
        (4, TYPE_UINT32),  # time_created
        (1, TYPE_UINT16),  # manufacturer
        (2, TYPE_UINT16),  # product
        (0, TYPE_ENUM),    # type
    ]
    body += _definition_msg(0, 0, file_id_fields)
    body += _data_msg(
        0,
        [
            (TYPE_UINT32, 0xDEADBEEF),
            (TYPE_UINT32, now_ts),
            (TYPE_UINT16, 255),  # manufacturer = development
            (TYPE_UINT16, 0),
            (TYPE_ENUM, 5),  # 5 = workout
        ],
    )

    # ----- workout (global #26) and workout_step (global #27) -----
    workout_def_fields = [
        (8, (TYPE_STRING[0], 16, "s", 0)),  # wkt_name (16-char string)
        (4, TYPE_UINT16),                    # sport (using UINT16 to keep it simple)
        (6, TYPE_UINT16),                    # num_valid_steps
    ]
    step_def_fields = [
        (0, (TYPE_STRING[0], 16, "s", 0)),   # message_index → reuse string for name
        (1, TYPE_UINT32),                    # duration_value (ms)
        (3, TYPE_UINT32),                    # target_value
        (4, TYPE_UINT8),                     # duration_type
        (5, TYPE_UINT8),                     # target_type
        (7, TYPE_UINT8),                     # intensity
    ]

    body += _definition_msg(1, 26, workout_def_fields)
    body += _definition_msg(2, 27, step_def_fields)

    for w in plan:
        name = (w.get("name") or "Workout")[:15]
        sport = SPORT_MAP.get((w.get("sport") or "running").lower(), 0)
        body += _data_msg(
            1,
            [
                ((TYPE_STRING[0], 16, "s", 0), name),
                (TYPE_UINT16, sport),
                (TYPE_UINT16, 3),  # warmup / main / cooldown
            ],
        )
        duration_min = max(1, int(w.get("duration_min") or 30))
        body += _data_msg(
            2,
            [
                ((TYPE_STRING[0], 16, "s", 0), "Warm up"),
                (TYPE_UINT32, 10 * 60 * 1000),
                (TYPE_UINT32, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 1),  # warmup
            ],
        )
        body += _data_msg(
            2,
            [
                ((TYPE_STRING[0], 16, "s", 0), "Main"),
                (TYPE_UINT32, max(1, duration_min - 15) * 60 * 1000),
                (TYPE_UINT32, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 0),  # active
            ],
        )
        body += _data_msg(
            2,
            [
                ((TYPE_STRING[0], 16, "s", 0), "Cool down"),
                (TYPE_UINT32, 5 * 60 * 1000),
                (TYPE_UINT32, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 0),
                (TYPE_UINT8, 2),  # cooldown
            ],
        )

    # ----- header + CRC -----
    header_size = 14
    protocol_version = 0x20
    profile_version = 2078
    data_size = len(body)
    signature = b".FIT"
    pre_crc_header = struct.pack(
        "<BBHI4s", header_size, protocol_version, profile_version, data_size, signature
    )
    header_crc = _crc16(pre_crc_header)
    header = pre_crc_header + struct.pack("<H", header_crc)

    file_crc = _crc16(header + body)
    return header + body + struct.pack("<H", file_crc)

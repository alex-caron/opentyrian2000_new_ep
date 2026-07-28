#!/usr/bin/env python3
"""Generate the custom Episode 6 in Tyrian's original data formats."""

from __future__ import annotations

import argparse
import json
import random
import struct
import sys
from pathlib import Path


CRYPT_KEY = (204, 129, 63, 255, 71, 19, 25, 62, 1, 99)
EVENT_STRUCT = struct.Struct("<HBhhbbbB")
ARCHIVE_OFFSET_STRUCT = struct.Struct("<I")
MAP_PAYLOAD_SIZE = 22_368
ITEM_DATA_MIN_SIZE = 0x22C3D
SHIELD_RECORD_SIZE = 37
SHIELD_RECORD_COUNT = 12
ENEMY_RECORD_SIZE = 77
EARLY_ENEMY_TABLE_OFFSET = 0x27EF3 + SHIELD_RECORD_COUNT * SHIELD_RECORD_SIZE
LATE_ENEMY_TABLE_OFFSET = 0x22C3D + SHIELD_RECORD_COUNT * SHIELD_RECORD_SIZE
ENEMY_SPAWN_EVENT_TYPES = {6, 7, 10, 12, 15, 17, 18, 23, 32, 56, 58}
ENEMY_DEATH_EVENT_TYPES = {33, 45}
UNSUPPORTED_RUNTIME_EVENT_TYPES = {59}
MAX_ENEMY_SHAPE_BANK = 36


def encrypt_pascal_string(text: str) -> bytes:
    plain = text.encode("cp437")
    if len(plain) > 255:
        raise ValueError(f"Tyrian strings are limited to 255 bytes: {text!r}")

    encrypted = bytearray(len(plain))
    for index, value in enumerate(plain):
        previous = encrypted[index - 1] if index else 0
        encrypted[index] = value ^ CRYPT_KEY[index % len(CRYPT_KEY)] ^ previous
    return bytes((len(encrypted),)) + encrypted


def decrypt_pascal_strings(data: bytes) -> list[str]:
    strings: list[str] = []
    offset = 0
    while offset < len(data):
        length = data[offset]
        offset += 1
        encrypted = bytearray(data[offset : offset + length])
        if len(encrypted) != length:
            raise ValueError("Truncated encrypted Pascal string")
        offset += length

        for index in range(length - 1, -1, -1):
            encrypted[index] ^= CRYPT_KEY[index % len(CRYPT_KEY)]
            if index:
                encrypted[index] ^= encrypted[index - 1]
        strings.append(encrypted.decode("cp437"))
    return strings


def encode_pascal_strings(strings: list[str]) -> bytes:
    return b"".join(encrypt_pascal_string(text) for text in strings)


def read_archive_offsets(data: bytes) -> tuple[int, tuple[int, ...]]:
    record_count = struct.unpack_from("<H", data, 0)[0]
    offsets = struct.unpack_from(f"<{record_count}I", data, 2)
    return record_count, offsets


def parse_level_header(data: bytes, start: int, map_start: int) -> tuple[bytes, list[tuple[int, ...]]]:
    cursor = start + 8  # map file, shape file, and three map-X words
    enemy_count = struct.unpack_from("<H", data, cursor)[0]
    cursor += 2 + enemy_count * 2
    event_count_position = cursor
    event_count = struct.unpack_from("<H", data, cursor)[0]
    cursor += 2

    events: list[tuple[int, ...]] = []
    for _ in range(event_count):
        events.append(EVENT_STRUCT.unpack_from(data, cursor))
        cursor += EVENT_STRUCT.size

    if cursor != map_start:
        raise ValueError(
            f"Unexpected level-header size: parsed to {cursor}, map begins at {map_start}"
        )
    return data[start:event_count_position], events


def event_from_json(value: dict[str, object]) -> tuple[int, ...]:
    return (
        int(value["time"]),
        int(value["type"]),
        int(value.get("data1", 0)),
        int(value.get("data2", 0)),
        int(value.get("data3", 0)),
        int(value.get("data5", 0)),
        int(value.get("data6", 0)),
        int(value.get("data4", 0)),
    )


def enemy_record_index(enemy_id: int) -> int:
    """Translate Tyrian's split enemy ID ranges into their packed table index."""
    if 0 <= enemy_id <= 850:
        return enemy_id
    if 1001 <= enemy_id <= 1850:
        return 851 + enemy_id - 1001
    raise ValueError(f"Invalid enemy ID {enemy_id}")


def read_enemy_record(data: bytes, table_start: int, enemy_id: int) -> bytes:
    start = table_start + enemy_record_index(enemy_id) * ENEMY_RECORD_SIZE
    record = data[start : start + ENEMY_RECORD_SIZE]
    if len(record) != ENEMY_RECORD_SIZE:
        raise ValueError(f"Enemy table is truncated at ID {enemy_id}")
    return record


def collect_enemy_records(
    events: list[tuple[int, ...]], source_data: bytes, table_start: int
) -> dict[int, bytes]:
    """Collect every enemy record reached directly or through launches/deaths."""
    enemy_ids = {
        event[2] for event in events if event[1] in ENEMY_SPAWN_EVENT_TYPES
    }
    enemy_ids.update(
        event[2]
        for event in events
        if event[1] in ENEMY_DEATH_EVENT_TYPES
        and (0 <= event[2] <= 850 or 1001 <= event[2] <= 1850)
    )
    pending = list(enemy_ids)
    records: dict[int, bytes] = {}
    while pending:
        enemy_id = pending.pop()
        record = read_enemy_record(source_data, table_start, enemy_id)
        records[enemy_id] = record
        launch_type = struct.unpack_from("<H", record, 71)[0] % 1000
        death_type = struct.unpack_from("<H", record, 75)[0]
        for child_type in (launch_type, death_type):
            if (
                child_type > 0
                and child_type not in enemy_ids
                and (child_type <= 850 or 1001 <= child_type <= 1850)
            ):
                enemy_ids.add(child_type)
                pending.append(child_type)
    return records


def build_events(
    config: dict[str, object],
    source_events: list[tuple[int, ...]],
    source_episode: int,
    source_level: int,
    load_source_events,
) -> tuple[list[tuple[int, ...]], dict[int, list[tuple[int, ...]]]]:
    events: list[tuple[int, ...]] = []
    events_by_source_episode: dict[int, list[tuple[int, ...]]] = {}

    def append_event(event: tuple[int, ...], event_source_episode: int) -> None:
        events.append(event)
        events_by_source_episode.setdefault(event_source_episode, []).append(event)

    for index in config.get("preamble_source_events", []):
        append_event(source_events[int(index)], source_episode)

    for segment in config.get("source_segments", []):
        segment_episode = int(segment.get("source_episode", source_episode))
        segment_level = int(segment.get("source_level", source_level))
        segment_source_events = (
            source_events
            if (segment_episode, segment_level) == (source_episode, source_level)
            else load_source_events(segment_episode, segment_level)
        )
        first = int(segment["first_event"])
        last = int(segment["last_event"])
        time_scale = int(segment.get("time_scale", 1))
        time_offset = int(segment["time_offset"])
        excluded_event_types = {int(event_type) for event_type in segment.get("exclude_event_types", [])}
        excluded_enemy_ids = {int(enemy_id) for enemy_id in segment.get("exclude_enemy_ids", [])}
        if time_scale <= 0:
            raise ValueError(f"Event time scale must be positive in segment {segment['name']!r}")
        if first < 0 or last >= len(segment_source_events) or first > last:
            raise ValueError(f"Invalid source event range {first}..{last}")
        for source_event in segment_source_events[first : last + 1]:
            if source_event[1] in excluded_event_types:
                continue
            if source_event[1] in ENEMY_SPAWN_EVENT_TYPES and source_event[2] in excluded_enemy_ids:
                continue
            copied = list(source_event)
            copied[0] = copied[0] * time_scale + time_offset
            if copied[0] < 0:
                raise ValueError(f"Event time became negative in segment {segment['name']!r}")
            append_event(tuple(copied), segment_episode)

    for event in config.get("events", config.get("extra_events", [])):
        append_event(
            event_from_json(event),
            int(event.get("source_episode", source_episode)),
        )

    for formation in config.get("formations", []):
        start = int(formation["start"])
        interval = int(formation.get("interval", 0))
        link = int(formation.get("link", 0))
        for index, x_position in enumerate(formation["positions"]):
            append_event(
                (
                    start + interval * index,
                    int(formation.get("type", 15)),
                    int(formation["enemy"]),
                    int(x_position),
                    int(formation.get("y_speed", 0)),
                    int(formation.get("y_offset", 0)),
                    int(formation.get("fixed_y", 0)),
                    link,
                ),
                int(formation.get("source_episode", source_episode)),
            )

    for wave in config.get("random_waves", []):
        start = int(wave["start"])
        end = int(wave["end"])
        count = int(wave["count"])
        enemies = [int(enemy) for enemy in wave["enemies"]]
        event_types = [int(event_type) for event_type in wave.get("types", [15])]
        y_speeds = [int(speed) for speed in wave.get("y_speeds", [1, 2, 3])]
        y_offsets = [int(offset) for offset in wave.get("y_offsets", [0])]
        fixed_y_values = [int(value) for value in wave.get("fixed_y", [0])]
        x_min = int(wave.get("x_min", 20))
        x_max = int(wave.get("x_max", 260))
        link_start = int(wave.get("link_start", 200))
        wave_source_episode = int(wave.get("source_episode", source_episode))
        if (
            start < 0
            or end < start
            or count <= 0
            or count > end - start + 1
            or not enemies
            or not event_types
            or not y_speeds
            or not y_offsets
            or not fixed_y_values
            or x_min > x_max
            or link_start < 0
            or link_start + count - 1 > 253
        ):
            raise ValueError(f"Invalid generated random wave {wave.get('name', '')!r}")
        if any(event_type not in ENEMY_SPAWN_EVENT_TYPES for event_type in event_types):
            raise ValueError(
                f"Random wave {wave.get('name', '')!r} contains a non-spawn event type"
            )
        rng = random.Random(int(wave["seed"]))
        times = sorted(rng.sample(range(start, end + 1), count))
        for index, event_time in enumerate(times):
            append_event(
                (
                    event_time,
                    rng.choice(event_types),
                    rng.choice(enemies),
                    rng.randint(x_min, x_max),
                    rng.choice(y_speeds),
                    rng.choice(y_offsets),
                    rng.choice(fixed_y_values),
                    link_start + index,
                ),
                wave_source_episode,
            )

    events.sort(key=lambda event: event[0])
    for event in events:
        EVENT_STRUCT.pack(*event)  # range validation
    return events, events_by_source_episode


def build_shard_run_map(source_payload: bytes) -> bytes:
    """Recompose intact Episode 5 tile structures into a new traversal.

    Tyrian's map bytes are not independent square tiles.  Many entries are
    transparent edge/corner pieces which only render correctly beside their
    original neighbours.  Keep the coherent base and canyon layers, then move
    complete parallax scenes as rectangular row bands.  This changes the
    mission's scenery order without slicing any multi-tile artwork apart.
    """
    if len(source_payload) != MAP_PAYLOAD_SIZE:
        raise ValueError("Cannot author a map from an invalid source payload")

    tile_lookup = source_payload[: 3 * 128 * 2]
    layer1_start = len(tile_lookup)
    layer2_start = layer1_start + 300 * 14
    layer3_start = layer2_start + 600 * 14
    layer1 = source_payload[layer1_start:layer2_start]
    source_layer2 = source_payload[layer2_start:layer3_start]
    layer3 = source_payload[layer3_start:]

    blank_row = bytes((71,)) * 14
    layer2_rows = [blank_row for _ in range(600)]
    source_rows = [source_layer2[row * 14 : (row + 1) * 14] for row in range(600)]

    # Each tuple is (source first row, source row after last, destination row).
    # The bands include every tile of their set pieces plus transparent padding.
    scene_moves = (
        (442, 484, 552),  # rift mouth: shown first instead of last
        (503, 525, 515),  # isolated shard cluster
        (529, 600, 420),  # large living-rock passage
    )
    for source_first, source_end, destination in scene_moves:
        height = source_end - source_first
        if destination + height > len(layer2_rows):
            raise ValueError("Shard Run parallax scene extends beyond the map")
        layer2_rows[destination : destination + height] = source_rows[source_first:source_end]

    layer2 = b"".join(layer2_rows)
    if layer2 == source_layer2:
        raise ValueError("Shard Run map did not change the source parallax layout")

    payload = tile_lookup + layer1 + layer2 + layer3
    if len(payload) != MAP_PAYLOAD_SIZE:
        raise ValueError(f"Authored map is {len(payload)} bytes, expected {MAP_PAYLOAD_SIZE}")
    return payload


def layer_component_sizes(layer: bytes, rows: int, transparent_tile: int = 71) -> list[int]:
    """Return the sizes of all orthogonally connected visible tile groups."""
    width = 14
    if len(layer) != rows * width:
        raise ValueError("Map layer dimensions do not match its payload")

    visible = {index for index, tile in enumerate(layer) if tile != transparent_tile}
    component_sizes: list[int] = []
    while visible:
        pending = [visible.pop()]
        size = 0
        while pending:
            index = pending.pop()
            size += 1
            row, column = divmod(index, width)
            neighbours = []
            if row:
                neighbours.append(index - width)
            if row + 1 < rows:
                neighbours.append(index + width)
            if column:
                neighbours.append(index - 1)
            if column + 1 < width:
                neighbours.append(index + 1)
            for neighbour in neighbours:
                if neighbour in visible:
                    visible.remove(neighbour)
                    pending.append(neighbour)
        component_sizes.append(size)
    return sorted(component_sizes)


def build_cold_echo_map(source_payload: bytes) -> bytes:
    """Reorder complete Episode 4 ice formations into a new frozen route."""
    if len(source_payload) != MAP_PAYLOAD_SIZE:
        raise ValueError("Cannot author a map from an invalid source payload")

    tile_lookup = source_payload[: 3 * 128 * 2]
    layer1_start = len(tile_lookup)
    layer2_start = layer1_start + 300 * 14
    layer3_start = layer2_start + 600 * 14
    layer1 = source_payload[layer1_start:layer2_start]
    source_layer2 = source_payload[layer2_start:layer3_start]
    layer3 = source_payload[layer3_start:]

    blank_row = bytes((71,)) * 14
    layer2_rows = [blank_row for _ in range(600)]
    source_rows = [source_layer2[row * 14 : (row + 1) * 14] for row in range(600)]

    # These bands contain every visible tile of each ice formation plus a
    # transparent margin.  Their new order creates a different route while
    # keeping the original artwork's multi-tile edges intact.
    ice_moves = (
        (297, 335, 558),
        (432, 485, 495),
        (234, 270, 450),
        (529, 570, 400),
        (351, 391, 350),
        (493, 524, 310),
        (206, 229, 275),
        (580, 597, 250),
        (412, 418, 230),
        (279, 285, 210),
    )
    for source_first, source_end, destination in ice_moves:
        height = source_end - source_first
        if destination + height > len(layer2_rows):
            raise ValueError("Cold Echo ice formation extends beyond the map")
        layer2_rows[destination : destination + height] = source_rows[source_first:source_end]

    layer2 = b"".join(layer2_rows)
    if layer2 == source_layer2:
        raise ValueError("Cold Echo map did not change the Episode 4 ice layout")
    if layer_component_sizes(layer2, 600) != layer_component_sizes(source_layer2, 600):
        raise ValueError("Cold Echo map cut, lost, or joined an ice formation")

    payload = tile_lookup + layer1 + layer2 + layer3
    if len(payload) != MAP_PAYLOAD_SIZE:
        raise ValueError(f"Authored map is {len(payload)} bytes, expected {MAP_PAYLOAD_SIZE}")
    return payload


MAP_LAYER_LAYOUT = (
    (14, 300, 72),
    (14, 600, 71),
    (15, 600, 70),
)
SHAPE_BYTES = 24 * 28


def read_shape_blank_flags(root: Path, shape_file: str) -> list[bool]:
    data = (root / "data" / f"shapes{shape_file.lower()}.dat").read_bytes()
    flags: list[bool] = []
    cursor = 0
    for _ in range(600):
        if cursor >= len(data):
            raise ValueError(f"Truncated shapes{shape_file.lower()}.dat")
        blank = data[cursor] != 0
        cursor += 1
        flags.append(blank)
        if not blank:
            cursor += SHAPE_BYTES
    return flags


def decode_map_shapes(payload: bytes, blank_shapes: list[bool]) -> tuple[list[list[int]], list[list[int | None]]]:
    """Translate a map's local tile bytes into shared shape-file indexes."""
    if len(payload) != MAP_PAYLOAD_SIZE:
        raise ValueError("Cannot decode an invalid map payload")

    lookups = [list(struct.unpack_from(">128H", payload, layer * 256)) for layer in range(3)]
    layers: list[list[int | None]] = []
    cursor = 3 * 128 * 2
    for layer_index, (width, rows, _) in enumerate(MAP_LAYER_LAYOUT):
        tile_data = payload[cursor : cursor + width * rows]
        cursor += width * rows
        shapes: list[int | None] = []
        for tile in tile_data:
            shape = lookups[layer_index][tile]
            if not 1 <= shape <= len(blank_shapes):
                raise ValueError(f"Map refers to invalid shape {shape}")
            transparent = (
                (layer_index == 1 and tile == 71)
                or (layer_index == 2 and tile >= 70)
                or (layer_index > 0 and blank_shapes[shape - 1])
            )
            shapes.append(None if transparent else shape)
        layers.append(shapes)
    return lookups, layers


def encode_map_shapes(layers: list[list[int | None]]) -> bytes:
    """Build new per-layer lookup tables for an authored multi-source map."""
    lookup_payload = bytearray()
    map_payload = bytearray()
    for layer_index, ((width, rows, capacity), layer) in enumerate(zip(MAP_LAYER_LAYOUT, layers)):
        if len(layer) != width * rows:
            raise ValueError(f"Composite layer {layer_index + 1} has invalid dimensions")

        shape_order: list[int] = []
        shape_to_tile: dict[int, int] = {}
        for shape in layer:
            if shape is not None and shape not in shape_to_tile:
                shape_to_tile[shape] = len(shape_order)
                shape_order.append(shape)
        if len(shape_order) > capacity:
            raise ValueError(
                f"Composite layer {layer_index + 1} needs {len(shape_order)} shapes; "
                f"the engine supports {capacity}"
            )

        lookup = [1] * 128
        for tile, shape in enumerate(shape_order):
            lookup[tile] = shape
        lookup_payload.extend(struct.pack(">128H", *lookup))

        transparent_tile = 71
        for shape in layer:
            map_payload.append(transparent_tile if shape is None else shape_to_tile[shape])

    payload = bytes(lookup_payload + map_payload)
    if len(payload) != MAP_PAYLOAD_SIZE:
        raise ValueError(f"Composite map is {len(payload)} bytes, expected {MAP_PAYLOAD_SIZE}")
    return payload


def build_composite_map(root: Path, config: dict[str, object], shape_file: str, load_level) -> bytes:
    """Compose a new map from JSON-directed bands, scatter, and intact scenes."""
    blank_shapes = read_shape_blank_flags(root, shape_file)
    source_cache: dict[tuple[int, int], tuple[list[list[int]], list[list[int | None]]]] = {}

    def source(spec: dict[str, object]) -> tuple[list[list[int]], list[list[int | None]]]:
        key = (int(spec["source_episode"]), int(spec["source_level"]))
        if key not in source_cache:
            header, _, payload = load_level(*key)
            if chr(header[1]).upper() != shape_file.upper():
                raise ValueError(
                    f"Composite source Episode {key[0]} level {key[1]} uses shapes{chr(header[1]).lower()}.dat, "
                    f"not shapes{shape_file.lower()}.dat"
                )
            source_cache[key] = decode_map_shapes(payload, blank_shapes)
        return source_cache[key]

    layers: list[list[int | None]] = [
        [None] * (width * rows) for width, rows, _ in MAP_LAYER_LAYOUT
    ]

    fill = config["base_fill"]
    fill_layer = int(fill.get("layer", 1)) - 1
    if fill_layer != 0:
        raise ValueError("The composite base fill must target layer 1")
    fill_lookups, _ = source(fill)
    fill_tile = int(fill["tile"])
    fill_shape = fill_lookups[fill_layer][fill_tile]
    layers[fill_layer] = [fill_shape] * len(layers[fill_layer])

    for scatter in config.get("scatter", []):
        layer_index = int(scatter["layer"]) - 1
        lookups, _ = source(scatter)
        shapes = [lookups[layer_index][int(tile)] for tile in scatter["tiles"]]
        count = int(scatter["count"])
        if count > len(layers[layer_index]):
            raise ValueError("Composite scatter count exceeds the layer size")
        rng = random.Random(int(scatter["seed"]))
        for index, destination in enumerate(rng.sample(range(len(layers[layer_index])), count)):
            layers[layer_index][destination] = shapes[index % len(shapes)]

    for band in config.get("bands", []):
        layer_index = int(band["layer"]) - 1
        _, source_layers = source(band)
        width, rows, _ = MAP_LAYER_LAYOUT[layer_index]
        source_first = int(band["source_first_row"])
        source_end = int(band["source_end_row"])
        destination = int(band["destination_row"])
        height = source_end - source_first
        if source_first < 0 or height <= 0 or source_end > rows or destination < 0 or destination + height > rows:
            raise ValueError(f"Invalid composite band {band.get('name', '')!r}")
        layers[layer_index][destination * width : (destination + height) * width] = source_layers[layer_index][
            source_first * width : source_end * width
        ]

    for transition in config.get("transitions", []):
        layer_index = int(transition["layer"]) - 1
        width, rows, _ = MAP_LAYER_LAYOUT[layer_index]
        boundary = int(transition["boundary_row"])
        offsets = [int(offset) for offset in transition["column_offsets"]]
        if len(offsets) != width or not 0 < boundary < rows:
            raise ValueError(f"Invalid composite transition {transition.get('name', '')!r}")

        before = transition["before"]
        after = transition["after"]
        _, before_layers = source(before)
        _, after_layers = source(after)
        before_delta = int(before["source_row_offset"])
        after_delta = int(after["source_row_offset"])

        for column, offset in enumerate(offsets):
            shifted_boundary = boundary + offset
            if not 0 <= shifted_boundary <= rows:
                raise ValueError(
                    f"Composite transition {transition.get('name', '')!r} leaves the map"
                )

            if shifted_boundary > boundary:
                destination_rows = range(boundary, shifted_boundary)
                source_layers = before_layers
                source_delta = before_delta
            else:
                destination_rows = range(shifted_boundary, boundary)
                source_layers = after_layers
                source_delta = after_delta

            for destination_row in destination_rows:
                source_row = destination_row + source_delta
                if not 0 <= source_row < rows:
                    raise ValueError(
                        f"Composite transition {transition.get('name', '')!r} "
                        f"requests source row {source_row}"
                    )
                layers[layer_index][destination_row * width + column] = source_layers[layer_index][
                    source_row * width + column
                ]

    for placement in config.get("placements", []):
        layer_index = int(placement["layer"]) - 1
        _, source_layers = source(placement)
        width, rows, _ = MAP_LAYER_LAYOUT[layer_index]
        source_x, source_y, rect_width, rect_height = map(int, placement["source_rect"])
        destination_x, destination_y = map(int, placement["destination"])
        if (
            source_x < 0
            or source_y < 0
            or destination_x < 0
            or destination_y < 0
            or rect_width <= 0
            or rect_height <= 0
            or source_x + rect_width > width
            or destination_x + rect_width > width
            or source_y + rect_height > rows
            or destination_y + rect_height > rows
        ):
            raise ValueError(f"Invalid composite placement {placement.get('name', '')!r}")
        copy_transparent = bool(placement.get("copy_transparent", False))
        for row in range(rect_height):
            for column in range(rect_width):
                source_value = source_layers[layer_index][(source_y + row) * width + source_x + column]
                if source_value is not None or copy_transparent:
                    layers[layer_index][(destination_y + row) * width + destination_x + column] = source_value

    # Some source bands contain scenery that depicts an enemy already destroyed.
    # Paint only the authored coordinates so the surrounding source artwork stays
    # intact and the corresponding live enemy event can occupy the platform.
    for paint in config.get("paint", []):
        layer_index = int(paint["layer"]) - 1
        if not 0 <= layer_index < len(MAP_LAYER_LAYOUT):
            raise ValueError(f"Invalid composite paint layer {layer_index + 1}")
        width, rows, _ = MAP_LAYER_LAYOUT[layer_index]
        shape = int(paint["shape"])
        if not 1 <= shape <= len(blank_shapes) or blank_shapes[shape - 1]:
            raise ValueError(f"Composite paint refers to invalid or blank shape {shape}")
        for position in paint["positions"]:
            x, y = map(int, position)
            if not 0 <= x < width or not 0 <= y < rows:
                raise ValueError(
                    f"Invalid composite paint position ({x}, {y}) in {paint.get('name', '')!r}"
                )
            layers[layer_index][y * width + x] = shape

    for check in config.get("forbidden_shapes", []):
        layer_index = int(check["layer"]) - 1
        if not 0 <= layer_index < len(MAP_LAYER_LAYOUT):
            raise ValueError(f"Invalid forbidden-shape layer {layer_index + 1}")
        width, rows, _ = MAP_LAYER_LAYOUT[layer_index]
        first_row = int(check.get("first_row", 0))
        end_row = int(check.get("end_row", rows))
        if not 0 <= first_row < end_row <= rows:
            raise ValueError(f"Invalid forbidden-shape row range {first_row}:{end_row}")
        forbidden = {int(shape) for shape in check["shapes"]}
        remaining = [
            (index % width, index // width, shape)
            for index, shape in enumerate(layers[layer_index])
            if first_row <= index // width < end_row and shape in forbidden
        ]
        if remaining:
            details = ", ".join(f"{shape}@({x},{y})" for x, y, shape in remaining[:8])
            raise ValueError(
                f"Composite background still contains forbidden scenery in "
                f"{check.get('name', 'checked region')!r}: {details}"
            )

    if any(shape is None for shape in layers[0]):
        raise ValueError("Composite layer 1 contains an unpainted tile")
    if len(source_cache) < 2:
        raise ValueError("A composite background must use at least two source maps")
    return encode_map_shapes(layers)


def build_level_archive(root: Path, config: dict[str, object]) -> tuple[bytes, list[int]]:
    archive_cache: dict[int, tuple[bytes, int, tuple[int, ...]]] = {}
    level_cache: dict[tuple[int, int], tuple[bytes, list[tuple[int, ...]], bytes]] = {}

    def load_archive(episode: int) -> tuple[bytes, int, tuple[int, ...]]:
        if episode not in archive_cache:
            path = root / "data" / f"tyrian{episode}.lvl"
            data = path.read_bytes()
            record_count, offsets = read_archive_offsets(data)
            archive_cache[episode] = (data, record_count, offsets)
        return archive_cache[episode]

    def load_level(episode: int, level: int) -> tuple[bytes, list[tuple[int, ...]], bytes]:
        key = (episode, level)
        if key not in level_cache:
            source, record_count, offsets = load_archive(episode)
            header_index = (level - 1) * 2
            if header_index + 2 >= record_count:
                raise ValueError(f"Level {level} is not present in tyrian{episode}.lvl")
            level_start = offsets[header_index]
            map_start = offsets[header_index + 1]
            next_level_start = offsets[header_index + 2]
            header_prefix, events = parse_level_header(source, level_start, map_start)
            map_payload = source[map_start:next_level_start]
            if len(map_payload) != MAP_PAYLOAD_SIZE:
                raise ValueError(
                    f"Episode {episode} level {level} has {len(map_payload)} map bytes, "
                    f"expected {MAP_PAYLOAD_SIZE}"
                )
            level_cache[key] = (header_prefix, events, map_payload)
        return level_cache[key]

    base_episode = int(config["base_episode"])
    item_source, _, item_offsets = load_archive(base_episode)
    item_payload = bytearray(item_source[item_offsets[-1]:])
    if len(item_payload) < ITEM_DATA_MIN_SIZE:
        raise ValueError(f"Episode {base_episode} item/enemy data is smaller than expected")
    _, weapon_port_count, power_count, ship_count, option_count, shield_count, _ = struct.unpack_from(
        "<7H", item_payload
    )
    shop_item_limits = {
        "ship": ship_count,
        "front_weapon": weapon_port_count,
        "rear_weapon": weapon_port_count,
        "power": power_count,
        "engine": 6,
        "left_option": option_count,
        "right_option": option_count,
        "armor": 4,
        "shield": shield_count,
    }
    for shop in config["shops"]:
        for field, maximum in shop_item_limits.items():
            invalid_ids = [
                int(item_id)
                for item_id in shop["inventory"][field]
                if not 0 <= int(item_id) <= maximum
            ]
            if invalid_ids:
                raise ValueError(
                    f"Shop {shop.get('name')!r} field {field!r} has IDs outside "
                    f"Episode {base_episode}'s 0..{maximum} range: {invalid_ids}"
                )

    records: list[bytes] = []
    event_counts: list[int] = []
    required_enemy_records: dict[int, tuple[bytes, int]] = {}
    for mission in config["missions"]:
        source_episode = int(mission.get("source_episode", base_episode))
        source_level = int(mission.get("source_level", config["base_level"]))
        map_source_episode = int(mission.get("map_source_episode", source_episode))
        map_source_level = int(mission.get("map_source_level", source_level))
        event_header, source_events, _ = load_level(source_episode, source_level)
        map_header, _, map_payload = load_level(map_source_episode, map_source_level)

        events, enemy_event_sources = build_events(
            mission,
            source_events,
            source_episode,
            source_level,
            lambda episode, level: load_level(episode, level)[1],
        )
        unsupported_events = sorted(
            {event[1] for event in events if event[1] in UNSUPPORTED_RUNTIME_EVENT_TYPES}
        )
        if unsupported_events:
            raise ValueError(
                f"Mission {mission['mission_title']!r} uses event types not implemented "
                f"by this OpenTyrian build: {unsupported_events}"
            )
        invalid_fixed_spawns = [
            event
            for event in events
            if event[1] == 58
            and (
                not 0 <= event[3] <= 264
                or not 0 <= 128 + event[5] <= 190
                or not 0 <= event[6] <= 3
            )
        ]
        if invalid_fixed_spawns:
            raise ValueError(
                f"Mission {mission['mission_title']!r} has invalid fixed-screen enemy spawns"
            )
        invalid_shape_banks = sorted(
            {
                bank
                for event in events
                if event[1] == 5
                for bank in (event[2], event[3], event[4], event[7])
                if not 0 <= bank <= MAX_ENEMY_SHAPE_BANK
            }
        )
        if invalid_shape_banks:
            raise ValueError(
                f"Mission {mission['mission_title']!r} requests enemy shape banks "
                f"outside 0..{MAX_ENEMY_SHAPE_BANK}: {invalid_shape_banks}"
            )
        if len(events) > 2500:
            raise ValueError(f"Mission {mission['mission_title']!r} exceeds the engine's event limit")
        boss_gate = mission.get("boss_gate")
        if boss_gate is not None:
            freeze_time = int(boss_gate["freeze_time"])
            jump_target = int(boss_gate["jump_target"])
            jump_events = [event for event in events if event[1] == 57]
            if not jump_events or any(event[2] != jump_target for event in jump_events):
                raise ValueError(
                    f"Mission {mission['mission_title']!r} boss destruction jump is not gated to {jump_target}"
                )
            if any(event[1] == 36 for event in events):
                raise ValueError(
                    f"Mission {mission['mission_title']!r} has a non-boss ready-to-end trigger"
                )
            if any(event[1] == 11 and event[0] < jump_target for event in events):
                raise ValueError(
                    f"Mission {mission['mission_title']!r} can end before its boss destruction target"
                )
            if (freeze_time, 2, 0, 0, 0, 0, 0, 0) not in events:
                raise ValueError(
                    f"Mission {mission['mission_title']!r} does not freeze while waiting for its boss"
                )
            if (jump_target, 11, 1, 0, 0, 0, 0, 0) not in events:
                raise ValueError(
                    f"Mission {mission['mission_title']!r} has no boss-gated completion event"
                )
            boss_link = boss_gate.get("boss_link")
            if boss_link is not None:
                boss_link = int(boss_link)
                linked_spawns = [
                    event
                    for event in events
                    if event[1] in ENEMY_SPAWN_EVENT_TYPES
                    and event[7] == boss_link
                    and event[0] <= freeze_time
                ]
                minimum_spawns = int(boss_gate.get("minimum_linked_spawns", 1))
                if len(linked_spawns) < minimum_spawns:
                    raise ValueError(
                        f"Mission {mission['mission_title']!r} has only {len(linked_spawns)} "
                        f"visible link-{boss_link} boss spawns; expected at least {minimum_spawns}"
                    )
                first_spawn = min(event[0] for event in linked_spawns)
                if boss_gate.get("require_damage_override") and not any(
                    event[1] == 25
                    and event[7] == boss_link
                    and 0 < event[2] < 255
                    and first_spawn <= event[0] <= freeze_time
                    for event in events
                ):
                    raise ValueError(
                        f"Mission {mission['mission_title']!r} never makes its "
                        f"link-{boss_link} boss destructible"
                    )
                if boss_gate.get("stationary"):
                    movement_types = {19, 20, 27, 55}
                    unsafe_movement = [
                        event
                        for event in events
                        if event[1] in movement_types
                        and event[7] == boss_link
                        and first_spawn <= event[0] <= freeze_time
                        and not (
                            event[1] in {19, 20, 55}
                            and event[2] == 0
                            and event[3] == 0
                        )
                    ]
                    if unsafe_movement:
                        raise ValueError(
                            f"Mission {mission['mission_title']!r} can move its stationary "
                            f"link-{boss_link} boss off screen"
                        )
                if boss_gate.get("require_motion_neutralization"):
                    last_spawn = max(event[0] for event in linked_spawns)
                    neutralized = {
                        event[1]
                        for event in events
                        if event[1] in {19, 20, 55}
                        and event[2] == 0
                        and event[3] == 0
                        and event[7] == boss_link
                        and last_spawn <= event[0] <= freeze_time
                    }
                    missing = {19, 20, 55} - neutralized
                    if missing:
                        raise ValueError(
                            f"Mission {mission['mission_title']!r} does not neutralize "
                            f"link-{boss_link} boss motion types {sorted(missing)}"
                        )

        for enemy_source_episode, sourced_events in enemy_event_sources.items():
            if enemy_source_episode <= 3:
                enemy_source = (root / "data" / "tyrian.hdt").read_bytes()
                enemy_table_start = EARLY_ENEMY_TABLE_OFFSET
            else:
                enemy_source, _, enemy_offsets = load_archive(enemy_source_episode)
                enemy_table_start = enemy_offsets[-1] + LATE_ENEMY_TABLE_OFFSET
            for enemy_id, record in collect_enemy_records(
                sourced_events, enemy_source, enemy_table_start
            ).items():
                previous = required_enemy_records.get(enemy_id)
                if previous is not None and previous[0] != record:
                    raise ValueError(
                        f"Enemy ID {enemy_id} has conflicting definitions in Episodes "
                        f"{previous[1]} and {enemy_source_episode}"
                    )
                required_enemy_records[enemy_id] = (record, enemy_source_episode)
        # Map and shape-file fields come from the visual source.  The enemy
        # frequency list comes from the event source so both halves remain
        # valid when a mission combines assets from two original levels.
        header_prefix = map_header[:8] + event_header[8:]
        level_header = header_prefix + struct.pack("<H", len(events))
        level_header += b"".join(EVENT_STRUCT.pack(*event) for event in events)
        map_style = mission.get("map_style", "source")
        if map_style == "source":
            mission_map = map_payload
        elif map_style == "shard_run_remix":
            mission_map = build_shard_run_map(map_payload)
        elif map_style == "cold_echo_remix":
            mission_map = build_cold_echo_map(map_payload)
        elif map_style == "composite":
            mission_map = build_composite_map(
                root,
                mission["background"],
                chr(map_header[1]),
                load_level,
            )
        else:
            raise ValueError(f"Unknown map style {map_style!r}")

        support_check = mission.get("ground_support_check")
        if support_check is not None:
            blank_shapes = read_shape_blank_flags(root, chr(map_header[1]))
            _, authored_layers = decode_map_shapes(mission_map, blank_shapes)
            first_time = int(support_check["first_time"])
            end_time = int(support_check["end_time"])
            event_types = {int(event_type) for event_type in support_check["event_types"]}
            void_shapes = {int(shape) for shape in support_check["void_shapes"]}
            row_origin = int(support_check.get("row_origin", 290))
            checked: list[tuple[int, int, int, int]] = []
            for event in events:
                if not first_time <= event[0] < end_time or event[1] not in event_types:
                    continue
                if event[3] == -99:
                    raise ValueError(
                        f"Ground-support check {support_check['name']!r} cannot validate "
                        "a randomly positioned enemy"
                    )
                if (event[3] + 6) % 24 != 0 or event[5] % 28 != 0:
                    raise ValueError(
                        f"Ground-support check {support_check['name']!r} found an enemy "
                        f"that is not aligned to the 24x28 map grid"
                    )
                column = (event[3] + 6) // 24
                if not 1 <= column <= 12:
                    continue  # fully outside the 12 visible layer-1 columns
                row = row_origin - event[0] // 28 + event[5] // 28
                if not 0 <= row < MAP_LAYER_LAYOUT[0][1]:
                    raise ValueError(
                        f"Ground-support check {support_check['name']!r} maps enemy "
                        f"{event[2]} outside the background"
                    )
                shape = authored_layers[0][row * MAP_LAYER_LAYOUT[0][0] + column]
                checked.append((event[2], column, row, shape))
            minimum_checked = int(support_check.get("minimum_checked", 1))
            if len(checked) < minimum_checked:
                raise ValueError(
                    f"Ground-support check {support_check['name']!r} examined only "
                    f"{len(checked)} enemies; expected at least {minimum_checked}"
                )
            unsupported = [entry for entry in checked if entry[3] in void_shapes]
            if unsupported:
                details = ", ".join(
                    f"enemy {enemy_id} at ({column},{row}) over shape {shape}"
                    for enemy_id, column, row, shape in unsupported[:8]
                )
                raise ValueError(
                    f"Ground-support check {support_check['name']!r} found void beneath "
                    f"a live defender: {details}"
                )
        records.extend((level_header, mission_map))
        event_counts.append(len(events))

    for enemy_id, (record, _) in required_enemy_records.items():
        start = LATE_ENEMY_TABLE_OFFSET + enemy_record_index(enemy_id) * ENEMY_RECORD_SIZE
        end = start + ENEMY_RECORD_SIZE
        if end > len(item_payload):
            raise ValueError(f"Episode {base_episode} item data cannot store enemy ID {enemy_id}")
        item_payload[start:end] = record

    records.append(bytes(item_payload))
    output_record_count = len(records)
    first_offset = 2 + output_record_count * ARCHIVE_OFFSET_STRUCT.size
    output_offsets: list[int] = []
    cursor = first_offset
    for record in records:
        output_offsets.append(cursor)
        cursor += len(record)

    archive = struct.pack("<H", output_record_count)
    archive += struct.pack(f"<{output_record_count}I", *output_offsets)
    archive += b"".join(records)
    return archive, event_counts


SHOP_FIELDS = (
    ("ship", " Ship   "),
    ("front_weapon", " WeapF  "),
    ("rear_weapon", " WeapR  "),
    ("power", " Power  "),
    ("engine", " Engine "),
    ("left_option", " Opt1   "),
    ("right_option", " Opt2   "),
    ("armor", " Armor  "),
    ("shield", " Shield "),
)

# The upgrade menu adds the player's equipped item when a shop does not list
# it.  Five authored entries leave room for that fallback and for the menu's
# final "Done" choice without overflowing its original fixed-size buffers.
SHOP_AUTHORED_ITEM_LIMIT = 5


def build_shop_inventory(shop: dict[str, object]) -> tuple[str, ...]:
    inventory = shop["inventory"]
    if not isinstance(inventory, dict):
        raise ValueError(f"Shop {shop.get('name')!r} inventory must be an object")

    expected_fields = {field for field, _ in SHOP_FIELDS}
    if set(inventory) != expected_fields:
        raise ValueError(
            f"Shop {shop.get('name')!r} must define exactly {sorted(expected_fields)}"
        )

    lines: list[str] = []
    for field, prefix in SHOP_FIELDS:
        item_ids = [int(item_id) for item_id in inventory[field]]
        if not item_ids:
            raise ValueError(f"Shop {shop.get('name')!r} field {field!r} is empty")
        if len(item_ids) > SHOP_AUTHORED_ITEM_LIMIT:
            raise ValueError(
                f"Shop {shop.get('name')!r} field {field!r} exceeds the safe "
                f"{SHOP_AUTHORED_ITEM_LIMIT}-item menu limit"
            )
        if len(set(item_ids)) != len(item_ids) or any(not 0 <= item_id <= 255 for item_id in item_ids):
            raise ValueError(f"Shop {shop.get('name')!r} field {field!r} has invalid item IDs")
        lines.append(prefix + " ".join(map(str, item_ids)))
    return tuple(lines)


def append_story_screen(strings: list[str], title: str, lines: list[str]) -> None:
    """Show story text on a clean black screen instead of the previous menu."""
    strings.extend(
        [
            "]C[",
            "]Wn 03[",
            title,
            *lines,
            "#",
        ]
    )


def append_shop_section(
    strings: list[str],
    section: int,
    destination: int,
    heading: str,
    inventory: tuple[str, ...],
    story_title: str | None = None,
    story_lines: list[str] | None = None,
) -> None:
    strings.append(f"**{section} SECTION - {heading} " + "*" * 44)
    if story_title is not None:
        append_story_screen(strings, story_title, story_lines or [])
    strings.extend(
        [
            "]?[ 01 001",
            "]![ 01",
            f"]G[ 04 1 04 {destination:03d}",
            "]I[",
            *inventory,
            "",
        ]
    )


def build_episode_script(config: dict[str, object]) -> tuple[bytes, list[str]]:
    strings: list[str] = []
    missions = config["missions"]
    shops = config["shops"]
    if len(shops) != len(missions):
        raise ValueError("Episode 6 needs one progressive shop tier before each mission")
    shop_inventories = [build_shop_inventory(shop) for shop in shops]

    prologue_lines = [str(line) for line in config["prologue"]]
    prologue_screen = [str(config["prologue_title"]), *prologue_lines]
    if len(prologue_screen) > 9 or any(len(line.encode("cp437")) > 60 for line in prologue_screen):
        raise ValueError("Episode prologue exceeds engine limits")
    append_shop_section(
        strings,
        1,
        2,
        "Before First Contact",
        shop_inventories[0],
        str(config["prologue_title"]),
        prologue_lines,
    )

    section = 2
    for mission_index, mission in enumerate(missions, start=1):
        next_section = section + 1
        if len(str(mission["mission_title"]).encode("cp437")) > 9:
            raise ValueError("HUD mission titles are limited to 9 bytes")
        warning_lines = [str(mission["briefing_title"]), *map(str, mission["briefing"])]
        if len(warning_lines) > 9 or any(len(line.encode("cp437")) > 60 for line in warning_lines):
            raise ValueError(f"Mission {mission['mission_title']!r} briefing exceeds engine limits")
        title = f"{mission['mission_title']:<9}"[:9]
        strings.extend(
            [
                f"**{section} SECTION - {mission['mission_title']} " + "*" * 48,
            ]
        )
        append_story_screen(
            strings,
            str(mission["briefing_title"]),
            [str(line) for line in mission["briefing"]],
        )
        strings.extend(
            [
                f"]L[ 9999 {next_section:03d} {title}{int(mission.get('song', 35)):02d} {mission_index:02d}",
                "",
            ]
        )
        section += 1

        if mission_index < len(missions):
            next_mission = missions[mission_index]
            append_shop_section(
                strings,
                section,
                section + 1,
                f"Resupply: {shops[mission_index]['name']} Before {next_mission['mission_title']}",
                shop_inventories[mission_index],
            )
            section += 1

    ending_section = section
    strings.extend(
        [
            f"**{ending_section} SECTION - Episode Complete " + "*" * 42,
        ]
    )
    append_story_screen(
        strings,
        str(config["ending_title"]),
        [str(line) for line in config["ending"]],
    )
    strings.append("]Q[")

    for _ in range(9):
        strings.extend(
            [
                str(config["ending_hint"]),
                "#",
            ]
        )
    return encode_pascal_strings(strings), strings


def build_cube_text() -> tuple[bytes, list[str]]:
    strings = [
        "*01 04",
        "UNIDENTIFIED TRANSMISSION",
        "PRIORITY: ?",
        "A narrow-band signal repeats from an abandoned asteroid corridor.",
        "",
        "Its timing does not match any known military beacon. Automated craft",
        "are converging on the source, as if something has called them home.",
        "",
        "Proceed carefully. The final signal contains only two words:",
        "~FIRST~ ~CONTACT~.",
        # OpenTyrian2000's datacube loader requires an explicit next-record
        # marker instead of treating end-of-file as an implicit terminator.
        "*",
    ]
    return encode_pascal_strings(strings), strings


def validate_outputs(archive: bytes, mission_count: int, script: bytes, script_strings: list[str], cube: bytes, cube_strings: list[str]) -> None:
    record_count, offsets = read_archive_offsets(archive)
    expected_record_count = mission_count * 2 + 1
    if record_count != expected_record_count or offsets[0] != 2 + expected_record_count * 4:
        raise ValueError("Episode 6 archive table is invalid")
    if not all(left < right for left, right in zip(offsets, offsets[1:])) or offsets[-1] >= len(archive):
        raise ValueError("Episode 6 archive offsets are invalid")
    for mission_index in range(mission_count):
        map_start = offsets[mission_index * 2 + 1]
        map_end = offsets[mission_index * 2 + 2]
        if map_end - map_start != MAP_PAYLOAD_SIZE:
            raise ValueError(f"Mission {mission_index + 1} map payload has the wrong size")
    if offsets[-1] + ITEM_DATA_MIN_SIZE > len(archive):
        raise ValueError("Episode 6 item data does not cover all known relative offsets")
    if decrypt_pascal_strings(script) != script_strings:
        raise ValueError("Episode script encryption did not round-trip")
    if sum(line.startswith("]L[") for line in script_strings) != mission_count:
        raise ValueError("Episode script does not launch every mission exactly once")
    if script_strings.count("]I[") != mission_count:
        raise ValueError("Episode script is missing an initial or between-mission shop")
    shop_markers = [index for index, line in enumerate(script_strings) if line == "]I["]
    previous_inventory: list[set[int]] | None = None
    for tier, marker in enumerate(shop_markers, start=1):
        inventory_lines = script_strings[marker + 1 : marker + 1 + len(SHOP_FIELDS)]
        if len(inventory_lines) != len(SHOP_FIELDS):
            raise ValueError(f"Shop tier {tier} has a truncated inventory")
        inventory = [set(map(int, line[8:].split())) for line in inventory_lines]
        if previous_inventory is not None and not any(
            current - previous for current, previous in zip(inventory, previous_inventory)
        ):
            raise ValueError(f"Shop tier {tier} does not unlock any new equipment")
        previous_inventory = inventory
    if not any(line.startswith("**3 SECTION - Resupply") for line in script_strings):
        raise ValueError("Episode script is missing the post-First-Contact menu")
    if decrypt_pascal_strings(cube) != cube_strings:
        raise ValueError("Datacube encryption did not round-trip")
    if len(cube_strings[1].encode("cp437")) > 80:
        raise ValueError("Datacube title exceeds the engine's 80-byte limit")
    if len(cube_strings[2].encode("cp437")) > 12:
        raise ValueError("Datacube header exceeds the engine's 12-byte limit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate generated bytes against files in data/ without rewriting them",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    config_path = Path(__file__).with_name("mission.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    archive, event_counts = build_level_archive(root, config)
    script, script_strings = build_episode_script(config)
    cube, cube_strings = build_cube_text()
    validate_outputs(archive, len(event_counts), script, script_strings, cube, cube_strings)

    outputs = {
        root / "data" / "tyrian6.lvl": archive,
        root / "data" / "levels6.dat": script,
        root / "data" / "cubetxt6.dat": cube,
    }

    if args.check:
        mismatches = [path for path, expected in outputs.items() if not path.exists() or path.read_bytes() != expected]
        if mismatches:
            for path in mismatches:
                print(f"out of date: {path.relative_to(root)}", file=sys.stderr)
            return 1
    else:
        for path, contents in outputs.items():
            path.write_bytes(contents)
            print(f"wrote {path.relative_to(root)} ({len(contents):,} bytes)")

    print(f"Episode 6 validation passed: {len(event_counts)} missions, {sum(event_counts)} events ({', '.join(map(str, event_counts))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

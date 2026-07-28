#!/usr/bin/env python3
"""Render honest gameplay-sized previews from the generated Episode 6 maps."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

import generate_episode6 as episode6


TILE_WIDTH = 24
TILE_HEIGHT = 28
VIEW_WIDTH = 264
VIEW_HEIGHT = 184
GAME_PALETTE = 0

RENDER_SETS = {
    7: {
        "title": "PALE EDEN",
        "slug": "pale-eden",
        "previews": (
            (350, None, "01-coral-aperture", "CORAL APERTURE"),
            (1250, None, "02-harvest-garden", "HARVEST GARDEN"),
            (2200, None, "03-asteroid-machine", "ASTEROID MACHINE"),
            (3150, None, "04-geode-engine", "GEODE ENGINE"),
            (4300, None, "05-deliani-vault", "DELIANI VAULT"),
        ),
        "transitions": (
            (700, None, "transition-01-coral-harvest", "CORAL / HARVEST FRACTURE"),
            (1932, None, "transition-02-harvest-astcity", "HARVEST / ASTCITY COLLAPSE"),
            (2520, None, "transition-03-astcity-geode", "ASTCITY / GEODE RUPTURE"),
            (3640, None, "transition-04-geode-deliani", "GEODE / DELIANI FAULT"),
        ),
    },
    8: {
        "title": "LAST WORD",
        "slug": "last-word",
        "previews": (
            (400, None, "01-sealed-cathedral", "SEALED CATHEDRAL"),
            (1600, 7, "02-command-foundry", "RED COMMAND FOUNDRY"),
            (2800, 7, "03-choir-machine-nave", "CHOIR MACHINE NAVE"),
            (3900, None, "04-black-iron-choir", "BLACK IRON CHOIR"),
            (4700, None, "05-throne-breach", "THRONE BREACH"),
            (5000, None, "06-first-voice", "FIRST VOICE"),
        ),
        "transitions": (
            (1200, 7, "transition-01-red-spectrum", "RED SPECTRUM BREACH"),
            (2400, 7, "transition-02-syntax", "SYNTAX ENGINE"),
            (3600, None, "transition-03-black-iron", "BLACK IRON DOOR"),
            (4480, None, "transition-04-throne", "THRONE FRACTURE"),
        ),
    },
}


def read_palette(root: Path) -> list[tuple[int, int, int]]:
    data = (root / "data" / "palette.dat").read_bytes()
    start = GAME_PALETTE * 256 * 3
    palette_data = data[start : start + 256 * 3]
    if len(palette_data) != 256 * 3:
        raise ValueError("palette.dat does not contain the gameplay palette")
    return [
        tuple(min(255, channel << 2) for channel in palette_data[offset : offset + 3])
        for offset in range(0, len(palette_data), 3)
    ]


def read_shapes(root: Path, shape_file: str) -> list[bytes | None]:
    data = (root / "data" / f"shapes{shape_file.lower()}.dat").read_bytes()
    shapes: list[bytes | None] = []
    cursor = 0
    for _ in range(600):
        if cursor >= len(data):
            raise ValueError(f"Truncated shapes{shape_file.lower()}.dat")
        blank = data[cursor] != 0
        cursor += 1
        if blank:
            shapes.append(None)
        else:
            end = cursor + episode6.SHAPE_BYTES
            if end > len(data):
                raise ValueError(f"Truncated shapes{shape_file.lower()}.dat")
            shapes.append(data[cursor:end])
            cursor = end
    return shapes


def colorize_shape(
    raw_shape: bytes,
    palette: list[tuple[int, int, int]],
    color_bank: int | None,
) -> Image.Image:
    image = Image.new("RGBA", (TILE_WIDTH, TILE_HEIGHT))
    pixels: list[tuple[int, int, int, int]] = []
    for value in raw_shape:
        mapped = value if color_bank is None else color_bank * 16 + (value & 0x0F)
        red, green, blue = palette[mapped]
        pixels.append((red, green, blue, 0 if value == 0 else 255))
    image.putdata(pixels)
    return image


def load_mission_map(
    root: Path,
    mission: int,
) -> tuple[str, list[list[int | None]]]:
    archive = (root / "data" / "tyrian6.lvl").read_bytes()
    record_count, offsets = episode6.read_archive_offsets(archive)
    map_index = (mission - 1) * 2 + 1
    if map_index + 1 >= record_count:
        raise ValueError(f"Episode 6 has no mission {mission}")
    level_start = offsets[map_index - 1]
    map_start = offsets[map_index]
    map_end = offsets[map_index + 1]
    header, _ = episode6.parse_level_header(archive, level_start, map_start)
    shape_file = chr(header[1])
    blank_shapes = episode6.read_shape_blank_flags(root, shape_file)
    _, layers = episode6.decode_map_shapes(archive[map_start:map_end], blank_shapes)
    return shape_file, layers


def layer_row(time: int, layer: int) -> int:
    # These are the same initial map rows and layer speeds used by Tyrian.
    origins = (290, 590, 590)
    speeds = (1, 2, 3)
    return origins[layer] - time * speeds[layer] // TILE_HEIGHT


def render_viewport(
    layers: list[list[int | None]],
    raw_shapes: list[bytes | None],
    palette: list[tuple[int, int, int]],
    time: int,
    color_bank: int | None,
) -> Image.Image:
    wide_width = 12 * TILE_WIDTH
    wide_height = 8 * TILE_HEIGHT
    image = Image.new("RGBA", (wide_width, wide_height), (0, 0, 0, 255))
    tile_cache: dict[tuple[int, int | None], Image.Image] = {}

    for layer_index, layer in enumerate(layers):
        map_width, map_rows, _ = episode6.MAP_LAYER_LAYOUT[layer_index]
        first_row = layer_row(time, layer_index)
        first_column = 1 if map_width == 14 else 2
        for screen_row in range(8):
            map_row = first_row + screen_row
            if not 0 <= map_row < map_rows:
                continue
            for screen_column in range(12):
                map_column = first_column + screen_column
                if not 0 <= map_column < map_width:
                    continue
                shape_number = layer[map_row * map_width + map_column]
                if shape_number is None:
                    continue
                raw_shape = raw_shapes[shape_number - 1]
                if raw_shape is None:
                    continue
                key = (shape_number, color_bank)
                tile = tile_cache.get(key)
                if tile is None:
                    tile = colorize_shape(raw_shape, palette, color_bank)
                    tile_cache[key] = tile
                position = (screen_column * TILE_WIDTH, screen_row * TILE_HEIGHT)
                if layer_index == 0:
                    image.paste(tile.convert("RGB"), position)
                else:
                    image.alpha_composite(tile, position)

    left = (wide_width - VIEW_WIDTH) // 2
    top = (wide_height - VIEW_HEIGHT) // 2
    return image.crop((left, top, left + VIEW_WIDTH, top + VIEW_HEIGHT)).convert("RGB")


def decorate(viewport: Image.Image, title: str, subtitle: str) -> Image.Image:
    scale = 2
    margin = 12
    heading = 42
    scaled = viewport.resize(
        (viewport.width * scale, viewport.height * scale),
        Image.Resampling.NEAREST,
    )
    image = Image.new(
        "RGB",
        (scaled.width + margin * 2, scaled.height + heading + margin),
        (8, 10, 16),
    )
    image.paste(scaled, (margin, heading))
    draw = ImageDraw.Draw(image)
    draw.text((margin, 8), title, fill=(225, 240, 255))
    draw.text((image.width - margin, 8), subtitle, fill=(112, 158, 188), anchor="ra")
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", type=int, default=8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("previews"),
    )
    args = parser.parse_args()
    render_set = RENDER_SETS.get(args.mission)
    if render_set is None:
        supported = ", ".join(map(str, sorted(RENDER_SETS)))
        parser.error(f"no authored preview set for mission {args.mission}; choose {supported}")

    root = Path(__file__).resolve().parents[2]
    output = args.output if args.output.is_absolute() else root / args.output
    output.mkdir(parents=True, exist_ok=True)

    shape_file, layers = load_mission_map(root, args.mission)
    raw_shapes = read_shapes(root, shape_file)
    palette = read_palette(root)
    rendered: list[Image.Image] = []

    for time, color_bank, filename, title in render_set["previews"]:
        viewport = render_viewport(layers, raw_shapes, palette, time, color_bank)
        preview = decorate(viewport, f"{render_set['title']} / {title}", f"EVENT {time}")
        path = output / f"{filename}.png"
        preview.save(path)
        rendered.append(preview)
        print(f"wrote {path.relative_to(root)}")

    gap = 12
    columns = 3
    rows = (len(rendered) + columns - 1) // columns
    contact_sheet = Image.new(
        "RGB",
        (
            rendered[0].width * columns + gap * (columns - 1),
            rendered[0].height * rows + gap * (rows - 1),
        ),
        (3, 4, 8),
    )
    for index, preview in enumerate(rendered):
        x = (index % columns) * (preview.width + gap)
        y = (index // columns) * (preview.height + gap)
        contact_sheet.paste(preview, (x, y))
    contact_path = output / f"{render_set['slug']}-contact-sheet.png"
    contact_sheet.save(contact_path)
    print(f"wrote {contact_path.relative_to(root)}")

    transition_renders: list[Image.Image] = []
    for time, color_bank, filename, title in render_set["transitions"]:
        viewport = render_viewport(layers, raw_shapes, palette, time, color_bank)
        preview = decorate(viewport, f"{render_set['title']} / {title}", f"EVENT {time}")
        path = output / f"{filename}.png"
        preview.save(path)
        transition_renders.append(preview)
        print(f"wrote {path.relative_to(root)}")

    transition_sheet = Image.new(
        "RGB",
        (
            transition_renders[0].width * 2 + gap,
            transition_renders[0].height * 2 + gap,
        ),
        (3, 4, 8),
    )
    for index, preview in enumerate(transition_renders):
        x = (index % 2) * (preview.width + gap)
        y = (index // 2) * (preview.height + gap)
        transition_sheet.paste(preview, (x, y))
    transition_path = output / f"{render_set['slug']}-transitions.png"
    transition_sheet.save(transition_path)
    print(f"wrote {transition_path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

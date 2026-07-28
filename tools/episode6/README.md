# Episode 6 mission authoring

This directory contains the editable source and generator for the custom
OpenTyrian episode in this project.

`mission.json` defines the episode story, mission order, enemy formations,
control events, music, and map style. `generate_episode6.py` writes the three
legacy data files expected by the engine:

- `data/tyrian6.lvl` — mission event stream, three-layer map, and item/enemy data
- `data/levels6.dat` — encrypted episode flow, shop, briefing, and ending
- `data/cubetxt6.dat` — encrypted story datacube

The episode currently contains:

1. `FIRST CNT` — the opening encounter with the unknown signal's defense grid.
2. `COLD ECHO` — an Episode 4-inspired ice-vault mission with a newly ordered
   background route, remixed attack sequence, and Cryo Warden encounter.
3. `FROSTGATE` — a fully authored multi-source background combining a procedural
   ice field, buried Camanis installations, intact crystal gates, and derelict
   fleet carriers across all three map layers.
4. `CINDERWAY` — the broken Frostgate throws the player into a completely
   different volcanic world. Its new route crosses an ash plain, magma canyons,
   a fossil core, living machinery, and the Receiver Heart chamber.
5. `NIGHTROOT` — the Receiver's last seed infects a jungle moon. A newly
   composed route moves from a night river canopy through overgrown botany
   machinery, hanging maws, rib caverns, and the living Rootmind nest.
6. `BLACK SUN` — the Rootmind's star-map leads beyond the rim. The route moves
   through colored debris, a shattered orbital, an asteroid foundry, and a red
   gravity scar before the stars vanish and the multi-part Null Core assembles
   inside an artificial sun.
7. `PALE EDEN` — the broken Black Sun opens into an artificial paradise. The
   unstable world glitches through a Coral aperture, Harvest machine garden,
   Asteroid City, a geode engine, and the Deliani SERAPH-0 vault.
8. `LAST WORD` — SERAPH-0 opens into a buried broadcast cathedral rather than
   another fleet. Black iron machinery turns red under the command spectrum,
   then fractures into the geometric throne of the First Voice.

The prologue, mission briefings, and ending each begin with a fade to a clean
black screen. This keeps story text readable instead of drawing it over the
shop menu left behind by the previous section.

The eight entries in `shops` define a progressive inventory tier before each
mission. They combine equipment from the original episodes, including Episode
5 ships and weapons. Each category has at most five authored choices because
the engine may append the player's equipped item as a sixth choice before its
final `Done` entry. Every later tier unlocks equipment that was absent from the
preceding shop.

`FROSTGATE` is boss-gated: its encounter clock and background stop after the
scripted battle sequence, and destroying the Gate Engine's linked core jumps to
the only completion event. The mission therefore cannot time out while the boss
still has health remaining.

`NIGHTROOT` combines maps from Episodes 2 and 4 that share `shapesx.dat`.
Its jungle, botany, and organic scenes are copied as intact full-width bands;
the resulting lookup tables use 71 of 72 layer-1 shapes, 38 of 71 layer-2
shapes, and 34 of 70 layer-3 shapes. The Rootmind uses the same destruction-gate
validation as Frostgate, including a frozen encounter clock with forced event
movement disabled until its linked core dies.

`BLACK SUN` combines compatible `shapesz.dat` scenery from all five original
episodes. Its main layer deliberately uses all 72 available shape slots, while
two sparse accretion layers add miner debris and gravitational streaks. The
orbital and foundry bands carry their own source-aligned, live ground-defense
tracks from Episodes 1 and 2; the generator rescales their event clocks to the
new row positions and switches enemy shape banks between combat phases. Baked
wreck and destroyed-turret scenery is repainted into intact platform flooring,
and a forbidden-shape check prevents those dead defenders from returning. The
foundry band covers the complete ground-defense event range, including solid
floor beneath the boundary node line and the final platforms in the gravity
scar, so destroying a defender never exposes an unrelated void tile. A
ground-support validation maps all 57 visible foundry spawns back to their
underlying tiles and rejects either known void shape. The
stars switch off inside the gravity scar, return distorted during the final
approach, and the encounter freezes after the last Dread-Not component spawns.
The ten-piece Null Core is anchored directly on screen rather than depending on
the original level's hours-long movement choreography; generation also checks
that every component exists, becomes destructible, and cannot accelerate out of
view. Only destruction of the link-254 Null Core can reach the ending.

`PALE EDEN` combines Episode 5 `CORAL`, Episode 4 `HARVEST` and `NOSE DRIP`,
Episode 2 `ASTCITY`, and Episode 1 `DELI`, all of which use `shapesz.dat`.
Five short, source-aligned bands replace the previous long Windy/Deliani
repetition. The main layer uses exactly 72 shapes, while aligned middle and
foreground bands use 25 and 69. Every scene keeps its original palette.
Ten staggered fracture masks reshape the four boundaries independently on the
main and parallax layers. Adjacent scenes interlock in waves, steps, hanging
columns, and faults instead of meeting on a full-width horizontal tile row.

Combat changes more frequently than the scenery: Coral fauna, Harvest patrols
with an Episode 3 New Deli glitch, Episode 2/3 AstCity machines, Nose Drip
geode defenders, a surprise Dread-Not incursion, and seeded Deliani sentries.
The generator produces deterministic pseudo-random times, positions, speeds,
and enemy choices for the glitch waves. Transition events clear the previous
family before switching graphic banks, so no unloaded enemy graphics survive
between biomes. Episode 5 source event types 58 and 59 remain filtered from the
Coral track: type 58 is reserved for this project's fixed-screen custom boss
spawns, while type 59 remains unimplemented. Shape tables 35 and 36 are enabled
by the `$` and `%` entries in `src/lvlmast.c`. The final SERAPH-0 uses twelve
interlocking Deliani components arranged as one wide mechanical guardian.
Every component receives destructible armor 170 and link 254, while the
guardian and its destruction drops use shape banks 24 and 16. Its event clock
freezes after the complete entity arrives, and only destroying that link can
reach Pale Eden's completion event.

`LAST WORD` deliberately avoids Episode 6's existing Savara, space, ice,
volcanic, jungle, and paradise imagery. Its `shapes).dat` composite begins in
the mostly unused UnderDeli cathedral: black brick, sealed windows, hanging
machines, and iron chambers. The command foundry and choir nave fade into a
violent red spectrum while Bubbles and Stargate enemy families attack inside
the architecture. The color drains away at the black iron choir, and the map
finally fractures into an unused purple geometric section of Brainiac for the
First Voice throne. Clear events isolate each graphics-bank handoff. The
global random background-explosion effect remains disabled throughout the
mission so it does not obscure these environments.

At the end, all ordinary combat is erased, the stars go dark, and 31 Episode 5
boss pieces assemble into the First Voice. Custom event type 58 gives every
piece an absolute screen coordinate, a reserved enemy slot, and zero intrinsic
motion, so horizontal map state cannot shift the body off-screen. Every piece
shares link 254, armor 220, and three active weapon circuits. The level clock
freezes after the entity arrives and waits indefinitely; destruction of any
damage-sharing link-254 component destroys the complete body and jumps to the
ending. The closing transmission deliberately mirrors the episode's opening
words: `FIRST CONTACT`.

Tyrian's map entries contain transparent edges and pieces of larger artwork;
placing them as independent square tiles produces holes and broken scenery.
The map builders therefore recompose their backgrounds safely:

- The proven base and foreground row structures remain intact.
- Complete parallax scenes are moved as rectangular bands, never cut apart.
- The mission traverses those scenes in a different order and spacing.
- `COLD ECHO` also verifies that every connected ice formation survives with
  exactly the same dimensions after rearrangement.

Regenerate the files from the repository root:

```sh
python3 tools/episode6/generate_episode6.py
```

Verify that committed/generated data matches the editable source:

```sh
python3 tools/episode6/generate_episode6.py --check
```

Render gameplay-sized previews directly from the generated map:

```sh
python3 tools/episode6/render_previews.py
```

Mission 8 is the default preview set; pass `--mission 7` to render Pale Eden.
Phase renders, transition close-ups, and contact sheets are written to
`tools/episode6/previews/`. These images use the generated binary map, Tyrian's
real shape pixels, aligned parallax layers, and each source scene's original
palette.

After building, start directly in Episode 6 with:

```sh
./opentyrian2000 --data=data --episode=6
```

Do not add `--constant`: it is the engine's autoplay mode. It intentionally
moves the ship down/right, holds the fire buttons, and skips menus. If a real
gamepad causes drift, use `--no-joystick` while testing keyboard controls.

New missions can select independent `source_episode`/`source_level` and
`map_source_episode`/`map_source_level` values. Available map styles are
`source`, `shard_run_remix`, `cold_echo_remix`, and `composite`. A composite
background describes its base tile, deterministic scatter, full-width terrain
bands, staggered cross-layer transitions, and intact rectangular artwork
placements directly in `mission.json`.
The generator translates each source map's local tile numbers into a new shared
lookup table, validates the engine's per-layer shape limits, and then writes the
new binary map. It follows every spawned enemy's launch chain and copies
matching enemy records from every source episode used by a mission's event
tracks. This is important because the same numeric enemy ID can have a different
definition in later episodes. Tracks may select their own source level, rescale
time, and filter source-only control events. Missions can also define individual
events, compact repeated `formations`, and seeded `random_waves`. The generator
validates archive offsets, map sizes, event ranges, briefing limits, encryption
round trips, datacube field sizes, enemy-record conflicts, and the integrity of
moved ice formations.

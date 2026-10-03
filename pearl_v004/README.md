# Pearl loop, light pass v4 (client notes of 2 Oct 2026)

Scene: `untitled_water_realism_v001.hiplc` (Houdini 21.0.700 Indie, Redshift, 540-frame loop at 30 fps).

Freek's notes and what this pass does about each:

| Note | What changes |
|---|---|
| Lights go 100 % to 0 %; make it 100 % to 15 % with a small ramp/envelope on the main lights | The whole-rig dark blink now drops to a 15 % floor (`Full Dark Depth` 0.85 plus a hard `Dark Floor` clamp on every path), and every dip ramps in over 1 frame and out over 2 frames. |
| Lights on the tree are good | Untouched: `/obj/rslight1` and the tree glow (`/obj/TREE_BASE_CTRL` Tree Glow tab, `/obj/geo1/tree_glow`). Dome 6 also lights the tree and keeps flickering as before, now floored at 15 %. |
| Flicker on the beat | Dips and dark blinks start on a beat grid. Default 150 BPM = 45 beats per loop = 12 frames per beat, dips on eighth notes. Set the real tempo on the controller once the track is known. |
| A version without the shell closing: open shell, tree looping, lights flickering | `Hold Shell Open` toggle on `/obj/PEARL_ANIM`, and two new ROPs that render the loop with it on. The tree cache ping-pongs through its fully grown frames so the tree keeps moving, and the roots are held grown with it. |

## Deliverables

- `out/untitled_water_realism_v002.hiplc`: the v001 scene with everything below already applied, built offline by `make_v002.py` and checked record by record. Open it in Houdini 21 and run through "First look in Houdini" below. (The `out/` folder is not committed; `make_v002.py` regenerates it.)
- `apply_v004.py`: the same change as a script you run inside Houdini on the v001 scene. Use it if you would rather apply the change to a newer version of the scene, or if the v002 file shows any load warning. It checks everything first, applies the change as one undo step, and saves a `_v002.hiplc` copy next to the loaded file. It refuses to run on a scene with unsaved changes and refuses to overwrite an existing file.
- `make_v002.py` and `hipio.py`: the offline builder and the .hiplc reader/writer it uses. `python3 make_v002.py v001.hiplc v002.hiplc` rebuilds the file and verifies it.
- `hou_session_v4.py`: the new light engine (installed as the scene's `hou.session` module by both paths).
- `tests/`: an offline harness that runs the engine against the controller data without Houdini. `python3 tests/test_engine.py --plot tests/levels_v4.svg` checks the floor, the ramps in and out, the beat alignment, the loop seam and that the old behaviour is reproduced exactly when the new features are off, and draws every light's level over the loop for both variants.

Both paths are driven by the same constants at the top of `apply_v004.py`, so the file and the script cannot drift apart.

## First look in Houdini

1. Open `untitled_water_realism_v002.hiplc`. The scene should load with no warnings about `/obj/PEARL_ANIM`, `/obj/geo1/timeshift2`, `/obj/TREE_BASE_CTRL` or the two new ROPs. If a warning appears, open the v001 file and run `apply_v004.py` instead (Windows > Python Shell: `exec(open(r"C:\path\to\apply_v004.py").read())`), and tell me what the warning said.
2. On `/obj/PEARL_ANIM` turn `Flicker On` on and scrub: the `Level:` fields never go below 15 % of the steady level, and dips sit on frames 1, 7, 13, 19, ... (every 6 frames at 150 BPM).
3. Turn `Hold Shell Open` on and scrub the whole loop: shell open, tree fully grown and moving on every frame, roots out, frame 540 flows into frame 1.
4. Render a few frames with `/out/Redshift_ROP_OPEN_LOOP_FAST` (half-res jpg, like `GLOW_FAST`). Its pre-frame script turns `Flicker On` and `Hold Shell Open` on for the render and the post-render script turns both off, so the saved scene state is unchanged.

## What the controller gets (`/obj/PEARL_ANIM`)

Light Flicker tab, after `Full Dark Step`:

| Parameter | Default | Meaning |
|---|---|---|
| Dark Floor | 0.15 | No main light goes below this share of its steady brightness. |
| Dip Ramp In (frames) | 1 | Frames a dip takes to reach full depth. |
| Dip Ramp Out (frames) | 2 | Frames a dip takes to come back. |
| Flicker On The Beat | on | Off gives the previous free-running flicker. `Speed` and the per-light `Step` parameters only act when this is off. |
| Track BPM | 0 | 0 means use `Beats per Loop` (Advanced folder, now 45). |
| Beat Offset (frames) | 0 | Shift the grid to line the first downbeat up with the audio. |
| Dips per Beat | 2 | 1 = quarter notes, 2 = eighths, 4 = sixteenths. |
| Dip Length (frames) | 2 | Frames a dip stays at its darkest, counted from the beat frame. |
| Off-beat Dip Chance | 0.5 | Dips between beats happen this fraction as often as dips on the beat. |
| Max Dips in a Row | 3 | A light never dips on more than this many consecutive grid slots. |

`Full Dark Depth` is set to 0.85 so the whole-rig blink lands exactly on the floor. A blink is 2 frames at the floor with the 1-frame ramp in and 2-frame ramp out around it, so 5 frames below full and 2 at the floor; in v001 a blink was 2 or 4 frames at black with no ramp. `Full Dark Step` 1 makes blinks shorter again. The water dome follows the whole-rig blink down to the floor like the other lights, as it did in v001; between blinks it keeps its own 0.75 floor.

The keyed story accents (slam flashes, landing dips, apex ripple, key hold) stay exactly where they were keyed and are protected: no blink lands on or next to them, and the key light keeps its hold windows. They are shell events, not beat events, so they were not moved onto the grid.

Timing tab, after `Glow Window`:

| Parameter | Default | Meaning |
|---|---|---|
| Hold Shell Open (loop variant) | off | The hold-open variant, see below. |
| Hold Open: Close Amount | 0 | Pose while held. 0 is the Open pose from the Shell tab, -0.069 the apex over-open of the story keys. |
| Hold Open: Shell Breath | 0 | A slow, loop-exact breath from the held pose toward the apex over-open and back, once per loop. 0 is perfectly still. |
| Hold Open: Keep Pearl Water Events | off | On keeps the keyed pearl rise and descent driving the water rings. Off holds the pearl out, so the water shows only its swell and the pearl bob ripple. |
| Hold Open: Tree Cache Frame | 124 | First fully grown frame of the tree cache; the ping-pong starts here. |

The keyed story channels (`Close Amount`, `Pearl Tuck`, `Pearl Out`, `Glow Window`, `Hits`, `Key Hold`, `Dip Group A/B`, `Apex Ripple`) keep their keys, unchanged, on new `... (story keys)` parameters right next to them (visible in the Animation Editor). The originals read those keys unless `Hold Shell Open` is on. The builder and the script both verify on every frame of the loop that the switched channels evaluate exactly as before.

## What the hold-open variant does, frame by frame

- Shell: open pose on every frame (the hinge in `/obj/oyster_shells/anim_delta` reads a constant Close Amount).
- Pearl: out, bobbing, swaying and spinning on its existing loop expressions. The pearl geometry itself is not rendered in v001 (its object display flag is off); these channels only move the water.
- Tree: the tree geometry is a baked cache whose growth is keyed to the shell (grows in over frames 1-124, out over 455-541). With the shell held open the cache would still grow and collapse, so `/obj/geo1/timeshift2` (present but bypassed in v001) is switched on with a frame expression that plays cache frames 124 to 394 and back once per loop. That is a seamless ping-pong: frame 1 and frame 541 read the same cache frame, and the wind motion reverses once at mid-loop and once at the seam. The glow pulses use real time and stay loop-exact; the glow fade-in/fade-out window (`glow_start` 60 / `glow_end` 470 on `TREE_BASE_CTRL`) is widened to the whole loop while held open and keeps its story values otherwise.
- Roots: `/obj/tree_roots` grows and retracts the roots with `TREE_BASE_CTRL/growth`, a link to the keyed tree growth. While held open that link reads 1, so the roots stay fully grown with the tree; the shell gate that pulls them back while closing never fires either.
- Water: the shell-driven wave is gone (nothing closes); the swell and the pearl bob ripple stay. If the water feels too still, raise `swell_h` on `/obj/WATER_CTRL` a little (0.003 to 0.005) or turn `Hold Open: Keep Pearl Water Events` on.
- Lights: the beat flicker runs on all 540 frames and wraps cleanly (frame 541 evaluates exactly like frame 1). The story accents are off because nothing slams.

Needs the tree caches on your machine, as every render does (`.../treee2/ver2.filecache1`, frames 1-600).

## The beat

The scene used 29 beats per loop, a leftover from the old 350-frame loop (the note on the parameter said 149 BPM). At 540 frames = 18 s that would be 96.7 BPM and would not line up with the frames.

Default now: 45 beats per loop = 150 BPM, 12 frames per beat, beat frames 1, 13, 25, ... 529. Dips sit on eighth notes (every 6 frames) with full probability on the beat and half probability off the beat, each light choosing its own beats from its own seed, with the same arbiter as before (never more than two lights dark, at most one dome dark when the key is dark).

To match the track:

1. Set `Track BPM` on the controller (or `Beats per Loop` in the Advanced folder).
2. Scrub to the first downbeat of the audio and set `Beat Offset` so a dip lands on it.
3. The loop is seamless when it holds a whole number of beats: at 18 s that is any multiple of 3.33 BPM, so 90, 100, 110, 120, 130, 140, 150, 160, 170 or 180. Other tempos drift by the fraction of a beat across the seam. If the track is 149 BPM, 150 is the nearest seamless grid (0.12 s drift over the full loop, under 4 frames). When a beat does not fall on a whole frame, the dip reaches full depth on the first frame at or after the beat, so at most one frame late.

## Rendering

- `/out/Redshift_ROP_OPEN_LOOP`: copy of `Redshift_ROP_18S_GLOW` (full quality), output `$HIP/render_open_loop/$HIPNAME.open_loop.$F4.exr`.
- `/out/Redshift_ROP_OPEN_LOOP_FAST`: copy of `Redshift_ROP_GLOW_FAST` (half-res jpg preview), output `$HIP/open_loop_fast/$HIPNAME.open_loop_fast.$F4.jpg`.

Both turn `Flicker On` and `Hold Shell Open` on in the pre-frame script and off in the post-render script, the same mechanism the existing flicker ROPs use for `Flicker On`. The tree glow needs `Flicker On` as before. Every existing ROP whose pre-frame script sets `Flicker On` now also turns `Hold Shell Open` off first, so a cancelled hold-open render (whose post-render script never ran) cannot leak into a story render.

Two things noticed on the way, not changed: `Redshift_ROP_FLICKER` and `Redshift_ROP_NOFLICKER` have `Unified Adaptive Error Threshold` 1 (minimum samples) although their comments say full quality, so the 18S family is the better template for finals; and `Redshift_ROP1` renders only frames 410-540 (a literal start frame).

## Numbers from the offline check

Multipliers of the steady light, from `tests/test_engine.py` on the controller data:

| | story loop | hold-open loop |
|---|---|---|
| lowest level of any main light | 0.15 | 0.15 |
| frames with a main light at the floor | 30 of 540 | 36 of 540 |
| frames below 60 % (key / dome6 / dome7 / grid) | 126 / 96 / 106 / 110 | 143 / 110 / 127 / 124 |
| frame 541 equals frame 1 | yes | yes |

Before this pass, 154 of the 540 frames had every light at exactly 0.

## Running the script again

`apply_v004.py` on the saved v002 (or on a scene it already converted) finds everything in place, changes nothing and does not save. Values you have tuned since (`Beats per Loop`, `Full Dark Depth`) are left alone: the script only migrates them while they still hold the v001 values.

## Reverting

`Hold Shell Open` off and `Flicker On The Beat` off reproduce the v001 flicker with the two things the client asked for still in place (`Full Dark Depth` 0.85 and the ramps). `Dark Floor` 0, `Dip Ramp In/Out` 0, `Full Dark Depth` 1 and `Beats per Loop` 29 give the v001 light levels exactly (checked frame by frame in the tests).

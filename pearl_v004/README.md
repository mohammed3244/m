# Pearl loop, light pass v4 (client notes of 2 Oct 2026)

Scene: `untitled_water_realism_v001.hiplc` (Houdini 21.0.700, Redshift, 540-frame loop at 30 fps).

Freek's notes and what this pass does about each:

| Note | What changes |
|---|---|
| Lights go 100 % to 0 %; make it 100 % to 15 % with a small ramp/envelope on the main lights | The full-dark blink now drops to a 15 % floor (`Full Dark Depth` 0.85, plus a hard `Dark Floor` clamp), and every dip ramps in over 1 frame and out over 2 frames. |
| Lights on the tree are good | Untouched: `/obj/rslight1` and the tree glow (`TREE_BASE_CTRL` Tree Glow tab, `/obj/geo1/tree_glow`). |
| Flicker on the beat | Dips and full-dark blinks start on a beat grid. Default 150 BPM = 45 beats per loop = 12 frames per beat, dips on eighth notes. Set the real tempo on the controller once the track is confirmed. |
| A version without the shell closing: open shell, tree looping, lights flickering | New `Hold Shell Open` toggle on `/obj/PEARL_ANIM` and a new ROP `/out/Redshift_ROP_OPEN_LOOP` that renders the full loop with it on. |

## Files

- `apply_v004.py`: run this once inside Houdini with the v001 scene open. It installs the new light engine, adds the parameters, moves the story keys, creates the ROP and saves `untitled_water_realism_v002.hiplc` next to the original. The original file is not modified.
- `hou_session_v4.py`: the light engine on its own (the same text is embedded in the apply script and installed as the scene's `hou.session` module).
- `tests/`: an offline harness that runs the engine against the controller data extracted from the v001 file, without Houdini. `python3 tests/test_engine.py --plot tests/levels_v4.svg` checks the floor, the ramps, the beat alignment and the loop seam, and draws every light's level over the loop for both variants.

## How to apply

1. Open `untitled_water_realism_v001.hiplc` in Houdini 21.
2. Windows > Python Shell, then:

```python
exec(open(r"C:\path\to\pearl_v004\apply_v004.py").read())
```

3. Read the `[pearl v4]` lines it prints. It stops with a clear message if anything is not as expected, and it does not save in that case.
4. It saves `untitled_water_realism_v002.hiplc`. Open that file for everything below.

Running it a second time on the v002 file is harmless: every step checks whether it has already been done.

## What the controller gets (`/obj/PEARL_ANIM`)

Light Flicker tab, after `Full Dark Step`:

| Parameter | Default | Meaning |
|---|---|---|
| Dark Floor | 0.15 | No main light goes below this share of its steady brightness. |
| Dip Ramp In (frames) | 1 | Frames a dip takes to reach full depth. |
| Dip Ramp Out (frames) | 2 | Frames a dip takes to come back. |
| Flicker On The Beat | on | Off gives the previous free-running flicker. |
| Track BPM | 0 | 0 means use `Beats per Loop` (Advanced folder, now 45). |
| Beat Offset (frames) | 0 | Shift the grid to line the first downbeat up with the audio. |
| Dips per Beat | 2 | 1 = quarter notes, 2 = eighths, 4 = sixteenths. |
| Dip Length (frames) | 2 | Frames a dip stays at its darkest, counted from the beat frame. |
| Off-beat Dip Chance | 0.5 | Dips between beats happen this fraction as often as dips on the beat. |
| Max Dips in a Row | 3 | A light never dips on more than this many consecutive grid slots. |

`Full Dark Depth` is set to 0.85 so the whole-rig blink lands exactly on the floor.

Timing tab, after `Glow Window`:

| Parameter | Default | Meaning |
|---|---|---|
| Hold Shell Open (loop variant) | off | Shell stays in the open pose, pearl stays out, glow window stays open, story accents off, beat flicker on every frame. |
| Hold Open: Close Amount | 0 | Close Amount used while held. 0 is the Open pose from the Shell tab; -0.069 is the apex over-open of the story keys. |

The keyed story channels (`Close Amount`, `Pearl Tuck`, `Pearl Out`, `Glow Window`, `Hits`, `Key Hold`, `Dip Group A/B`, `Apex Ripple`) keep their keys on new `... (story keys)` parameters next to them. The originals now read those keys unless `Hold Shell Open` is on. The script verifies on every frame of the loop that the switched channels evaluate exactly as before, and refuses to continue if they do not.

## The beat

The scene used 29 beats per loop, a leftover from the old 350-frame loop (the note on the parameter said 149 BPM). At 540 frames = 18 s that would be 96.7 BPM and would not line up with the frames.

Default now: 45 beats per loop = 150 BPM, 12 frames per beat, beat frames 1, 13, 25, ... 529. Dips sit on eighth notes (every 6 frames) with full probability on the beat and half probability off the beat, each light choosing its own beats from its own seed.

To match the track:

1. Set `Track BPM` on the controller (or `Beats per Loop` in the Advanced folder).
2. Scrub to the first downbeat of the audio and set `Beat Offset` so a dip lands on it.
3. For a seamless loop the loop has to hold a whole number of beats: at 18 s that is 90, 100, 120, 150 or 180 BPM exactly. Any other tempo drifts by the fraction of a beat across the seam. If the track is 149 BPM, 150 is the nearest seamless grid (0.12 s drift over the full loop, less than 4 frames).

## Rendering the hold-open variant

`/out/Redshift_ROP_OPEN_LOOP` is a copy of `Redshift_ROP_FLICKER` with frames 1-540, pre-render script turning on `Flicker On` and `Hold Shell Open`, post-render turning both off, and `OPEN_LOOP` in the output path. Any other ROP renders the hold-open variant too if `Hold Shell Open` is on and `Flicker On` is on (the tree glow needs `Flicker On` as before).

What the hold-open loop does, frame by frame:

- Shell: open pose on every frame (hinge from `anim_delta` reads a constant `Close Amount`).
- Pearl: out, bobbing, swaying and spinning on its existing loop expressions.
- Tree: its growth and glow pulses do not read the shell, so they loop exactly as before. Roots stay fully out (they only pull back while the shell closes).
- Water: the shell-driven wave is gone (nothing closes), the pearl bob and the looping swell stay.
- Lights: the beat flicker runs on all 540 frames and wraps cleanly (frame 541 evaluates exactly like frame 1).

## Numbers from the offline check

Multipliers of the steady light, from `tests/test_engine.py` on the v001 controller data:

| | story loop | hold-open loop |
|---|---|---|
| lowest level of any main light | 0.15 | 0.15 |
| frames with a main light at the floor | 32 of 540 | 36 of 540 |
| frames below 60 % (key / dome6 / dome7 / grid) | 128 / 99 / 109 / 112 | 143 / 110 / 127 / 124 |
| frame 541 equals frame 1 | yes | yes |

Before this pass, 154 of the 540 frames had every light at exactly 0.

## Reverting

`Hold Shell Open` off and `Flicker On The Beat` off reproduce the v001 behaviour, with the two differences the client asked for still in place (`Full Dark Depth` 0.85 and the ramps). Set `Dark Floor` 0, `Dip Ramp In/Out` 0 and `Full Dark Depth` 1 to get the v001 look exactly.

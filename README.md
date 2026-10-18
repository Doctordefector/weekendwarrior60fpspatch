# Weekend Warriors — 60fps patch

Makes MDickie's *Weekend Warriors* render at 60fps while the game still runs at
normal speed.

The game ties its logic to the frame rate (15 ticks per second), so if you just
raise the fps, everything runs 4x faster. This patch splits the two apart:
rendering runs at 60fps, game logic still runs 15 ticks per second, and movement,
easing and animation blending are interpolated in between.

No game files are included. You need your own copy of the game.

## What's here

| Path | What it is |
|---|---|
| `patches/game_v2.diff` | Unified diff of the decompiled scripts (`Game_fla/MainTimeline.as`, `flare/core/Pivot3D.as`), original → patched |
| `tools/smooth.py` | v2 transform (pose blending, easing, keyframe gating), applied to a v1 export |
| `tools/set_fps.py` | Sets the SWF header frame rate. Keeps FileLength valid, or AIR won't load the file |
| `NOTES.md` | Full work log: how the engine works, every change category, root causes, limitations |

## Building from source

Requirements: [JPEXS FFDEC](https://github.com/jindrapetrik/jpexs-decompiler) 26.2.x, Java, Python 3, `patch`, and `airglobal.swc` from the AIR SDK.

```sh
# 1. back up the original
cp Game.swf Game_original.swf

# 2. export scripts
java -jar ffdec.jar -export script src Game_original.swf

# 3. apply the patch
cd src/scripts && patch -p0 < /path/to/patches/game_v2.diff && cd ../..

# 4. recompile (the playerLibLocation override is required, FFDEC CLI ignores -air for type lookup)
mkdir -p imp/scripts/Game_fla imp/scripts/flare/core
cp src/scripts/Game_fla/MainTimeline.as imp/scripts/Game_fla/
cp src/scripts/flare/core/Pivot3D.as   imp/scripts/flare/core/
java -Xmx6g -jar ffdec.jar -config "playerLibLocation=/path/to/airglobal.swc" -air \
     -importScript Game_original.swf Game_patched.swf imp/scripts

# 5. header to 60fps, then install
python tools/set_fps.py Game_patched.swf Game.swf 60
```

Compiling takes about 10 minutes. The main timeline is roughly 138k lines.

To uninstall, copy `Game_original.swf` back over `Game.swf`.

## How it works (short)

- **Tick accumulator** at the top of all 27 screen handlers: `tickAcc += optFrameRate`.
  Each time it reaches 60, one logic tick runs. At Game Speed 100% that's one tick
  every 4th frame.
- **Movement** goes through `AdvanceX/Y/Z`, scaled per frame by `optFrameRate/60`.
- **Timers** advance by `tickRun`. One-shot keyframe events fire only on frames
  where a tick happened.
- **Easing** (`PursueAngle`, `SmoothTransition`) uses a per-frame fraction of
  `1 - (1 - 1/T)^(opt/60)`, which compounds to exactly the original 1/T per tick.
- **Animation blending** (Flare3D `Pivot3D`) runs on a shared tick clock. At every
  tick it gives exactly the pose the 15fps original would show, and between ticks
  it interpolates linearly.
- The **Game Speed** option still works and now only changes logic speed.

## Changelog

- **v2**: Fixed limb clipping and input lag. The pose blend now matches the
  original curve, instant poses snap again, limb overrides no longer restart
  their blend every frame, and easing is exponential-correct. 172 variable
  keyframe events that fired up to 4x per tick (doubled sounds and impacts) are
  now gated.
- **v1**: 60fps rendering at 1x game speed.

## Disclaimer

This is an unofficial fan patch, not affiliated with or endorsed by MDickie.
*Weekend Warriors* belongs to its owner. This repo has only patch data and
tooling.

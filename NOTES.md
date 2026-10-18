# Weekend Warriors Classic — 60fps @ 1x speed patch

Work log + findings. COMPLETE — patch shipped and verified in-game 2026-08-13.

## Game facts (verified via FFDEC decompile of Game.swf)

- Adobe AIR app, `renderMode=direct`, Stage3D via **Flare3D** (`flare.basic:Scene3D`).
- SWF header frame rate: **15.1 fps**. Runtime: `stage.frameRate` set from `optFrameRate`
  (5 sites: 2x `=15`, 2x `=optFrameRate` stage, 1x `scene.frameRate=optFrameRate`).
- Default `optFrameRate = 18` (reset-defaults block, line ~130966).
- Options menu item 4 is titled **"Game Speed"** = `optFrameRate`, range 15–60,
  displayed as `100 + (fps-15)*10` percent. MDickie intentionally treats fps = speed.
- Only ONE compensated timer in entire codebase: `promoTim > 100 * (optFrameRate / 15)`.
- Match clock: `matchClock += 1` per frame; `matchClock >= 15` → 1 match second.
  → engine time base = **15 frames per real second**. Everything is frame units.
- `* 15` / `/ 15` literals throughout (round breaks, travel steps, etc).
- All game logic in per-screen `Event.ENTER_FRAME` handlers (27 screens),
  gameplay = `GameScreen()` calling ManageMatch/PlayerCycle/ItemCycle/etc.
- `getTimer()` used only by loader — zero real-time in gameplay.

## Why naive patch fails (user-confirmed)

Header/code patch to 60fps → 4x game speed. No global timescale variable exists.
Every per-frame quantity (movement steps, timers, decays, ramps) hardcodes the
15-frames-per-second assumption.

## Architecture: decouple render rate from logic rate

Render always 60fps. Game logic still measured in **ticks** (1 tick = 1/15 s of game
time). Per rendered frame, a tick accumulator decides how many logic-ticks' worth of
work happens:

```actionscript
// inserted at top of all 27 screen handlers
this.tickAcc += this.optFrameRate;   // optFrameRate = game speed setting (15..60)
this.tickRun = 0;
while(this.tickAcc >= 60) { this.tickRun++; this.tickAcc -= 60; }
```

At 60fps + Game Speed 100% (optFrameRate=15): tickRun fires 1-in-4 frames
(0,0,0,1 pattern) → timers/counters advance at exactly 15Hz, movement applies
4 sub-steps of 1/4 size per tick → smooth 60Hz motion at 1x speed.
Game Speed option still works: opt=30 → tick every 2nd frame (2x), opt=60 → every
frame (4x, original speed-hack behavior), opt in-between interpolates.

### Transform categories

1. **Movement chokepoint** — ALL vector movement routes through
   `AdvanceX/AdvanceY/AdvanceZ(angle, distance)` (+ `Advance()` wrapper, 259 call sites).
   Bodies scaled: `distance * (optFrameRate / 60)`. One change covers everything
   routed through it (including MoveTravel — no double scale).
2. **Easing chokepoints** — `PursueAngle` / `SmoothTransition` divide by a
   `transition` param expressed in frames. Divisor scaled by `60 / optFrameRate`
   so eased turns/transitions take the same real time.
3. **Integer timers** — all `*tim`/`matchClock`/`pBlood`/`pHeat`/`entBored`
   mutations gated by `tickRun`: `--fooTim` → `fooTim -= tickRun`,
   `+= 1` → `+= tickRun`, `-= N` → `-= N * tickRun`. (~220 sites)
   Excluded: `charInjuryTime` (day counter), `pHeat -= 10/25/50` (one-shot crowd
   reactions, 20 sites — single-unit pHeat drift stays gated).
4. **One-shot keyframe events** — `if(animTim == N)` style triggers would fire on
   every render frame inside their window; wrapped as
   `(animTim == N && tickRun == 1)`. ~1760 sites (animTim 1742, gotim, promoTim,
   pTauntTim, pStretchTim, pAnimTim, + the pWalkTim footstep line).
   `== 0` checks left alone (hold-states, self-limiting).
5. **Direct per-frame motion** (bypasses Advance*) — scaled by `(optFrameRate / 60)`:
   gravity (`pGravity -= 0.5`, `pY += pGravity`, 3 sites; weapGravity pair),
   speeder/faller applications, platform carry deltas `(iX - iOldX)`, arena boundary
   nudges (10 sites), per-frame rotations `pA += N` inside `animTim >= a && <= b`
   windows (31 sites — all verified range-gated, hence per-frame).
6. **Per-frame decays/ramps** (would run 4x fast) — linearized with `tickRun`:
   - `pTravel -= pTravel / N` (59 sites) → `-= pTravel * tickRun / N`
   - `pTravel += accel` (14 sites) → `+= (accel) * tickRun`
   - `iTravel -= iTravel / 5` (victim knockback budget) → tickRun form
   - `pTransition += 5` accumulator (anim 52/53) → `* tickRun`
   - FlyingAnims: `pGravity += 1` (2x) scaled; `pGravity *= 0.9` (2x) →
     `*= 1 - 0.1*tickRun`; `pTravel *= 0.95` → `*= 1 - 0.05*tickRun`
   - `pRunUp` countdown, `pAccel += 0.1` ramp → tickRun form
7. **Engine blend** — `Pivot3D.blendValue += 1 / _blendFrames` (animation blending,
   fed by `gotoAndStop(frame, pTransition)`) → `1 / (_blendFrames * 4)` (2 sites).
   Fixed 4x: engine scene runs at hard 60fps regardless of Game Speed option —
   blending at >1x speed is slightly slow relative to game time (cosmetic only).
8. **promoTim threshold** — `> 100 * (optFrameRate/15)` simplifies to `> 100`
   (gated timer already counts ticks).
9. **Frame rate constants** — all 5 `stage/scene.frameRate` assignments → 60.

### Verified NOT needing scaling (checked, not assumed)

- `this.s`, `this.t` — recomputed per frame per anim state (derived stride/duration
  params in tick units), consistent with tick-gated animTim comparisons.
- `pTransition` resets+adjusts inside anim blocks — derived, except the one gated
  accumulator above. pTransition consumed as `transition` arg (scaled chokepoints)
  or `gotoAndStop` blendFrames (engine scaled).
- `pOffsetY/TY` — position offsets rebuilt/zeroed per frame in RenderPlayer, or
  chased via SmoothTransition (scaled).
- One-shot events: `pTravel /= 2`, `*= 1.5`, `weapTravel *= 0.5` (rebound),
  launch-time gravity setup (`pGravity = RndDec(3,5) + mods`) — state transitions,
  not per-frame.
- Crowd: no per-frame position increments (anim-frame based).
- `crowdTransition`, `pHangTime *= 1.5` — assignments, not accumulations.

## Build pipeline (all in /tmp, MSYS paths = C:\Users\chapl\AppData\Local\Temp)

- `ww_build/` — full FFDEC script export of Game.swf (412 .as files), edited.
  Backups: `MainTimeline.as.orig60`, `Pivot3D.as.orig60`.
- `ww_work/transform2.py` — main transform (steps 1-5, 7-9 above), asserts each site.
- `ww_work/transform3.py` — decay/ramp fixes (category 6).
- Recompile: `java -Xmx4g -jar /tmp/ffdec/ffdec.jar -air -importScript patch_in.swf patch_out.swf /tmp/ww_build`
  → exit 0, zero errors, 11417230 bytes.
- Roundtrip proven lossless pre-edit: unmodified reimport → only cosmetic diffs
  (for→while, explicit casts, import order).
- Post-compile verification: re-exported scripts from patched SWF — 1710 tickRun
  references, 74 `optFrameRate / 60` scales, 5x frameRate=60, Pivot3D blend x4,
  tick generators, animTim event wraps all present in bytecode.
- SWF header layout (this file): sig[0-2], version[3]=50, uncompressedLength[4-7],
  zlib data[8+]. Frame rate = 8.8 fixed-point LE right after RECT in decompressed
  stream. Patched 15.0 → 60.0 (script: ww_work/patch_header.py).
- Final file sha1: `4dcde0b844afbeb9d98415ca63d66c36966f8bc0` (11406126 bytes).
- Original backup sha1: `af1cac5784273501763bf6023127aa5d33d8b95a` (11561888 bytes).

### Launch-failure postmortem (first build didn't start — fixed)

First installed build failed to launch. Root cause: header patcher wrote the
**compressed** size into the FileLength field. SWF FileLength = total
**uncompressed** length (8 + len(decompressed payload)). AIR validates this and
rejects the file. FFDEC's own output was valid — corruption was introduced only
by the final header step. Fix: `FileLength = 8 + len(payload)`. Rebuilt +
reinstalled → game launches, confirmed working by user 2026-08-13.
Lesson recorded: any SWF header tooling must keep FileLength = uncompressed size.

## Status

- [x] Decompilation + analysis (FFDEC 26.2.1)
- [x] Chokepoints identified + timer census
- [x] Animation system understood (pAnimTim drives frames; animTim equality = events)
- [x] FFDEC reimport roundtrip proven semantically lossless
- [x] All transforms applied + edge-case sweep (pTravel/gravity/pRunUp/pAccel/iTravel)
- [x] Patched SWF compiled + bytecode verified + header 60fps
- [x] Installed: Game.swf patched, original backed up
- [x] Launch failure root-caused (FileLength header bug) + fixed
- [x] In-game verification — CONFIRMED WORKING by user, 2026-08-13

## Install / test

Already installed in this folder:
- `Game.swf` — patched 60fps build (was the target all along; AIR descriptor loads it)
- `Game_backup_15fps.swf` — original, untouched. Restore = copy back over Game.swf.
- `Game_v1_60fps.swf` — previous v1 build (before the v2 smoothness pass).

Test checklist:
1. Launch normally via Steam.
2. Menus/title animate at smooth 60fps, no speed change in music/UI.
3. Start a match: wrestlers move at NORMAL speed (the 4x bug is gone),
   match clock advances 1 second per real second, round timer/bell normal.
4. Options → Game Speed still works: 100% = normal, higher = faster logic
   (that setting is now decoupled from render fps).
5. Spot-check: grapples/strikes land, characters don't sink through ring,
   entrance animations complete, crowd reacts.

## v2 — smoothness / latency pass (2026-10-18)

Reported: odd limb clipping during animations + slight added latency.

### Root causes

1. **Pose blend curve was wrong.** Flare3D's stop-mode blend is a *cumulative*
   lerp: every update `transform = lerp(transform, key, b)`, b = k/N on the k-th
   update after `gotoAndStop(frame, N)`. v1 ran it 4x per tick with b/4, which is
   a different curve: for N=10 it chased keyframes ~2.3x faster than the original
   (23% per tick vs 10%), and on holds it converged 3-4x faster. Limbs reached
   extreme poses the original never showed (MDickie tuned contact distances against
   the smoothed poses) → clipping. Also produced a velocity spike each tick (15Hz pulse).
2. **N=1 no longer snapped.** Original b=1/1 snaps on the first update. v1 took 4
   frames. `pInstantFrame` (blend 1) snaps rotation by +180° at the same moment, so
   for ~3 frames the old pose was shown rotated → visible glitch, plus lag.
3. **Limb overrides restarted the blend every render frame** (`pLimbFrame` is set
   by per-frame code, and `gotoAndStop` is re-issued each frame). Original saw one
   restart per tick.
4. **Easing helpers scaled linearly.** `PursueAngle`/`SmoothTransition` are
   exponential (`x += (t-x)/T`); dividing by `T*4` is only right for large T.
   T=1 (instant) took ~4 frames → turning/offset lag. T=2..3 also laggier.
5. **172 variable keyframes ungated** (`animTim == this.s * k`): sounds, impacts,
   tag logic fired on every render frame of the tick (up to 4x).
6. `tickRun == 1` guards dropped events on frames that ran 2 ticks (hitches).

### Fixes (tools/smooth.py in the repo)

- Pivot3D: global tick clock `Pivot3D.tickTime = ticks + tickAcc/60`, fed by all
  27 tick generators. Blend reproduces the original per-tick samples *exactly*
  (same recurrence, b = k/N) and lerps linearly between them → smooth 60Hz and
  identical poses to the 15fps original at every tick. N≤1 snaps as originally.
  Same-frame re-requests within one tick are ignored (fixes 3).
- Easing: per-frame fraction `1 - (1 - 1/T)^(opt/60)` — compounds to exactly 1/T
  per tick; T=1 snaps again.
- Each `X == this.s…` equality term gated `&& tickRun > 0`; all `tickRun == 1` → `> 0`.

Trade-off: interpolating between tick samples shows each pose up to one tick
(≤66ms, ~33ms avg) after the 15fps original would have. Unavoidable without
predicting future keyframes; v1 had comparable delay, minus the snap cases.

Build: FFDEC 26.2.1 CLI ignores `-air` for type lookup (uses per-SWF GUI setting)
→ `File is not an existing type`. Fix: `-config playerLibLocation=<airglobal.swc>`.
Import into the v1 SWF keeps the 60fps header. Compile ~10 min.
Installed sha1 `e0ad0087ed4a3516104dd67a29a9e6945d932328`; v1 kept as `Game_v1_60fps.swf`.

## Known limitations / risks

- Per-frame random checks (`Rnd(...)`) without timer gates fire 4x more often.
  Most AI decisions sit behind scaled timer gates → acceptable drift.
- (fixed in v2) variable-RHS keyframes are now gated.
- (replaced in v2) engine blend now runs on the game tick clock, so it follows the Game Speed setting.
- If the stage actually renders below 60fps on weak hardware, tickRun>1 frames
  linearize decays — visually fine, motion steps coarser.
- Reverted by restoring `Game_backup_15fps.swf`.

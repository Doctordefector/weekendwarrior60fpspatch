"""Smoothness/latency pass on top of the 60fps patch (v2).

Run against a fresh FFDEC script export of the v1 patched Game.swf:
    python smooth.py <export>/scripts
"""
import re, sys
from pathlib import Path

root = Path(sys.argv[1])


def sub(text, old, new, count):
    n = text.count(old)
    assert n == count, f"expected {count} of {old[:60]!r}, found {n}"
    return text.replace(old, new)


# --- 1. Pivot3D: tick-exact pose blending ------------------------------------
# Original engine at 15Hz: each update does transform = lerp(transform, key, b),
# b = k/N on the k-th tick after gotoAndStop. v1 ran that 4x per tick with b/4,
# which is a different curve (2-3x snappier, pops each tick, N=1 no longer snaps).
# v2 reproduces the original per-tick samples exactly and lerps linearly between
# them on a shared tick clock fed by the game (Pivot3D.tickTime).
p = root / "flare/core/Pivot3D.as"
t = p.read_text(encoding="utf-8")

t = sub(t, "      private var _blendFrames:Number = 0;\n",
        "      private var _blendFrames:Number = 0;\n"
        "      public static var tickTime:Number = 0;\n"
        "      private var _blendStart:Number = 0;\n"
        "      private var _blendDone:int = 0;\n"
        "      private var _blendTarget:Object;\n", 1)

# gotoAndStop, instant branch: forget any pending blend target
t = sub(t, "            this.stop();\n            this.currentFrame = frame is String ? Number(this.labels[frame].from) : frame as Number;\n",
        "            this.stop();\n            this._blendTarget = null;\n            this.currentFrame = frame is String ? Number(this.labels[frame].from) : frame as Number;\n", 1)

# gotoAndStop, blend branch: re-requests of the same frame inside one tick are
# no-ops (limb overrides are re-issued every render frame; original saw 1/tick)
t = sub(t, "            if(!this.frames || !this.scene)\n            {\n               return;\n            }\n            if(this is Mesh3D && Mesh3D(this).modifier is SkinModifier)\n            {\n               SkinModifier(Mesh3D(this).modifier).setBlendingState(this as Mesh3D);\n            }\n            if(!this.lastBlendFrame)",
        "            if(!this.frames || !this.scene)\n            {\n               return;\n            }\n            if(frame == this._blendTarget && this._blendFrames > 0 && Math.floor(tickTime) == Math.floor(this._blendStart))\n            {\n               return;\n            }\n            if(this is Mesh3D && Mesh3D(this).modifier is SkinModifier)\n            {\n               SkinModifier(Mesh3D(this).modifier).setBlendingState(this as Mesh3D);\n            }\n            if(!this.lastBlendFrame)", 1)
t = sub(t, "            this._blendFrames = blendFrames;\n            this.currentFrame = frame is String",
        "            this._blendFrames = blendFrames;\n            this._blendStart = tickTime;\n            this._blendDone = 0;\n            this._blendTarget = frame;\n            this.currentFrame = frame is String", 1)

old_update = """         else if(this._blendFrames > 0)
         {
            this.blendValue += 1 / (this._blendFrames * 4);
            if(this.blendValue >= 1)
            {
               this._blendFrames = 0;
               this.blendValue = 1;
               this.stop();
            }
            if(Boolean(this.frames) && Boolean(this.frames.length))
            {
               Matrix3DUtils.interpolateTo(this.transform,this.frames[int(this._currentFrame)],this.blendValue);
               this.updateTransforms(true);
            }
         }
"""
new_update = """         else if(this._blendFrames > 0)
         {
            if(Boolean(this.frames) && Boolean(this.frames.length))
            {
               key = this.frames[int(this._currentFrame)];
               elapsed = this._blendFrames <= 1 ? 1 : tickTime - this._blendStart;
               while(this._blendDone < int(elapsed) && this.blendValue < 1)
               {
                  ++this._blendDone;
                  this.blendValue = Math.min(1,this._blendDone / this._blendFrames);
                  Matrix3DUtils.interpolateTo(this.lastBlendFrame,key,this.blendValue);
               }
               this.transform.copyFrom(this.lastBlendFrame);
               if(this.blendValue < 1)
               {
                  Matrix3DUtils.interpolateTo(this.transform,key,Math.min(1,(this._blendDone + 1) / this._blendFrames) * (elapsed - this._blendDone));
               }
               this.updateTransforms(true);
            }
            else
            {
               this.blendValue = 1;
            }
            if(this.blendValue >= 1)
            {
               this._blendFrames = 0;
               this.blendValue = 1;
               this.stop();
            }
         }
"""
t = sub(t, old_update, new_update, 1)
t = sub(t, "      public function update() : void\n      {\n",
        "      public function update() : void\n      {\n         var key:Matrix3D = null;\n         var elapsed:Number = NaN;\n", 1)
p.write_text(t, encoding="utf-8")

# --- 2. MainTimeline ------------------------------------------------------------
p = root / "Game_fla/MainTimeline.as"
t = p.read_text(encoding="utf-8")

# feed the tick clock from every screen's tick generator
gen = ("         while(this.tickAcc >= 60)\n         {\n            ++this.tickRun;\n"
       "            this.tickAcc -= 60;\n         }\n")
t = sub(t, gen, gen + "         Pivot3D.tickTime = Math.floor(Pivot3D.tickTime) + this.tickRun + this.tickAcc / 60;\n", 27)

# exponential easing: per-frame fraction that compounds to the original per-tick
# fraction (1/T). Linear divisor scaling made small T laggy (T=1 no longer snapped).
for name, diff in (("angleChange", "targetAngle - currentAngle"), ("valueChange", "targetValue - currentValue")):
    t = sub(t, f"var {name}:Number = ({diff}) / (transition * (60 / this.optFrameRate));",
            f"var {name}:Number = ({diff}) * (1 - Math.pow(1 - 1 / transition,this.optFrameRate / 60));", 1)

# keyframe events: fire whenever a tick happened this frame, not only single-tick frames
n = t.count("tickRun == 1")
t = t.replace("tickRun == 1", "tickRun > 0")
print("tickRun==1 -> >0:", n)

# variable-RHS keyframe events (animTim == this.s * k) were never gated: sounds,
# impacts, tags fired on every render frame of the tick (up to 4x)
# each equality term is gated on its own so mixed range tests (|| animTim >= ..) keep working
var = r"(?:this\.)?(?:animTim|gotim|promoTim|pTauntTim\[[^]]*\]|pStretchTim\[[^]]*\]|pAnimTim\[[^]]*\]|pWalkTim\[[^]]*\])"
term = re.compile(rf"({var} == this\.s(?: \* [\d.]+)?(?: [-+] [\d.]+)?)(?=\)| \|\| | && )")
lines, wrapped = t.split("\n"), 0
for i, line in enumerate(lines):
    if re.search(rf"{var} == this\.s\b", line) and "tickRun" not in line:
        lines[i], n = term.subn(r"(\1 && this.tickRun > 0)", line)
        assert not re.search(rf"[^(.]{var} == this\.s\b", lines[i]), line
        wrapped += 1
t = "\n".join(lines)
assert wrapped == 172, wrapped
print("variable keyframe lines gated:", wrapped)
p.write_text(t, encoding="utf-8")
print("ok")

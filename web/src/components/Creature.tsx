// The companion, drawn: three kinds, each an egg and then five grown stages.
// Everything is plain SVG shapes, so it scales to any size and needs no image files.
// A porthole is the round window it lives in, on the home page and on its own page.
import { useId, type ReactNode } from "react";

export type EggKind = "jelly" | "shell" | "kelp";
export interface CreatureLook {
  egg: EggKind;
  /** 0 = egg, 1–5 = grown stages. */
  stage: number;
  /** egg | awake | hungry | asleep */
  mood?: string;
  /** Solved problems so far while it is an egg: each one cracks the shell a little. */
  cracks?: number;
}

const INK = "#0b1626";
const SCALE = [0, 0.78, 0.86, 0.93, 1, 1.06];
const clampStage = (s: number) => Math.max(0, Math.min(5, Math.round(s) || 0));

/** Two eyes and a mouth. Asleep: closed. Hungry: a small round mouth. */
function Face({ x, y, gap, mood }: { x: number; y: number; gap: number; mood?: string }) {
  const eyes = [x - gap / 2, x + gap / 2];
  if (mood === "asleep") {
    return (
      <g fill="none" stroke={INK} strokeWidth="2.2" strokeLinecap="round">
        {eyes.map(ex => <path key={ex} d={`M${ex - 5} ${y} q5 4 10 0`} />)}
        <path d={`M${x - 3} ${y + 10} h6`} strokeWidth="1.8" />
      </g>
    );
  }
  return (
    <g>
      <g className="c-blink">
        {eyes.map(ex => (
          <g key={ex}>
            <ellipse cx={ex} cy={y} rx="5" ry="6.4" fill={INK} />
            <circle cx={ex - 1.6} cy={y - 2.2} r="1.9" fill="#fff" />
          </g>
        ))}
      </g>
      {mood === "hungry"
        ? <ellipse cx={x} cy={y + 11} rx="3" ry="3.8" fill={INK} />
        : <path d={`M${x - 5} ${y + 9} q5 5 10 0`} fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />}
    </g>
  );
}

/** Small letters that drift up from a sleeper. */
function Zzz() {
  return (
    <g className="c-zzz" aria-hidden="true" fill="rgba(238,243,248,.75)" fontWeight="700" fontFamily="var(--font)">
      <text x="134" y="62" fontSize="13">z</text>
      <text x="146" y="48" fontSize="17">z</text>
    </g>
  );
}

// ---- the egg -------------------------------------------------------------------
const EGG_PATH = "M100 50 C129 50 147 96 147 124 C147 152 126 168 100 168 C74 168 53 152 53 124 C53 96 71 50 100 50 Z";
const EGG_COLOURS: Record<EggKind, [string, string, string]> = {
  jelly: ["#e9fbfc", "#7fd4de", "#b8a3ff"],
  shell: ["#fff0d6", "#eaa94e", "#b9722a"],
  kelp: ["#dcf9ea", "#55c896", "#1f8f63"],
};

function EggArt({ egg, cracks = 0, id }: { egg: EggKind; cracks?: number; id: string }) {
  const [light, main, mark] = EGG_COLOURS[egg];
  return (
    <g className={`c-wobble${cracks >= 2 ? " soon" : ""}`}>
      <defs>
        <radialGradient id={`${id}-egg`} cx="38%" cy="30%" r="80%">
          <stop offset="0" stopColor={light} /><stop offset="1" stopColor={main} />
        </radialGradient>
        <clipPath id={`${id}-eggclip`}><path d={EGG_PATH} /></clipPath>
      </defs>
      <path d={EGG_PATH} fill={`url(#${id}-egg)`} />
      <g clipPath={`url(#${id}-eggclip)`} opacity=".55">
        {egg === "jelly" && [104, 126, 148].map((y, i) => (
          <path key={y} d={`M44 ${y} q14 -10 28 0 t28 0 t28 0 t28 0`} fill="none" stroke={mark} strokeWidth={5 - i} strokeLinecap="round" />
        ))}
        {egg === "shell" && [[78, 100, 5], [118, 92, 4], [96, 128, 6], [128, 132, 4.5], [72, 140, 4], [108, 152, 3.5], [92, 74, 3]].map(([x, y, r]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={r} fill={mark} />
        ))}
        {egg === "kelp" && [70, 100, 130].map(x => (
          <path key={x} d={`M${x} 172 q-12 -44 0 -88 q10 -22 0 -44`} fill="none" stroke={mark} strokeWidth="4" strokeLinecap="round" />
        ))}
      </g>
      <ellipse cx="82" cy="88" rx="9" ry="19" transform="rotate(-18 82 88)" fill="#fff" opacity=".35" />
      <path d={EGG_PATH} fill="none" stroke="rgba(255,255,255,.55)" strokeWidth="1.5" />
      <g fill="none" stroke={INK} strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" opacity=".7">
        {cracks >= 1 && <path d="M118 62 l-7 12 l9 7 l-8 12" />}
        {cracks >= 2 && <path d="M84 60 l6 13 l-10 8 l8 11 l-9 9" />}
      </g>
    </g>
  );
}

// ---- Awa, the glass drifter ------------------------------------------------------
const BELL = "M56 104 C56 66 76 46 100 46 C124 46 144 66 144 104 Q138 114 132 104 Q126 114 120 104 Q114 114 108 104 "
  + "Q102 114 96 104 Q90 114 84 104 Q78 114 72 104 Q66 114 60 104 Q57 108 56 104 Z";

function Jelly({ stage, mood, id }: { stage: number; mood?: string; id: string }) {
  const ribbons = [3, 4, 5, 6, 7][stage - 1];
  const curls = [1, 2, 2, 3, 3][stage - 1];
  const xs = Array.from({ length: ribbons }, (_, i) => 70 + (60 * i) / (ribbons - 1));
  const ribbon = (x: number) => `M${x} 104` + Array.from({ length: curls }, (_, k) => ` q${k % 2 ? 7 : -7} 9 0 18`).join("");
  return (
    <>
      <defs>
        <radialGradient id={`${id}-bell`} cx="50%" cy="22%" r="85%">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".85" /><stop offset=".55" stopColor="#a9e6ec" stopOpacity=".62" />
          <stop offset="1" stopColor="#58c7d4" stopOpacity=".55" />
        </radialGradient>
        <linearGradient id={`${id}-rib`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#a9e6ec" stopOpacity=".95" /><stop offset="1" stopColor="#b8a3ff" stopOpacity=".15" />
        </linearGradient>
      </defs>
      {stage >= 3 && [86, 114].map((x, i) => (
        <path key={x} className="c-sway" style={{ animationDelay: `${-1.3 * i}s` }}
          d={`M${x} 102 q${i ? 12 : -12} 16 0 30 q${i ? -10 : 10} 14 0 ${stage >= 4 ? 30 : 20}`}
          fill="none" stroke="#b8a3ff" strokeOpacity=".5" strokeWidth="9" strokeLinecap="round" />
      ))}
      {xs.map((x, i) => (
        <path key={x} className="c-sway" style={{ animationDelay: `${-0.6 * i}s` }} d={ribbon(x)}
          fill="none" stroke={`url(#${id}-rib)`} strokeWidth="4.5" strokeLinecap="round" />
      ))}
      {stage >= 5 && <ellipse cx="100" cy="42" rx="34" ry="7" fill="none" stroke="#f0d76a" strokeOpacity=".75" strokeWidth="2.5" />}
      <path className="c-pulse" d={BELL} fill={`url(#${id}-bell)`} stroke="#d9f6f9" strokeOpacity=".9" strokeWidth="1.6" />
      {stage >= 2 && <ellipse cx="100" cy="68" rx={stage >= 3 ? 20 : 14} ry="9" fill="#b8a3ff" opacity=".4" />}
      {stage >= 4 && [66, 83, 100, 117, 134].map(x => <circle key={x} cx={x} cy={98 - Math.abs(x - 100) * 0.08} r="2.3" fill="#fff" opacity=".85" />)}
      <ellipse cx="80" cy="64" rx="7" ry="12" transform="rotate(28 80 64)" fill="#fff" opacity=".4" />
      <Face x={100} y={84} gap={26} mood={mood} />
    </>
  );
}

// ---- Tsubo, the shell dweller ----------------------------------------------------
// A soft body under a turban shell: a cone of whorls that leans back to a point.
const CONE = "M70 120 C64 92 86 66 116 60 C132 55 146 46 160 34 C161 50 157 66 148 80 C156 106 140 130 110 134 C92 136 74 134 70 120 Z";

function Shell({ stage, mood, id }: { stage: number; mood?: string; id: string }) {
  return (
    <>
      <defs>
        <linearGradient id={`${id}-shell`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#d68f3c" /><stop offset=".55" stopColor="#f3b860" /><stop offset="1" stopColor="#ffe9c2" />
        </linearGradient>
        <linearGradient id={`${id}-body`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9ccff" /><stop offset="1" stopColor="#9b88ec" />
        </linearGradient>
        <clipPath id={`${id}-cone`}><path d={CONE} /></clipPath>
      </defs>
      {stage >= 4 && [[100, 62, -30], [128, 52, -8], [150, 62, 34]].map(([x, y, r]) => (
        <path key={x} d="M-5 3 L0 -13 L5 3 Z" transform={`translate(${x} ${y}) rotate(${r})`} fill="#f6c177" stroke="#b9722a" strokeWidth="1.2" strokeLinejoin="round" />
      ))}
      <path d={CONE} fill={`url(#${id}-shell)`} stroke="#b9722a" strokeOpacity=".6" strokeWidth="1.5" strokeLinejoin="round" />
      <g clipPath={`url(#${id}-cone)`} fill="none" stroke="#9c5f1f" strokeOpacity=".5" strokeWidth="3" strokeLinecap="round">
        <path d="M84 72 C104 86 116 108 114 138" /><path d="M110 58 C128 70 138 90 140 116" /><path d="M134 48 C144 56 150 66 152 80" />
      </g>
      {stage >= 2 && <path d="M74 118 q10 14 34 16" fill="none" stroke="#fff3da" strokeOpacity=".85" strokeWidth="4" strokeLinecap="round" />}
      {stage >= 3 && (
        <g fill="none" stroke="#ff9e8f" strokeWidth="3" strokeLinecap="round" className="c-sway up">
          <path d="M118 60 v-14 m0 7 l-6 -6 m6 2 l6 -6" />
          {stage >= 5 && <path d="M96 70 v-10 m0 5 l-5 -5" />}
        </g>
      )}
      {stage >= 5 && <circle cx="160" cy="33" r="5" fill="#f0d76a" />}
      <ellipse cx="98" cy="88" rx="7" ry="15" transform="rotate(38 98 88)" fill="#fff" opacity=".3" />
      <g fill="none" stroke="#9b88ec" strokeWidth="3" strokeLinecap="round">
        <path className="c-sway up" d="M66 116 q-8 -12 -15 -15" /><path className="c-sway up" style={{ animationDelay: "-1.4s" }} d="M84 112 q1 -13 8 -17" />
      </g>
      <circle cx="51" cy="101" r="3.2" fill="#d9ccff" /><circle cx="92" cy="95" r="3.2" fill="#d9ccff" />
      <path d="M52 142 C44 126 57 110 78 110 C97 110 109 121 110 135 C111 149 96 155 80 155 C66 155 57 151 52 142 Z" fill={`url(#${id}-body)`} />
      {stage >= 2 && <><ellipse cx="64" cy="156" rx="7" ry="3.5" fill="#9b88ec" /><ellipse cx="90" cy="157" rx="7" ry="3.5" fill="#9b88ec" /></>}
      <Face x={78} y={129} gap={22} mood={mood} />
    </>
  );
}

// ---- Mosu, the kelp sprite -------------------------------------------------------
// A small swimmer with a mane of kelp blades that streams behind it, and a leaf for a tail.
function Kelp({ stage, mood, id }: { stage: number; mood?: string; id: string }) {
  const count = [2, 3, 4, 5, 6][stage - 1];
  const length = [26, 34, 42, 50, 56][stage - 1];
  const blade = (len: number, w: number) => `M0 0 C${-w} ${-len / 3} ${-w} ${(-2 * len) / 3} 0 ${-len} C${w} ${(-2 * len) / 3} ${w} ${-len / 3} 0 0 Z`;
  // blades start along the back of the head and lean further back the further along they sit
  const blades = Array.from({ length: count }, (_, i) => {
    const t = count === 1 ? 0 : i / (count - 1);
    return { x: 80 + 44 * t, y: 80 + 9 * t * t, angle: 4 + 58 * t, len: length * (1 - 0.18 * Math.abs(t - 0.45)) };
  });
  return (
    <>
      <defs>
        <radialGradient id={`${id}-seed`} cx="34%" cy="30%" r="85%">
          <stop offset="0" stopColor="#c4f8dd" /><stop offset=".55" stopColor="#52d09a" /><stop offset="1" stopColor="#23976a" />
        </radialGradient>
        <linearGradient id={`${id}-leaf`} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#2aa877" /><stop offset="1" stopColor="#86ecbd" />
        </linearGradient>
      </defs>
      <path className="c-sway" style={{ transformOrigin: "0% 50%" }} d="M146 114 C158 98 172 96 182 100 C176 108 176 112 178 116 C176 122 178 128 182 132 C170 134 156 130 146 114 Z" fill={`url(#${id}-leaf)`} />
      {blades.map((bl, i) => (
        <g key={i} transform={`translate(${bl.x} ${bl.y}) rotate(${bl.angle})`}>
          <g className="c-sway up" style={{ animationDelay: `${-0.55 * i}s` }}>
            <path d={blade(bl.len, 7)} fill={`url(#${id}-leaf)`} />
            <path d={`M0 -3 V${-bl.len + 6}`} stroke="#d5fbe9" strokeOpacity=".7" strokeWidth="1.4" strokeLinecap="round" />
            {stage >= 4 && i === count - 2 && (
              <g transform={`translate(0 ${-bl.len})`}>
                {stage >= 5 && [0, 72, 144, 216, 288].map(r => <ellipse key={r} cx="0" cy="-6" rx="3.4" ry="6" transform={`rotate(${r})`} fill="#ffd9e2" />)}
                <circle r="4.6" fill="#f0d76a" />
              </g>
            )}
          </g>
        </g>
      ))}
      <path d="M50 114 C50 90 72 76 98 78 C124 80 142 96 150 114 C142 132 124 146 98 148 C72 150 50 138 50 114 Z" fill={`url(#${id}-seed)`} />
      <ellipse cx="92" cy="134" rx="26" ry="9" fill="#fff" opacity=".2" />
      {stage >= 2 && <path className="c-sway" d="M102 132 C112 138 116 148 112 158 C102 154 96 146 96 136 Z" fill="#2aa877" />}
      {stage >= 3 && [118, 128, 137].map((x, i) => <circle key={x} cx={x} cy={112 + i * 1.5} r={2.6 - i * 0.3} fill="#f0d76a" opacity=".9" />)}
      <ellipse cx="70" cy="96" rx="6" ry="12" transform="rotate(38 70 96)" fill="#fff" opacity=".35" />
      <Face x={80} y={110} gap={24} mood={mood} />
    </>
  );
}

/** The companion as SVG shapes, for use inside a 200×200 viewBox. */
export function CreatureArt({ egg, stage, mood, cracks }: CreatureLook) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const s = clampStage(stage);
  if (s === 0) return <EggArt egg={egg} cracks={cracks} id={id} />;
  const k = SCALE[s];
  const body: ReactNode = egg === "jelly" ? <Jelly stage={s} mood={mood} id={id} /> : egg === "shell" ? <Shell stage={s} mood={mood} id={id} /> : <Kelp stage={s} mood={mood} id={id} />;
  return (
    <g className={`c-bob${mood === "asleep" ? " slow" : ""}`}>
      <g transform={`translate(${100 - 100 * k} ${104 - 104 * k}) scale(${k})`}>{body}</g>
      {mood === "asleep" && <Zzz />}
    </g>
  );
}

/** A round window with water in it, and the companion inside. */
export function Porthole({ look, size = 120, label }: { look: CreatureLook; size?: number; label?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <svg className={`porthole creature ${look.mood || ""}`} width={size} height={size} viewBox="0 0 200 200" role="img" aria-label={label || "your companion"}>
      <defs>
        <clipPath id={`${id}-win`}><circle cx="100" cy="100" r="93" /></clipPath>
        <radialGradient id={`${id}-water`} cx="50%" cy="18%" r="95%">
          <stop offset="0" stopColor="#2f7fa8" /><stop offset=".55" stopColor="#173f6e" /><stop offset="1" stopColor="#0a1a36" />
        </radialGradient>
        <linearGradient id={`${id}-rim`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity=".85" /><stop offset=".5" stopColor="#a9e6ec" stopOpacity=".35" />
          <stop offset="1" stopColor="#58c7d4" stopOpacity=".7" />
        </linearGradient>
      </defs>
      <g clipPath={`url(#${id}-win)`}>
        <rect width="200" height="200" fill={`url(#${id}-water)`} />
        <path d="M70 0 L112 0 L84 200 L20 200 Z" fill="#fff" opacity=".045" /><path d="M128 0 L150 0 L150 200 L110 200 Z" fill="#fff" opacity=".035" />
        <path d="M0 176 Q50 160 100 172 T200 166 V200 H0 Z" fill="#0d2748" />
        {[[44, 0], [150, -2.6], [118, -4.8]].map(([x, delay]) => (
          <circle key={x} className="bubble" style={{ animationDelay: `${delay}s` }} cx={x} cy="182" r={x === 150 ? 3.2 : 2.3} fill="none" stroke="#cfeff3" strokeOpacity=".7" strokeWidth="1.2" />
        ))}
        <CreatureArt {...look} />
      </g>
      <circle cx="100" cy="100" r="94.5" fill="none" stroke={`url(#${id}-rim)`} strokeWidth="5" />
      <path d="M38 62 A72 72 0 0 1 92 28" fill="none" stroke="#fff" strokeOpacity=".35" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// The water: one fragment shader on a low-resolution canvas. Four soft colour
// bodies drift on slow sine paths under a faint caustic shimmer. Replaces the
// old CSS blur + SVG turbulence stack, which re-rasterised every frame on the
// CPU and stuttered — this is a single GPU pass, capped at 30 fps on touch
// devices, paused when the tab is hidden, and a still frame under reduced motion.
import { useEffect, useRef } from "react";

const VS = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";
const FS = `
precision mediump float;
uniform vec2 u_res; uniform float u_t;
float blob(vec2 p, vec2 c, float r){ float d = length(p - c) / r; return exp(-d * d * 1.7); }
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3. - 2. * f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), u.x), mix(hash(i + vec2(0., 1.)), hash(i + vec2(1., 1.)), u.x), u.y); }
void main(){
  vec2 uv = gl_FragCoord.xy / u_res;
  vec2 p = (gl_FragCoord.xy - .5 * u_res) / min(u_res.x, u_res.y);
  float t = u_t * .07;
  vec3 col = vec3(.024, .039, .078);
  col += vec3(.345, .780, .831) * .58 * blob(p, vec2(-.62 + .14 * sin(t * 1.1), .38 + .10 * cos(t * .9)), .58);
  col += vec3(.184, .357, .847) * .66 * blob(p, vec2(.66 + .16 * cos(t * .8), .12 + .12 * sin(t * 1.3)), .72);
  col += vec3(.427, .357, .816) * .48 * blob(p, vec2(-.12 + .18 * sin(t * .7), -.52 + .09 * cos(t * 1.2)), .56);
  col += vec3(.275, .784, .804) * .36 * blob(p, vec2(.38 + .10 * sin(t * 1.5), -.36 + .12 * cos(t * .6)), .42);
  col += vec3(.59, .90, .94) * .22 * blob(p, vec2(.05 + .22 * sin(t * .5), .05 + .16 * cos(t * .85)), .26);
  float n = noise(p * 3.2 + vec2(t * .9, -t * .5)) * .55 + noise(p * 6.5 - vec2(t * .6, t * .9)) * .3;
  col += vec3(.35, .75, .85) * smoothstep(.58, .92, n) * .09;
  col *= 1. - .9 * dot(uv - .5, uv - .5);
  gl_FragColor = vec4(col, 1.);
}`;

export function Water({ still = false }: { still?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current!;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, depth: false, powerPreference: "low-power" });
    if (!gl) { canvas.classList.add("nogl"); return; }
    const sh = (type: number, src: string) => { const s = gl.createShader(type)!; gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { canvas.classList.add("nogl"); return; }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const a = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(a);
    gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0);
    const uRes = gl.getUniformLocation(prog, "u_res");
    const uT = gl.getUniformLocation(prog, "u_t");

    const coarse = matchMedia("(pointer: coarse)").matches;
    const minFrame = coarse ? 1000 / 30 : 1000 / 60;
    const resize = () => {
      const scale = Math.min(window.devicePixelRatio || 1, 1) * 0.5;
      canvas.width = Math.max(2, Math.floor(window.innerWidth * scale));
      canvas.height = Math.max(2, Math.floor(window.innerHeight * scale));
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    resize();
    window.addEventListener("resize", resize);

    let raf = 0, last = 0;
    const t0 = performance.now();
    const draw = (now: number) => {
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uT, (now - t0) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (document.hidden || now - last < minFrame) return;
      last = now;
      draw(now);
    };
    if (still) draw(t0 + 4000); else raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [still]);
  return <canvas ref={ref} className="water" aria-hidden="true" />;
}

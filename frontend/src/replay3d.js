// ---- replay in 3D with three.js: the 8 seconds before and 3 after the moment, seen from the touchline. Players run,
// walk or stand by their speed and face where they go; the ball sits at the carrier's feet and rolls; on the decision
// the clip stops for 3 seconds and shows the four marked options, and the receiver's run when the ball goes ahead of him.
// Players are drawn with models/player.glb when that file is there (a rigged model facing +z with Idle, Walk and Run
// clips; a material named "Shirt" takes the team colour), otherwise as capsules ----
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";

const HOLD_S = 3, FADE_S = 0.5, RUN_MIN_GAIN = 3, FLIGHT_MS = 8, NEAR_M = 1.6, BALL_R = 0.11, BODY_M = 1.8;
const HOME = "#d32f2f", AWAY = "#1565c0", KEEPER = "#ffb300";   // keepers wear amber, their number keeps the team colour
const MARKS = [["is_chosen", "#ffeb3b", "Player's choice"], ["is_best", "#ff40ff", "Biggest chance (AI)"],
  ["is_safe_best", "#00e5ff", "Safest option (AI)"], ["is_decision1", "#76ff03", "Decision-1's choice"]];
const P = (x, y, h = 0) => new THREE.Vector3(x - 52.5, h, -(y - 34));   // pitch metres to the 3D scene
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const VIEWS = [["broadcast", "Broadcast"], ["tactical", "Tactical"], ["sideline", "Sideline"], ["player", "Player"]];
let stage = null, gltf, view = "broadcast";   // the camera chosen last stays for the next replay

async function model() {                 // loaded once; null when there is no player model
  if (gltf === undefined) gltf = await new GLTFLoader().loadAsync("models/player.glb").catch(() => null);
  return gltf;
}

function label(text, colour, size, back = "rgba(0,0,0,0.65)") {
  const c = document.createElement("canvas"); c.width = 256; c.height = 64; const g = c.getContext("2d");
  g.fillStyle = back; g.roundRect(0, 0, 256, 64, 14); g.fill();
  g.fillStyle = colour; g.font = "bold 40px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 128, 34);
  const map = new THREE.CanvasTexture(c); map.colorSpace = THREE.SRGBColorSpace;   // the colours as painted, not washed out
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map, depthTest: false, transparent: true }));
  s.scale.set(size * 4, size, 1); return s;
}

function pitch(scene) {
  for (let i = 0; i < 14; i += 1) {
    const g = new THREE.Mesh(new THREE.PlaneGeometry(7.5, 68), new THREE.MeshLambertMaterial({ color: i % 2 ? "#3b8f40" : "#368538" }));
    g.rotation.x = -Math.PI / 2; g.position.set(-52.5 + 3.75 + 7.5 * i, 0, 0); g.receiveShadow = true; scene.add(g);
  }
  const apron = new THREE.Mesh(new THREE.PlaneGeometry(125, 90), new THREE.MeshLambertMaterial({ color: "#2f7a35" }));
  apron.rotation.x = -Math.PI / 2; apron.position.y = -0.01; apron.receiveShadow = true; scene.add(apron);
  const white = new THREE.LineBasicMaterial({ color: "#ffffff" });
  const line = (pts) => scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts.map(([x, y]) => P(x, y, 0.02))), white));
  line([[0, 0], [105, 0], [105, 68], [0, 68], [0, 0]]); line([[52.5, 0], [52.5, 68]]);
  for (const s of [0, 1]) {
    const f = (x) => (s ? 105 - x : x);
    line([[f(0), 13.84], [f(16.5), 13.84], [f(16.5), 54.16], [f(0), 54.16]]); line([[f(0), 24.84], [f(5.5), 24.84], [f(5.5), 43.16], [f(0), 43.16]]);
    const goal = new THREE.Mesh(new THREE.BoxGeometry(0.15, 2.44, 7.32), new THREE.MeshBasicMaterial({ color: "#ffffff", wireframe: true }));
    goal.position.copy(P(s ? 106 : -1, 34, 1.22)); scene.add(goal);
  }
  const circle = []; for (let a = 0; a <= 64; a += 1) circle.push([52.5 + 9.15 * Math.cos(a / 32 * Math.PI), 34 + 9.15 * Math.sin(a / 32 * Math.PI)]);
  line(circle);
  scene.add(new THREE.HemisphereLight("#ffffff", "#335533", 1.6));
  const sun = new THREE.DirectionalLight("#ffffff", 2.2); sun.position.set(-30, 60, 40); sun.castShadow = true;
  Object.assign(sun.shadow.camera, { left: -70, right: 70, top: 50, bottom: -50 }); sun.shadow.mapSize.set(2048, 2048); scene.add(sun);
}

function player(gl, colour, shirt, carrier, keeper) {
  const kit = keeper ? KEEPER : colour;
  const g = new THREE.Group(), u = { yaw: null, v: 0, vx: 0, vy: 0 };
  if (gl) {                               // the model is scaled to 1.8 m; its shirt (or, with no shirt, all of it) in the kit colour
    const body = SkeletonUtils.clone(gl.scene), box = new THREE.Box3().setFromObject(gl.scene);
    body.scale.setScalar(BODY_M / (box.max.y - box.min.y));
    const paint = () => new THREE.MeshStandardMaterial({ color: kit, roughness: 0.55, emissive: kit, emissiveIntensity: 0.15 });
    const shirted = (m) => /shirt/i.test(m.name);
    const meshes = []; body.traverse((n) => { if (n.isMesh) { n.castShadow = true; meshes.push(n); } });
    const hasShirt = meshes.some((n) => [n.material].flat().some(shirted));
    for (const n of meshes) {
      n.material = Array.isArray(n.material) ? n.material.map((m) => (!hasShirt || shirted(m) ? paint() : m))
        : !hasShirt || shirted(n.material) ? paint() : n.material;
    }
    u.mixer = new THREE.AnimationMixer(body);
    u.acts = Object.fromEntries(["Idle", "Walk", "Run"].map((n) => {
      const clip = gl.animations.find((c) => c.name === n), a = clip && u.mixer.clipAction(clip);
      if (a) { a.play(); a.setEffectiveWeight(0); }
      return [n, a];
    }));
    u.mixer.update(Math.random());
    u.body = body; g.add(body);
  } else {
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 1.0, 6, 12), new THREE.MeshStandardMaterial({ color: kit, roughness: 0.6 }));
    body.position.y = 0.9; body.castShadow = true; g.add(body);
  }
  // the number on a tag in the kit colour: white on the team colour, the keeper's in the team colour on amber
  const tag = label(String(shirt ?? ""), keeper ? colour : "#ffffff", 0.8, kit); tag.position.y = 2.4; g.add(tag);
  if (carrier) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.15, 40), new THREE.MeshBasicMaterial({ color: "#ffffff", side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.03; g.add(ring);
  }
  g.userData = u;
  return g;
}

function arrow(scene, a, b, colour, width, dashed) {   // a flat arrow on the grass; returns its material for fading
  const mat = new THREE.MeshBasicMaterial({ color: colour, side: THREE.DoubleSide, transparent: true, opacity: 0 });
  const d = b.clone().sub(a), len = d.length(), rot = Math.atan2(-(b.z - a.z), b.x - a.x), head = width * 4;
  const piece = (from, to) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(to - from, width), mat);
    m.rotation.x = -Math.PI / 2; m.rotation.z = rot; m.position.copy(a.clone().lerp(b, (from + to) / 2 / len)); scene.add(m);
  };
  if (dashed) for (let t = 1; t < len - head; t += 1) piece(t, Math.min(t + 0.55, len - head));
  else piece(0, len - head);
  const cone = new THREE.Mesh(new THREE.ConeGeometry(width * 1.7, head, 3), mat), holder = new THREE.Group();
  cone.rotation.z = -Math.PI / 2; cone.position.x = -head / 2; holder.add(cone);
  holder.position.copy(b); holder.rotation.y = rot; holder.scale.y = 0.15; scene.add(holder);
  return mat;
}

// the four marks and the receivers' runs, drawn at the decision; returns what fades in and out
function marks(scene, x, at, name) {
  const fade = [], marked = x.options.filter((o) => o.target_x != null && MARKS.some(([k]) => o[k])), runs = new Set();
  for (const o of marked) {
    const hits = MARKS.filter(([k]) => o[k]);
    hits.forEach(([, colour], i) => {
      const a = P(x.x, x.y, 0.05 + 0.01 * i), b = P(o.target_x, o.target_y, 0.05 + 0.01 * i);
      const side = new THREE.Vector3(-(b.z - a.z), 0, b.x - a.x).normalize().multiplyScalar((i - (hits.length - 1) / 2) * 0.7);
      fade.push(arrow(scene, a.add(side), b.add(side), colour, 0.35, false));
    });
    const t = label(name(o), hits[0][1], 1.2); t.position.copy(P(o.target_x, o.target_y, 3.8)); scene.add(t); fade.push(t.material);
    const mate = at[o.target_player_id], key = `${o.target_player_id} ${o.target_x} ${o.target_y}`;
    if (!mate || runs.has(key) || Math.hypot(o.target_x - mate.x, o.target_y - mate.y) < RUN_MIN_GAIN) continue;
    runs.add(key);                       // a ball played into space ahead of him: his run there, white and dashed
    fade.push(arrow(scene, P(mate.x, mate.y, 0.06), P(o.target_x, o.target_y, 0.06), "#ffffff", 0.25, true));
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.0, 1.2, 32), fade[fade.length - 1]);
    ring.rotation.x = -Math.PI / 2; ring.position.copy(P(mate.x, mate.y, 0.06)); scene.add(ring);
    const r = label(`${(o.target_name || "").split(" ").pop()} runs`, "#ffffff", 0.9);
    r.position.copy(P((mate.x + o.target_x) / 2, (mate.y + o.target_y) / 2, 1.4)); scene.add(r); fade.push(r.material);
  }
  return [fade, marked];
}

export function stop() {
  if (!stage) return;
  cancelAnimationFrame(stage.raf); stage.renderer.dispose(); stage = null;
}

export async function play(div, frames, x, home, name) {
  stop();
  if (!frames.length) return;
  const gl = await model(), width = div.clientWidth || div.parentElement.clientWidth, height = Math.round(width * 9 / 16);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio); renderer.setSize(width, height); renderer.shadowMap.enabled = true;
  const scene = new THREE.Scene(); scene.background = new THREE.Color("#0f2a17"); pitch(scene);
  const cap = document.createElement("div"), legend = document.createElement("div"), bar = document.createElement("div");
  cap.className = "cap"; legend.className = "legend"; bar.className = "bar";
  legend.innerHTML = MARKS.map(([, c, t]) => `<div><b style="background:${c}"></b>${t}</div>`).join("")
    + `<div><b class="dash"></b>Receiver's run</div>`;
  const cams = document.createElement("div"), hint = document.createElement("div");
  cams.className = "cams"; hint.className = "hint";
  cams.innerHTML = VIEWS.map(([k, t]) => `<button data-v="${k}">${t}</button>`).join("");
  hint.innerHTML = `<span>Drag to rotate · right-drag to pan · scroll to zoom</span><button data-k="reset">Reset view</button>`;
  const screen = document.createElement("div"); screen.className = "screen"; screen.append(renderer.domElement, cap, legend, cams, hint);
  bar.innerHTML = `<button data-k="play">❚❚ Pause</button><button data-k="slow">½× speed</button><input type="range" min="0" max="1000" value="0">`;
  div.replaceChildren(screen, bar);

  const people = {}, t0 = frames[0].ts_ms, tEnd = frames[frames.length - 1].ts_ms;
  for (const f of frames) for (const o of f.objects) if (o.id !== "ball" && !people[o.id]) {
    people[o.id] = player(gl, o.team_id === home ? HOME : AWAY, o.shirt, o.id === x.player_id, o.position === "GK"); scene.add(people[o.id]);
  }
  const ball = new THREE.Mesh(new THREE.SphereGeometry(BALL_R, 24, 16), new THREE.MeshStandardMaterial({ map: ballSkin(), roughness: 0.4 }));
  ball.castShadow = true; scene.add(ball);
  const at = Object.fromEntries(where(frames, x.ts_ms).map((o) => [o.id, o]));
  const [fade, marked] = marks(scene, x, at, name);
  const runners = marked.map((o) => at[o.target_player_id]).filter(Boolean);   // where the receivers' runs start
  const xs = [x.x, ...marked.map((o) => o.target_x), ...runners.map((m) => m.x)];
  const ys = [x.y, ...marked.map((o) => o.target_y), ...runners.map((m) => m.y)];
  const decX = (Math.min(...xs) + Math.max(...xs)) / 2, decY = (Math.min(...ys) + Math.max(...ys)) / 2 - 2;
  // on the decision the camera steps back (and up) far enough for every arrow: ~35 m across and ~20 m deep per step
  const decZ = clamp(Math.max((Math.max(...xs) - Math.min(...xs) + 12) / 35, (Math.max(...ys) - Math.min(...ys) + 8) / 20), 1.5, 2.8);
  const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 500);
  // dragging, panning or zooming hands the camera to the viewer until "Reset view" or another camera is picked
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI / 2 - 0.05; controls.minDistance = 5; controls.maxDistance = 160;

  // the clip's clock: data time runs to the decision, stands still for HOLD_S, then runs on
  const dec = clamp(x.ts_ms, t0, tEnd), total = (tEnd - t0) / 1000 + HOLD_S;
  const dataMs = (s) => { const d = t0 + s * 1000; return d < dec ? d : d < dec + HOLD_S * 1000 ? dec : d - HOLD_S * 1000; };
  const held = (s) => t0 + s * 1000 >= dec && t0 + s * 1000 < dec + HOLD_S * 1000;
  const st = { s: 0, rate: 1, playing: true, last: performance.now(), cam: null, lastBall: null, pos: null, look: null, free: false, owner: null };
  controls.addEventListener("start", () => { st.free = true; });
  const pick = (v) => { view = v; st.free = false; for (const b of cams.children) b.classList.toggle("on", b.dataset.v === v); };
  pick(view);
  cams.onclick = (e) => { if (e.target.dataset.v) pick(e.target.dataset.v); };
  hint.querySelector("[data-k=reset]").onclick = () => pick(view);
  const slider = bar.querySelector("input"), playBtn = bar.querySelector("[data-k=play]"), slowBtn = bar.querySelector("[data-k=slow]");
  playBtn.onclick = () => { if (st.s >= total) st.s = 0; st.playing = !st.playing; playBtn.textContent = st.playing ? "❚❚ Pause" : "▶ Play"; };
  slowBtn.onclick = () => { st.rate = st.rate === 1 ? 0.5 : 1; slowBtn.textContent = st.rate === 1 ? "½× speed" : "1× speed"; };
  slider.oninput = () => { st.s = (slider.value / 1000) * total; st.cam = null; st.pos = null; };

  const draw = (dt) => {
    const ms = dataMs(st.s), now = where(frames, ms), before = byId(where(frames, ms - 200)), after = byId(where(frames, ms + 200));
    const paused = held(st.s) || !st.playing;
    let raw = null;
    for (const o of now) {
      if (o.id === "ball") { raw = o; continue; }
      const g = people[o.id]; if (!g) continue;
      g.position.copy(P(o.x, o.y)); g.visible = true;
      const u = g.userData, a = before[o.id], b = after[o.id];
      if (a && b) { u.vx = (b.x - a.x) / 0.4; u.vy = (b.y - a.y) / 0.4; u.v = Math.hypot(u.vx, u.vy); }
      if (u.mixer) {                      // stand, walk or run by speed, faster steps when sprinting
        const v = u.v, w = { Idle: Math.max(0, 1 - v / 1.5), Walk: v < 1.5 ? v / 1.5 : Math.max(0, 1 - (v - 1.5) / 2.5), Run: clamp((v - 1.5) / 2.5, 0, 1) };
        for (const n in w) if (u.acts[n]) u.acts[n].setEffectiveWeight(w[n]);
        u.mixer.update(paused ? 0 : dt * st.rate * (v > 4 ? v / 5 : 1));
        const want = v > 0.6 ? Math.atan2(u.vx, -u.vy) : (o.team_id === home ? Math.PI / 2 : -Math.PI / 2);   // the model faces +z
        if (u.yaw === null) u.yaw = want;
        const d = want - u.yaw; u.yaw += Math.atan2(Math.sin(d), Math.cos(d)) * 0.25; u.body.rotation.y = u.yaw;
      }
    }
    for (const id in people) if (!now.some((o) => o.id === id)) people[id].visible = false;
    if (raw) placeBall(ball, raw, before.ball, after.ball, people, ms, st);
    // the marks fade in on the decision and out after it
    const into = t0 + st.s * 1000 - dec, show = into < 0 ? 0 : into < HOLD_S * 1000 ? Math.min(1, into / 1000 / FADE_S)
      : Math.max(0, 1 - (into / 1000 - HOLD_S) / FADE_S);
    for (const m of fade) m.opacity = show * (m.isSpriteMaterial ? 1 : 0.95);
    legend.style.opacity = show;
    const clock = (t) => { const s = Math.floor(t / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
    cap.textContent = held(st.s) ? `${clock(x.ts_ms)}  ${x.player_name}: the decision` : clock(ms);
    // the camera follows the ball from the touchline and steps back to show the whole decision
    const tx = held(st.s) ? decX : ball.position.x + 52.5, ty = held(st.s) ? decY : 34 - ball.position.z, tz = held(st.s) ? decZ : 0.7;
    if (!st.cam) st.cam = { x: tx, y: ty, z: tz };
    const k = 1 - Math.exp(-dt * 2.5);
    st.cam.x += (tx - st.cam.x) * k; st.cam.y += (ty - st.cam.y) * k; st.cam.z += (tz - st.cam.z) * k;
    if (st.free) controls.update();
    else {
      const [pos, look] = shot(view, st.cam, held(st.s), held(st.s) ? people[x.player_id] : st.owner);
      if (!st.pos) { st.pos = pos; st.look = look; }
      const kc = 1 - Math.exp(-dt * 3);           // a new camera glides to its place instead of jumping
      st.pos.lerp(pos, kc); st.look.lerp(look, kc);
      camera.position.copy(st.pos); camera.lookAt(st.look); controls.target.copy(st.look);
    }
    renderer.render(scene, camera);
  };
  const tick = (t) => {
    const dt = Math.min(0.1, (t - st.last) / 1000); st.last = t;
    if (st.playing) { st.s += dt * st.rate; if (st.s >= total) { st.s = total; st.playing = false; playBtn.textContent = "▶ Play"; } }
    slider.value = Math.round((st.s / total) * 1000);
    draw(dt);
    stage.raf = requestAnimationFrame(tick);
  };
  stage = { renderer, raf: requestAnimationFrame(tick) };
}

// where each camera stands and looks, around the point it follows (c: pitch x, y and how far back, z):
// broadcast high on the touchline, tactical over the whole pitch, sideline low on the touchline,
// player behind the man on the ball looking where he faces (further back and higher on the decision)
function shot(v, c, hold, man) {
  if (v === "tactical") return [P(52.5, -38, 92), P(52.5, 30, 0)];
  if (v === "sideline") return [P(c.x, c.y - 16 * c.z - 6, 2 + 2.5 * c.z), P(c.x, c.y + 2, 0.5)];
  if (v === "player" && man) {
    const yaw = man.userData.yaw ?? 0, fx = Math.sin(yaw), fz = Math.cos(yaw), back = hold ? 13 : 9, up = hold ? 8 : 4.5;
    const p = man.position;
    return [new THREE.Vector3(p.x - fx * back, up, p.z - fz * back), new THREE.Vector3(p.x + fx * 12, 0, p.z + fz * 12)];
  }
  return [P(c.x - 5, c.y - 30 * c.z, 16 * c.z), P(c.x, c.y + 2, 0)];
}

// the objects at a time, each moved in a line between the two frames around it
function where(frames, ms) {
  const i = frames.findIndex((f) => f.ts_ms >= ms);
  if (i < 0) return frames[frames.length - 1].objects;
  if (i === 0) return frames[0].objects;
  const a = frames[i - 1], b = frames[i], w = (ms - a.ts_ms) / (b.ts_ms - a.ts_ms || 1), prev = byId(a.objects);
  return b.objects.map((o) => (prev[o.id] ? { ...o, x: prev[o.id].x + (o.x - prev[o.id].x) * w, y: prev[o.id].y + (o.y - prev[o.id].y) * w } : o));
}
const byId = (objs) => Object.fromEntries(objs.map((o) => [o.id, o]));

// the data puts the ball on the carrier's spot: draw it in front of him, pushed ahead on each touch, and roll it.
// A ball moving faster than 8 m/s is in flight and is not pulled to a player it passes
function placeBall(ball, raw, a, b, people, ms, st) {
  const p = P(raw.x, raw.y, BALL_R);
  const flying = a && b && Math.hypot(b.x - a.x, b.y - a.y) / 0.4 > FLIGHT_MS;
  let near = null, dmin = NEAR_M;
  if (!flying) for (const id in people) {
    const g = people[id], d = Math.hypot(g.position.x - p.x, g.position.z - p.z);
    if (g.visible && d < dmin) { dmin = d; near = g; }
  }
  if (near) {
    st.owner = near;
    const u = near.userData;
    let fx = 0, fz = 0;
    if (u.v > 1) { fx = u.vx / u.v; fz = -u.vy / u.v; } else if (u.yaw !== null) { fx = Math.sin(u.yaw); fz = Math.cos(u.yaw); }
    const touch = 0.6 / Math.max(1, u.v / 3), phase = ((ms / 1000) % touch) / touch;
    const ahead = 0.45 + (u.v > 1 ? Math.min(1.1, u.v * 0.18) * (1 - phase) : 0), w = clamp((NEAR_M - dmin) / 0.6, 0, 1);
    p.set(p.x + (near.position.x + fx * ahead - p.x) * w, p.y, p.z + (near.position.z + fz * ahead - p.z) * w);
  }
  if (st.lastBall) {
    const dx = p.x - st.lastBall.x, dz = p.z - st.lastBall.z, dist = Math.hypot(dx, dz);
    if (dist > 1e-4 && dist < 3) ball.rotateOnWorldAxis(new THREE.Vector3(dz, 0, -dx).normalize(), dist / BALL_R);
  }
  ball.position.copy(p); st.lastBall = p.clone();
}

function ballSkin() {                    // white with dark patches, so the roll shows
  const c = document.createElement("canvas"); c.width = 256; c.height = 128; const g = c.getContext("2d");
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, 256, 128); g.fillStyle = "#222222";
  for (const [x, y] of [[32, 30], [96, 70], [160, 30], [224, 70], [64, 105], [192, 105], [128, 10]]) {
    g.beginPath(); for (let a = 0; a < 5; a += 1) g.lineTo(x + 13 * Math.cos(a * 1.2566), y + 13 * Math.sin(a * 1.2566)); g.fill();
  }
  return new THREE.CanvasTexture(c);
}

window.replay3d = { play, stop };

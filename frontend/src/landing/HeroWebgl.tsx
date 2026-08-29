/** Fondo 3D animado del hero — portado de diseno/Factuchat - pagina web.html
 * (hero-webgl.js extraído del bundle). La maqueta lo carga desde un CDN
 * (unpkg/esm.sh); aquí usa el `three` instalado como dependencia normal, así
 * queda en el bundle propio y no depende de una red externa en producción. */
import { useEffect, useRef } from "react";
import * as THREE from "three";

function docTexture(accent: string) {
  const w = 256,
    h = 340;
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const x = c.getContext("2d")!;
  const r = 18;
  x.beginPath();
  x.moveTo(r, 0);
  x.lineTo(w - r, 0);
  x.quadraticCurveTo(w, 0, w, r);
  x.lineTo(w, h - r);
  x.quadraticCurveTo(w, h, w - r, h);
  x.lineTo(r, h);
  x.quadraticCurveTo(0, h, 0, h - r);
  x.lineTo(0, r);
  x.quadraticCurveTo(0, 0, r, 0);
  x.closePath();
  x.fillStyle = "rgba(9,32,24,.82)";
  x.fill();
  x.strokeStyle = accent;
  x.lineWidth = 3;
  x.globalAlpha = 0.5;
  x.stroke();
  x.globalAlpha = 1;
  x.fillStyle = accent;
  x.globalAlpha = 0.85;
  x.fillRect(28, 34, 92, 9);
  x.globalAlpha = 0.3;
  x.fillRect(28, 62, 150, 6);
  const rows = [104, 128, 152, 176, 200];
  rows.forEach((y, i) => {
    x.globalAlpha = 0.22;
    x.fillRect(28, y, 200 - i * 14, 5);
  });
  x.globalAlpha = 0.1;
  x.fillRect(28, 232, 200, 1);
  x.globalAlpha = 0.7;
  x.fillRect(148, 250, 80, 8);
  x.globalAlpha = 0.3;
  x.fillRect(28, 250, 54, 8);
  x.globalAlpha = 0.55;
  x.beginPath();
  x.arc(214, 302, 14, 0, Math.PI * 2);
  x.fill();
  const t = new THREE.CanvasTexture(c);
  t.anisotropy = 4;
  return t;
}

const GLYPH: Record<string, string> = {
  wa: "M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.46 1.32 4.96L2 22l5.25-1.38a9.9 9.9 0 004.79 1.22h.01c5.46 0 9.91-4.45 9.91-9.91S17.5 2 12.04 2zm5.8 14.06c-.24.68-1.4 1.3-1.93 1.35-.53.05-1.03.24-2.9-.62-2.23-1.02-3.63-3.36-3.74-3.51-.11-.16-.9-1.24-.9-2.37 0-1.13.58-1.68.79-1.91.2-.23.44-.29.59-.29.15 0 .3 0 .43.01.14.01.32-.5.5.39.18.44.6 1.51.65 1.62.05.11.08.24.01.38-.7.15-.13.24-.26.38-.13.14-.25.25-.36.4-.12.14-.26.3-.11.57.15.27.63 1.05 1.36 1.7.93.83 1.67 1.09 1.94 1.21.27.12.42.1.58-.6.16-.16.7-.79.89-1.06.19-.27.38-.22.63-.13.25.9 1.6.78 1.87.92.28.14.46.21.53.32.7.11.7.64-.17 1.32z",
  spark: "M12 1.6l2.2 6.4a3 3 0 001.8 1.8l6.4 2.2-6.4 2.2a3 3 0 00-1.8 1.8L12 22.4l-2.2-6.4a3 3 0 00-1.8-1.8L1.6 12l6.4-2.2a3 3 0 001.8-1.8z",
  check: "M9.2 16.4L5 12.2l-1.5 1.5 5.7 5.7L21.5 7.1 20 5.6z",
  bubble: "M20 2.5H4a2 2 0 00-2 2v11a2 2 0 002 2h3.4v4l4.4-4H20a2 2 0 002-2v-11a2 2 0 00-2-2z",
  receipt: "M5.6 1.8v20.4l2.1-1.6 2.1 1.6 2.1-1.6 2.1 1.6 2.1-1.6 2.2 1.6V1.8H5.6zm2.6 5h7.6v1.8H8.2V6.8zm0 4.2h7.6v1.8H8.2V11zm0 4.2h4.8V17H8.2v-1.8z",
  bell: "M12 22.4a2.4 2.4 0 002.4-2.4H9.6a2.4 2.4 0 002.4 2.4zm7.4-5.6v-5.6c0-3.5-1.9-6.4-5.1-7.1v-.8a2.3 2.3 0 10-4.6 0v.8c-3.2.7-5.1 3.6-5.1 7.1v5.6L2.4 19v1.1h19.2V19l-2.2-2.2z",
  chart: "M3.6 20.6h4V10h-4v10.6zm6.4 0h4V3.4h-4v17.2zm6.4 0h4v-8h-4v8z",
  shield: "M12 1.8L3.6 5.4v6c0 5.2 3.6 10 8.4 11.2 4.8-1.2 8.4-6 8.4-11.2v-6L12 1.8zm-1.4 15.4l-4-4 1.6-1.6 2.4 2.4 6-6 1.6 1.6-7.6 7.6z",
};

function drawGlyph(x: CanvasRenderingContext2D, path: string, size: number, color: string) {
  const p = new Path2D(path);
  const k = size / 24;
  x.save();
  x.translate((128 - size) / 2, (128 - size) / 2);
  x.scale(k, k);
  x.fillStyle = color;
  x.fill(p);
  x.restore();
}

function iconTexture(kind: string, accent: string) {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 128;
  const x = c.getContext("2d")!;
  if (kind === "wa") {
    const g = x.createRadialGradient(64, 52, 6, 64, 64, 62);
    g.addColorStop(0, "#5CE68F");
    g.addColorStop(1, "#12984A");
    x.beginPath();
    x.arc(64, 64, 58, 0, Math.PI * 2);
    x.fillStyle = g;
    x.fill();
    x.lineWidth = 3;
    x.strokeStyle = "rgba(255,255,255,.55)";
    x.globalAlpha = 0.6;
    x.stroke();
    x.globalAlpha = 1;
    drawGlyph(x, GLYPH.wa, 72, "#FFFFFF");
  } else {
    const r = 30;
    x.beginPath();
    x.moveTo(r + 6, 6);
    x.lineTo(122 - r, 6);
    x.quadraticCurveTo(122, 6, 122, 6 + r);
    x.lineTo(122, 122 - r);
    x.quadraticCurveTo(122, 122, 122 - r, 122);
    x.lineTo(6 + r, 122);
    x.quadraticCurveTo(6, 122, 6, 122 - r);
    x.lineTo(6, 6 + r);
    x.quadraticCurveTo(6, 6, 6 + r, 6);
    x.closePath();
    x.fillStyle = "rgba(9,32,24,.86)";
    x.fill();
    x.lineWidth = 3;
    x.strokeStyle = accent;
    x.globalAlpha = 0.55;
    x.stroke();
    x.globalAlpha = 1;
    drawGlyph(x, GLYPH[kind] || GLYPH.spark, 62, accent);
  }
  const t = new THREE.CanvasTexture(c);
  t.anisotropy = 4;
  return t;
}

function dotTexture() {
  const s = 64;
  const c = document.createElement("canvas");
  c.width = s;
  c.height = s;
  const x = c.getContext("2d")!;
  const g = x.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(160,255,200,.7)");
  g.addColorStop(1, "rgba(160,255,200,0)");
  x.fillStyle = g;
  x.fillRect(0, 0, s, s);
  return new THREE.CanvasTexture(c);
}

/** Fondo 3D del hero: partículas, documentos flotando, íconos orbitando. */
export function HeroWebgl({ accent = "#5CE68F", background = "#07231B" }: { accent?: string; background?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    const w = host.clientWidth || 1200;
    const h = host.clientHeight || 700;
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(new THREE.Color(background), 18, 56);

    const camera = new THREE.PerspectiveCamera(52, w / h, 0.1, 120);
    camera.position.set(0, 1.6, 15);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    host.appendChild(renderer.domElement);

    const world = new THREE.Group();
    scene.add(world);

    const grid = new THREE.GridHelper(90, 60, new THREE.Color(accent), new THREE.Color(accent));
    const gridMat = grid.material as THREE.LineBasicMaterial;
    gridMat.transparent = true;
    gridMat.opacity = 0.4;
    gridMat.depthWrite = false;
    grid.position.y = -4.2;
    world.add(grid);

    const grid2 = grid.clone();
    const grid2Mat = gridMat.clone();
    grid2Mat.opacity = 0.22;
    grid2.material = grid2Mat;
    grid2.position.y = 7.4;
    grid2.rotation.x = Math.PI;
    world.add(grid2);

    const N = 1400;
    const pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 58;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 22;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 52;
    }
    const pg = new THREE.BufferGeometry();
    pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const points = new THREE.Points(
      pg,
      new THREE.PointsMaterial({
        size: 0.2,
        map: dotTexture(),
        transparent: true,
        opacity: 0.8,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      }),
    );
    world.add(points);

    const tex = docTexture(accent);
    const geo = new THREE.PlaneGeometry(2.1, 2.8);
    const spots: [number, number, number, number, number][] = [
      [-8.4, 2.1, -3, -0.22, 0.38],
      [7.9, 3.3, -5.5, 0.2, -0.42],
      [-6.2, -2.6, 1.4, 0.16, 0.3],
      [9.2, -1.8, -1.2, -0.14, -0.3],
      [-11.4, 0.4, -8.5, 0.1, 0.5],
      [4.6, 4.6, -9.5, -0.1, -0.24],
      [11.8, 1.2, -7.8, 0.06, -0.52],
    ];
    const docs = spots.map((s, i) => {
      const m = new THREE.Mesh(
        geo,
        new THREE.MeshBasicMaterial({
          map: tex,
          transparent: true,
          opacity: 0.72 - (i % 3) * 0.1,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      m.position.set(s[0], s[1], s[2]);
      m.rotation.set(s[3], s[4], (Math.random() - 0.5) * 0.12);
      const ud = { y0: s[1], sp: 0.28 + Math.random() * 0.3, ph: Math.random() * 6.28, rs: (Math.random() - 0.5) * 0.1 };
      m.userData = ud;
      world.add(m);
      return m;
    });

    const orbit = new THREE.Group();
    orbit.rotation.x = -0.24;
    orbit.position.z = -16;
    orbit.position.y = 0.6;
    world.add(orbit);
    const rings = [
      { kind: "wa", r: 9, y: 1.2, sp: 0.17, ph: 0, s: 2.4, op: 1 },
      { kind: "bubble", r: 9, y: 1.2, sp: 0.17, ph: 2.09, s: 1.6, op: 0.88 },
      { kind: "check", r: 9, y: 1.2, sp: 0.17, ph: 4.19, s: 1.6, op: 0.88 },
      { kind: "wa", r: 13.4, y: -1.8, sp: -0.11, ph: 0.9, s: 2, op: 0.95 },
      { kind: "receipt", r: 13.4, y: -1.8, sp: -0.11, ph: 2.5, s: 1.7, op: 0.8 },
      { kind: "spark", r: 13.4, y: -1.8, sp: -0.11, ph: 4.1, s: 1.7, op: 0.8 },
      { kind: "shield", r: 13.4, y: -1.8, sp: -0.11, ph: 5.7, s: 1.7, op: 0.8 },
      { kind: "chart", r: 18, y: 4.2, sp: 0.075, ph: 0.4, s: 1.9, op: 0.6 },
      { kind: "bell", r: 18, y: 4.2, sp: 0.075, ph: 2.5, s: 1.9, op: 0.6 },
      { kind: "wa", r: 18, y: 4.2, sp: 0.075, ph: 4.6, s: 2.2, op: 0.75 },
    ];
    const texCache: Record<string, THREE.CanvasTexture> = {};
    const icons = rings.map((o) => {
      if (!texCache[o.kind]) texCache[o.kind] = iconTexture(o.kind, accent);
      const sp = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: texCache[o.kind], transparent: true, opacity: o.op, depthWrite: false }),
      );
      sp.scale.set(o.s, o.s, 1);
      sp.userData = o;
      orbit.add(sp);
      return sp;
    });

    const lineMat = new THREE.LineBasicMaterial({ color: new THREE.Color(accent), transparent: true, opacity: 0.5, depthWrite: false });
    for (let s = 0; s < 5; s++) {
      const pts: THREE.Vector3[] = [];
      for (let i = 0; i < 5; i++) {
        pts.push(new THREE.Vector3((Math.random() - 0.5) * 46, (Math.random() - 0.5) * 15, (Math.random() - 0.5) * 40));
      }
      const curve = new THREE.CatmullRomCurve3(pts);
      world.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(70)), lineMat));
    }

    let tx = 0,
      ty = 0,
      cx = 0,
      cy = 0;
    const onMove = (e: PointerEvent) => {
      tx = (e.clientX / window.innerWidth - 0.5) * 2;
      ty = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    if (!reduce) window.addEventListener("pointermove", onMove, { passive: true });

    const resize = () => {
      const W = host.clientWidth || w,
        H = host.clientHeight || h;
      renderer.setSize(W, H, false);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    let visible = true;
    let io: IntersectionObserver | undefined;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver((es) => {
        visible = es[0].isIntersecting;
      }, { threshold: 0 });
      io.observe(host);
    }

    let raf = 0;
    let dead = false;
    const clock = new THREE.Clock();
    const tick = () => {
      if (dead) return;
      raf = requestAnimationFrame(tick);
      if (!visible) return;
      const t = clock.getElapsedTime();
      cx += (tx - cx) * 0.045;
      cy += (ty - cy) * 0.045;
      camera.position.x = cx * 2.6;
      camera.position.y = 1.6 - cy * 1.5;
      camera.lookAt(0, 0.8, 0);
      world.rotation.y = t * 0.022 + cx * 0.09;
      points.rotation.y = -t * 0.012;
      icons.forEach((sp) => {
        const o = sp.userData as { sp: number; ph: number; r: number; y: number };
        const a = t * o.sp + o.ph;
        sp.position.set(Math.cos(a) * o.r, o.y + Math.sin(t * 0.5 + o.ph) * 0.45, Math.sin(a) * o.r);
      });
      docs.forEach((m) => {
        const ud = m.userData as { y0: number; sp: number; ph: number; rs: number };
        m.position.y = ud.y0 + Math.sin(t * ud.sp + ud.ph) * 0.5;
        m.rotation.z += ud.rs * 0.0016;
        m.rotation.y += 0.0012;
      });
      renderer.render(scene, camera);
    };
    if (reduce) {
      renderer.render(scene, camera);
    } else {
      tick();
    }

    return () => {
      dead = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io?.disconnect();
      window.removeEventListener("pointermove", onMove);
      renderer.dispose();
      host.removeChild(renderer.domElement);
    };
  }, [accent, background]);

  return <div ref={hostRef} className="lp-hero-webgl" aria-hidden="true" />;
}

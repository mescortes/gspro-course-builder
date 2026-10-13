// 3D grass for the viewer: a stand-in for the Stix Games DX11 Grass Shader ("3DG") that GSPro courses put on their
// semi-rough / rough / deep-rough meshes. 3DG grows blades from the mesh surface on the GPU; WebGL has no geometry
// shaders, so here blade clumps are instanced over the terrain triangles of each grass surface near the camera.
// Settings per surface come from output/gspro/grass_3dg.json (the same spec handed over for 3DG), with defaults.
import * as THREE from 'three';

export const DEFAULT_SPEC = {
  radius_m: 55,             // blades beyond this are not drawn
  full_density_m: 22,       // full density up to here, then thinned towards radius_m
  far_density: 0.18,        // fraction of clumps kept at radius_m
  tile_m: 6,
  max_instances: 400000,
  wind: { strength: 0.35, speed: 1.0 },
  surfaces: {               // object-name suffix -> blade settings (height m, width m, clumps per m2, blades per clump)
    SemiRough: { height: [0.03, 0.05], width: 0.008, density: 45, blades: 8,  colour_tip: [1.06, 1.10, 1.02], dry: 0.0 },
    Rough:     { height: [0.05, 0.09], width: 0.009, density: 40, blades: 9,  colour_tip: [1.07, 1.12, 1.02], dry: 0.05 },
    DeepRough: { height: [0.14, 0.32], width: 0.010, density: 14, blades: 9,  colour_tip: [1.14, 1.10, 0.88], dry: 0.25 },
    Pinestraw: { height: [0.22, 0.45], width: 0.008, density: 7,  blades: 10, colour_tip: [1.22, 1.12, 0.82], dry: 0.6 },
  },
};

function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// one clump of `n` tapered, slightly curved blades of unit height (scaled per instance in the shader)
function clumpGeometry(n, width, seed) {
  const rnd = mulberry32(seed);
  const SEG = 3, pos = [], uv = [], nrm = [], idx = [];
  for (let b = 0; b < n; b++) {
    const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd()) * 0.035;
    const ox = Math.cos(a) * r, oz = Math.sin(a) * r;
    const face = rnd() * Math.PI * 2, fx = Math.cos(face), fz = Math.sin(face);
    const lean = 0.04 + rnd() * 0.22, la = rnd() * Math.PI * 2, lx = Math.cos(la) * lean, lz = Math.sin(la) * lean;
    const hs = 0.7 + rnd() * 0.3, w = width * (0.8 + rnd() * 0.4);
    const base = pos.length / 3;
    for (let s = 0; s <= SEG; s++) {
      const v = s / SEG, half = 0.5 * w * Math.pow(1 - v, 0.9) + 0.0004;
      const cx = ox + lx * v * v * hs, cz = oz + lz * v * v * hs, y = v * hs;
      pos.push(cx - fz * half, y, cz + fx * half, cx + fz * half, y, cz - fx * half);
      uv.push(0, v, 1, v);
      // normals mostly up (lawn-like shading), tilted towards the blade face
      for (let k = 0; k < 2; k++) nrm.push(fx * 0.12, 0.99, fz * 0.12);
    }
    for (let s = 0; s < SEG; s++) {
      const i = base + s * 2;
      idx.push(i, i + 1, i + 2, i + 1, i + 3, i + 2);
    }
  }
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

function grassMaterial(set, uniforms) {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0, side: THREE.DoubleSide });
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, uniforms);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', `#include <common>
        attribute vec4 iPos;      // xyz, yaw
        attribute vec4 iParam;    // height, rank (0..1, for distance thinning), dryness, unused
        attribute vec3 iColor;
        uniform float uTime, uWind, uWindSpeed, uFull, uRadius, uFar;
        uniform vec3 uCam, uTip;
        varying vec3 vGrassCol;
        varying float vV;`)
      .replace('#include <begin_vertex>', `
        float d = distance(iPos.xz, uCam.xz);
        float keep = d < uFull ? 1.0 : mix(1.0, uFar, clamp((d - uFull) / (uRadius - uFull), 0.0, 1.0));
        float alive = step(iParam.y, keep) * (1.0 - smoothstep(uRadius * 0.85, uRadius, d));
        float h = iParam.x * alive;
        float cy = cos(iPos.w), sy = sin(iPos.w);
        vec3 p = vec3(cy * position.x - sy * position.z, position.y, sy * position.x + cy * position.z);
        p.y *= h; p.xz *= mix(1.0, 1.6, smoothstep(uFull, uRadius, d));   // far clumps a little wider
        float v = uv.y;
        float ph = iPos.x * 0.37 + iPos.z * 0.23;
        float sway = (sin(uTime * 1.6 * uWindSpeed + ph) * 0.6 + sin(uTime * 3.3 * uWindSpeed + ph * 2.7) * 0.25) * uWind;
        p.x += sway * v * v * h * 1.2; p.z += sway * v * v * h * 0.5;
        vec3 transformed = p + iPos.xyz;
        vV = v;
        vGrassCol = iColor * mix(vec3(0.9), uTip, v);`)
      .replace('#include <beginnormal_vertex>', `#include <beginnormal_vertex>
        { float cy = cos(iPos.w), sy = sin(iPos.w); objectNormal = vec3(cy * objectNormal.x - sy * objectNormal.z, objectNormal.y, sy * objectNormal.x + cy * objectNormal.z); }`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vGrassCol;
        varying float vV;`)
      .replace('vec4 diffuseColor = vec4( diffuse, opacity );', 'vec4 diffuseColor = vec4( vGrassCol, 1.0 );');
  };
  m.customProgramCacheKey = () => 'grass3dg';
  return m;
}

export class Grass {
  constructor(scene, spec = {}) {
    this.spec = { ...DEFAULT_SPEC, ...spec, surfaces: { ...DEFAULT_SPEC.surfaces, ...(spec.surfaces || {}) } };
    this.scene = scene;
    this.uniforms = {
      uTime: { value: 0 }, uWind: { value: this.spec.wind.strength }, uWindSpeed: { value: this.spec.wind.speed },
      uFull: { value: this.spec.full_density_m }, uRadius: { value: this.spec.radius_m }, uFar: { value: this.spec.far_density },
      uCam: { value: new THREE.Vector3() }, uTip: { value: new THREE.Vector3(1.1, 1.1, 0.95) },
    };
    this.types = {};      // surface name -> { set, mesh, geo, attrs }
    this.sources = [];    // [{ type, pos, idx, col, colNorm }]
    this.tiles = new Map();  // key -> { tris: [src, tri, ...], data: {type: Float32Array} | null }
    this.last = null;
    this.enabled = true;
  }

  typeOf(name) {
    for (const k of ['SemiRough', 'DeepRough', 'Rough', 'Pinestraw']) if (name.includes('_' + k)) return this.spec.surfaces[k] ? k : null;
    return null;
  }

  // index the terrain triangles of the grass surfaces into tiles (once, after loading)
  index(meshes) {
    const T = this.spec.tile_m;
    for (const o of meshes) {
      const t = this.typeOf(o.name) || this.typeOf(o.parent?.name || '');
      if (!t) continue;
      o.updateWorldMatrix(true, false);
      if (!o.matrixWorld.equals(new THREE.Matrix4())) continue;   // terrain is authored in world space
      const g = o.geometry, pos = g.attributes.position.array, idx = g.index.array;
      const ca = g.attributes.color, ma = g.attributes.color_1;   // COLOR_1 = 3DG density masks (R grass, G dry)
      const scaleOf = (a) => a && a.normalized ? (a.array instanceof Uint8Array ? 1 / 255 : 1 / 65535) : 1;
      const src = this.sources.length;
      this.sources.push({ type: t, pos, idx, col: ca ? ca.array : null, colScale: scaleOf(ca), csize: ca ? ca.itemSize : 3,
                          mask: ma ? ma.array : null, maskScale: scaleOf(ma), msize: ma ? ma.itemSize : 4,
                          base: this.baseColour(o.material) });
      for (let f = 0; f < idx.length; f += 3) {
        const a = idx[f] * 3, b = idx[f + 1] * 3, c = idx[f + 2] * 3;
        const cx = (pos[a] + pos[b] + pos[c]) / 3, cz = (pos[a + 2] + pos[b + 2] + pos[c + 2]) / 3;
        const key = Math.floor(cx / T) * 100003 + Math.floor(cz / T);
        let tile = this.tiles.get(key);
        if (!tile) { tile = { ix: Math.floor(cx / T), iz: Math.floor(cz / T), tris: [], data: null }; this.tiles.set(key, tile); }
        tile.tris.push(src, f);
      }
    }
    for (const [name, set] of Object.entries(this.spec.surfaces)) {
      if (!this.sources.some(s => s.type === name)) continue;
      const geo = clumpGeometry(set.blades, set.width, name.length * 977);
      const N = this.spec.max_instances;
      const attrs = { iPos: new THREE.InstancedBufferAttribute(new Float32Array(N * 4), 4),
                      iParam: new THREE.InstancedBufferAttribute(new Float32Array(N * 4), 4),
                      iColor: new THREE.InstancedBufferAttribute(new Float32Array(N * 3), 3) };
      for (const [k, a] of Object.entries(attrs)) { a.setUsage(THREE.DynamicDrawUsage); geo.setAttribute(k, a); }
      geo.instanceCount = 0;
      const u = { ...this.uniforms, uTip: { value: new THREE.Vector3(...set.colour_tip) } };
      const mesh = new THREE.Mesh(geo, grassMaterial(set, u));
      mesh.frustumCulled = false; mesh.receiveShadow = true; mesh.castShadow = false; mesh.name = 'Grass3DG_' + name;
      this.scene.add(mesh);
      this.types[name] = { set, mesh, geo, attrs };
    }
    return this.tiles.size;
  }

  // mean colour of the surface's texture (the vertex colours are relative to it)
  baseColour(mat) {
    const c = new THREE.Color(1, 1, 1);
    const img = mat?.map?.image;
    if (img && img.width) {
      try {
        const cv = document.createElement('canvas'); cv.width = 16; cv.height = 16;
        const g = cv.getContext('2d'); g.drawImage(img, 0, 0, 16, 16);
        const d = g.getImageData(0, 0, 16, 16).data; let r = 0, gg = 0, b = 0;
        for (let i = 0; i < d.length; i += 4) { r += d[i]; gg += d[i + 1]; b += d[i + 2]; }
        const n = d.length / 4; c.setRGB(r / n / 255, gg / n / 255, b / n / 255, THREE.SRGBColorSpace);
      } catch (e) {}
    }
    if (mat?.color) c.multiply(mat.color);
    return c;
  }

  buildTile(tile) {
    const rnd = mulberry32(tile.ix * 73856093 ^ tile.iz * 19349663);
    const out = {};
    const tris = tile.tris;
    for (let i = 0; i < tris.length; i += 2) {
      const s = this.sources[tris[i]], f = tris[i + 1], set = this.spec.surfaces[s.type];
      const ia = s.idx[f], ib = s.idx[f + 1], ic = s.idx[f + 2], P = s.pos;
      const ax = P[ia * 3], ay = P[ia * 3 + 1], az = P[ia * 3 + 2];
      const ux = P[ib * 3] - ax, uy = P[ib * 3 + 1] - ay, uz = P[ib * 3 + 2] - az;
      const vx = P[ic * 3] - ax, vy = P[ic * 3 + 1] - ay, vz = P[ic * 3 + 2] - az;
      const area = 0.5 * Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx);
      let ma = 1, mb = 1, mc = 1, ga = 0, gb = 0, gc = 0;
      if (s.mask) {
        const M = s.mask, z = s.msize, sc = s.maskScale;
        ma = M[ia * z] * sc; mb = M[ib * z] * sc; mc = M[ic * z] * sc;
        ga = M[ia * z + 1] * sc; gb = M[ib * z + 1] * sc; gc = M[ic * z + 1] * sc;
        if (ma + mb + mc <= 0) continue;
      }
      const expect = area * set.density;
      let n = Math.floor(expect); if (rnd() < expect - n) n++;
      if (!n) continue;
      const arr = out[s.type] || (out[s.type] = []);
      for (let k = 0; k < n; k++) {
        let r1 = rnd(), r2 = rnd(); if (r1 + r2 > 1) { r1 = 1 - r1; r2 = 1 - r2; }
        const w0m = 1 - r1 - r2, dens = ma * w0m + mb * r1 + mc * r2;
        if (s.mask && rnd() >= dens) continue;                         // thinned / cleared by the mask
        const dryMask = s.mask ? (ga * w0m + gb * r1 + gc * r2) / Math.max(dens, 1e-3) : null;
        let cr = 1, cg = 1, cb = 1;
        if (s.col) {
          const C = s.col, z = s.csize, sc = s.colScale, w0 = 1 - r1 - r2;
          cr = (C[ia * z] * w0 + C[ib * z] * r1 + C[ic * z] * r2) * sc;
          cg = (C[ia * z + 1] * w0 + C[ib * z + 1] * r1 + C[ic * z + 1] * r2) * sc;
          cb = (C[ia * z + 2] * w0 + C[ib * z + 2] * r1 + C[ic * z + 2] * r2) * sc;
        }
        const dry = dryMask !== null ? Math.min(1, dryMask * (0.6 + 0.8 * rnd())) : set.dry * rnd();
        const jit = 0.85 + rnd() * 0.3;
        arr.push(ax + ux * r1 + vx * r2, ay + uy * r1 + vy * r2, az + uz * r1 + vz * r2, rnd() * Math.PI * 2,
                 set.height[0] + (set.height[1] - set.height[0]) * rnd(), rnd(), dry, 0,
                 s.base.r * cr * jit * (1 + dry * 0.5), s.base.g * cg * jit * (1 + dry * 0.25), s.base.b * cb * jit * (1 - dry * 0.2));
      }
    }
    tile.data = {};
    for (const [t, a] of Object.entries(out)) tile.data[t] = new Float32Array(a);
  }

  update(camera, time, force = false) {
    if (!this.enabled || !Object.keys(this.types).length) return;
    this.uniforms.uTime.value = time;
    const cp = camera.position;
    this.uniforms.uCam.value.copy(cp);
    if (!force && this.last && Math.hypot(cp.x - this.last.x, cp.z - this.last.z) < 2.5 && Math.abs(cp.y - this.last.y) < 5) return;
    this.last = cp.clone();
    const T = this.spec.tile_m, R = this.spec.radius_m + T;
    const near = [];
    const i0 = Math.floor((cp.x - R) / T), i1 = Math.floor((cp.x + R) / T);
    const k0 = Math.floor((cp.z - R) / T), k1 = Math.floor((cp.z + R) / T);
    for (let i = i0; i <= i1; i++) for (let k = k0; k <= k1; k++) {
      const tile = this.tiles.get(i * 100003 + k);
      if (!tile) continue;
      const dx = (i + 0.5) * T - cp.x, dz = (k + 0.5) * T - cp.z, d = Math.hypot(dx, dz);
      if (d > R) continue;
      near.push([d, tile]);
    }
    near.sort((a, b) => a[0] - b[0]);
    const fill = {};
    for (const name of Object.keys(this.types)) fill[name] = 0;
    for (const [, tile] of near) {
      if (!tile.data) this.buildTile(tile);
      for (const [name, data] of Object.entries(tile.data)) {
        const ty = this.types[name]; if (!ty) continue;
        const n = data.length / 11, at = fill[name];
        if (at + n > this.spec.max_instances) continue;
        const P = ty.attrs.iPos.array, Q = ty.attrs.iParam.array, Cc = ty.attrs.iColor.array;
        for (let j = 0; j < n; j++) {
          const o = j * 11, w = at + j;
          P[w * 4] = data[o]; P[w * 4 + 1] = data[o + 1]; P[w * 4 + 2] = data[o + 2]; P[w * 4 + 3] = data[o + 3];
          Q[w * 4] = data[o + 4]; Q[w * 4 + 1] = data[o + 5]; Q[w * 4 + 2] = data[o + 6]; Q[w * 4 + 3] = 0;
          Cc[w * 3] = data[o + 8]; Cc[w * 3 + 1] = data[o + 9]; Cc[w * 3 + 2] = data[o + 10];
        }
        fill[name] = at + n;
      }
    }
    for (const [name, ty] of Object.entries(this.types)) {
      ty.geo.instanceCount = fill[name];
      for (const a of Object.values(ty.attrs)) { a.needsUpdate = true; a.clearUpdateRanges?.(); a.addUpdateRange?.(0, fill[name] * a.itemSize); }
    }
    this.count = fill;
  }

  setVisible(v) { this.enabled = v; for (const t of Object.values(this.types)) t.mesh.visible = v; }
}

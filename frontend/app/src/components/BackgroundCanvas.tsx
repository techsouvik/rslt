import { useEffect, useRef } from 'react';
import * as THREE from 'three';

const vertexShader = `
  attribute vec3 position;
  varying vec3 vPosition;
  void main() {
    vPosition = position;
    gl_Position = vec4(position, 1.0);
  }
`;

const fragmentShader = `
  precision highp float;
  uniform float uTime;
  uniform vec2 uResolution;
  uniform vec2 uMouse;

  #define MAX_STEPS 48
  #define MAX_DIST 20.0
  #define SURF_DIST 0.008
  #define PI 3.14159265359
  #define TAU 6.28318530718

  vec3 mod289v3(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289v4(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289v4(((x * 34.0) + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289v3(i);
    vec4 p = permute(permute(permute(
      i.z + vec4(0.0, i1.z, i2.z, 1.0))
      + i.y + vec4(0.0, i1.y, i2.y, 1.0))
      + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
  }

  float fbm(vec3 p) {
    float val = 0.0;
    float amp = 0.5;
    float freq = 1.0;
    for (int i = 0; i < 4; i++) {
      val += amp * snoise(p * freq);
      freq *= 2.0;
      amp *= 0.5;
    }
    return val;
  }

  float sdSphere(vec3 p, float r) { return length(p) - r; }

  float sdGyroid(vec3 p, float scale, float thickness, float bias) {
    float g = dot(sin(p * scale), cos(p.zxy * scale));
    return (g + bias) / scale - thickness;
  }

  float opSmoothSubtraction(float d1, float d2, float k) {
    float h = clamp(0.5 - 0.5 * (d2 + d1) / k, 0.0, 1.0);
    return mix(d2, -d1, h) + k * h * (1.0 - h);
  }

  float scene(vec3 p) {
    float t = uTime * 0.15;
    p.xz *= mat2(cos(t*0.3), sin(t*0.3), -sin(t*0.3), cos(t*0.3));
    p.yx *= mat2(cos(t*0.2), sin(t*0.2), -sin(t*0.2), cos(t*0.2));
    float sphere = sdSphere(p, 1.2 + 0.1 * sin(uTime * 0.4));
    float gyroid = sdGyroid(p + vec3(uTime*0.05, uTime*0.03, 0.0), 2.5, 0.08, 0.4);
    float d = opSmoothSubtraction(gyroid, sphere, 0.3);
    float noise = fbm(p * 2.0 + vec3(uTime * 0.1)) * 0.15;
    d -= noise;
    return d;
  }

  vec3 getNormal(vec3 p) {
    vec2 e = vec2(0.001, 0.0);
    return normalize(vec3(
      scene(p + e.xyy) - scene(p - e.xyy),
      scene(p + e.yxy) - scene(p - e.yxy),
      scene(p + e.yyx) - scene(p - e.yyx)
    ));
  }

  float softShadow(vec3 ro, vec3 rd, float mint, float maxt, float k) {
    float res = 1.0;
    float ph = 1e10;
    for (float t = mint; t < maxt; ) {
      float h = scene(ro + rd * t);
      if (h < 0.001) return 0.0;
      float y = h * h / (2.0 * ph);
      float d = sqrt(h * h - y * y);
      res = min(res, k * d / max(0.0, t - y));
      ph = h;
      t += h;
    }
    return clamp(res, 0.0, 1.0);
  }

  float calcAO(vec3 p, vec3 n) {
    float occ = 0.0;
    float sca = 1.0;
    for (int i = 0; i < 5; i++) {
      float h = 0.01 + 0.12 * float(i) / 4.0;
      float d = scene(p + h * n);
      occ += (h - d) * sca;
      sca *= 0.95;
    }
    return clamp(1.0 - 3.0 * occ, 0.0, 1.0);
  }

  vec2 raymarch(vec3 ro, vec3 rd) {
    float d0 = 0.0;
    for (int i = 0; i < MAX_STEPS; i++) {
      vec3 p = ro + rd * d0;
      float ds = scene(p);
      d0 += ds;
      if (ds < SURF_DIST || d0 > MAX_DIST) break;
    }
    return vec2(d0, 0.0);
  }

  void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * uResolution.xy) / uResolution.y;
    float mTheta = (uMouse.x - 0.5) * 0.5;
    float mPhi = (uMouse.y - 0.5) * 0.3;
    vec3 ro = vec3(0.0, 0.0, -4.0);
    ro.yz *= mat2(cos(mPhi), sin(mPhi), -sin(mPhi), cos(mPhi));
    ro.xz *= mat2(cos(mTheta), sin(mTheta), -sin(mTheta), cos(mTheta));
    vec3 rd = normalize(vec3(uv.x, uv.y, 1.0));
    vec2 d = raymarch(ro, rd);

    // Dark background
    vec3 col = vec3(0.031, 0.035, 0.055);

    if (d.x < MAX_DIST) {
      vec3 p = ro + rd * d.x;
      vec3 n = getNormal(p);
      vec3 lightDir = normalize(vec3(1.0, 2.0, -1.0));
      float diff = max(dot(n, lightDir), 0.0);
      float amb = 0.5 + 0.5 * n.y;
      float shadow = softShadow(p, lightDir, 0.1, 5.0, 8.0);
      float ao = calcAO(p, n);

      // Dark blob color with blue-gray tone
      vec3 blobCol = vec3(0.08, 0.09, 0.14);
      // Blue edge tint
      vec3 edgeCol = vec3(0.15, 0.20, 0.35);
      float fresnel = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
      col = mix(blobCol, edgeCol, fresnel * 0.5);
      col *= (diff * shadow + amb * 0.3) * ao;
      // Subtle blue inner glow
      col += vec3(0.10, 0.14, 0.22) * pow(fresnel, 2.0) * 0.15;
    }

    // Fog blends to dark background
    col = mix(col, vec3(0.031, 0.035, 0.055), 1.0 - exp(-0.08 * d.x * d.x));
    // Tone mapping
    col = col * (2.51 * col + 0.03) / (col * (2.43 * col + 0.59) + 0.14);
    gl_FragColor = vec4(col, 1.0);
  }
`;

export default function BackgroundCanvas() {
  const mountRef = useRef<HTMLDivElement>(null);
  const mouseRef = useRef({ x: 0.5, y: 0.5 });
  const targetMouseRef = useRef({ x: 0.5, y: 0.5 });

  useEffect(() => {
    if (!mountRef.current) return;
    const container = mountRef.current;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });

    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.position = 'fixed';
    renderer.domElement.style.top = '0';
    renderer.domElement.style.left = '0';
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.zIndex = '0';
    container.appendChild(renderer.domElement);

    const blobMaterial = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      transparent: true,
      uniforms: {
        uTime: { value: 0.0 },
        uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
        uMouse: { value: new THREE.Vector2(0.5, 0.5) },
      },
      side: THREE.DoubleSide,
    });

    const blobGeometry = new THREE.PlaneGeometry(2, 2);
    const blobMesh = new THREE.Mesh(blobGeometry, blobMaterial);
    scene.add(blobMesh);

    // Trajectory lines
    const lineGroup = new THREE.Group();
    scene.add(lineGroup);
    const lineCount = 6;
    const lines: { mesh: THREE.Line; speed: number; offset: number; axis: THREE.Vector3 }[] = [];

    for (let i = 0; i < lineCount; i++) {
      const points: THREE.Vector3[] = [];
      for (let j = 0; j < 64; j++) {
        const t = j / 64;
        const angle = t * Math.PI * 4 + (i * Math.PI * 2) / lineCount;
        const radius = 2.8 + Math.sin(t * Math.PI * 3) * 0.4;
        points.push(new THREE.Vector3(
          Math.cos(angle) * radius,
          Math.sin(angle) * radius * 0.6,
          Math.sin(angle) * radius
        ));
      }
      const curve = new THREE.CatmullRomCurve3(points);
      const curvePoints = curve.getPoints(128);
      const geometry = new THREE.BufferGeometry().setFromPoints(curvePoints);
      const material = new THREE.LineBasicMaterial({
        color: new (THREE.Color as any)(0.25, 0.35, 0.55),
        transparent: true,
        opacity: 0.12,
        depthWrite: false,
      });
      const mesh = new THREE.Line(geometry, material);
      lineGroup.add(mesh);
      lines.push({
        mesh,
        speed: 0.1 + Math.random() * 0.2,
        offset: Math.random() * 100,
        axis: new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize(),
      });
    }

    const handleMouseMove = (e: MouseEvent) => {
      targetMouseRef.current.x = e.clientX / window.innerWidth;
      targetMouseRef.current.y = e.clientY / window.innerHeight;
    };
    window.addEventListener('mousemove', handleMouseMove);

    const handleResize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      blobMaterial.uniforms.uResolution.value.set(w, h);
    };
    window.addEventListener('resize', handleResize);

    let animId: number;
    const animate = (time: number) => {
      const t = time * 0.001;
      blobMaterial.uniforms.uTime.value = t;

      mouseRef.current.x += (targetMouseRef.current.x - mouseRef.current.x) * 0.08;
      mouseRef.current.y += (targetMouseRef.current.y - mouseRef.current.y) * 0.08;
      blobMaterial.uniforms.uMouse.value.set(mouseRef.current.x, mouseRef.current.y);

      for (let i = 0; i < lines.length; i++) {
        const { mesh, speed, offset, axis } = lines[i];
        mesh.rotation.x = t * 0.0001 * speed * 1000 + offset;
        mesh.rotation.y = t * 0.0002 * speed * 1000 + offset;
        mesh.rotateOnAxis(axis, 0.001);
      }

      renderer.render(scene, camera);
      animId = requestAnimationFrame(animate);
    };
    animId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      renderer.dispose();
      blobMaterial.dispose();
      blobGeometry.dispose();
      lines.forEach(({ mesh }) => {
        mesh.geometry.dispose();
        (mesh.material as any).dispose();
      });
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className="fixed inset-0"
      style={{ zIndex: 0, background: '#08090e' }}
      aria-hidden="true"
    />
  );
}

"use client";

import * as THREE from "three";
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls, Stars, useTexture } from "@react-three/drei";
import { latLonToVector3, latencyColor } from "@/lib/geo";
import { formatLocation, formatIsp } from "@/lib/geolocation";
import type { TraceHop } from "@/lib/types";
import { useTraceStore } from "@/store/traceStore";

const EARTH_RADIUS = 1;
const MARKER_RADIUS = EARTH_RADIUS + 0.012;

function greatCirclePoints(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
  segments = 64,
  altitude = 0.06,
): THREE.Vector3[] {
  const v1 = new THREE.Vector3(...latLonToVector3(lat1, lon1, 1));
  const v2 = new THREE.Vector3(...latLonToVector3(lat2, lon2, 1));
  const angle = v1.angleTo(v2);
  const points: THREE.Vector3[] = [];
  for (let i = 0; i <= segments; i++) {
    const t = i / segments;
    const sinTotal = Math.sin(angle);
    let point: THREE.Vector3;
    if (sinTotal < 1e-6) {
      point = v1.clone();
    } else {
      const a = Math.sin((1 - t) * angle) / sinTotal;
      const b = Math.sin(t * angle) / sinTotal;
      point = v1
        .clone()
        .multiplyScalar(a)
        .add(v2.clone().multiplyScalar(b));
    }
    point.normalize().multiplyScalar(EARTH_RADIUS + altitude * Math.sin(Math.PI * t));
    points.push(point);
  }
  return points;
}

function Earth() {
  const [dayMap, bumpMap] = useTexture([
    "https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg",
    "https://unpkg.com/three-globe/example/img/earth-topology.png",
  ]);
  const ref = useRef<THREE.Mesh>(null);
  const autoRotate = useTraceStore((s) => s.autoRotate);

  useFrame((_, delta) => {
    if (ref.current && autoRotate) ref.current.rotation.y += delta * 0.08;
  });

  return (
    <mesh ref={ref}>
      <sphereGeometry args={[EARTH_RADIUS, 64, 64]} />
      <meshStandardMaterial
        map={dayMap}
        bumpMap={bumpMap}
        bumpScale={0.04}
        roughness={0.85}
        metalness={0.05}
      />
    </mesh>
  );
}

function Atmosphere() {
  return (
    <mesh scale={1.015}>
      <sphereGeometry args={[EARTH_RADIUS, 64, 64]} />
      <meshBasicMaterial
        color="#4fd1ff"
        transparent
        opacity={0.08}
        side={THREE.BackSide}
      />
    </mesh>
  );
}

function RouteArc({
  from,
  to,
  color,
  index,
}: {
  from: TraceHop;
  to: TraceHop;
  color: string;
  index: number;
}) {
  const lineRef = useRef<THREE.Group>(null);
  const pulseRef = useRef<THREE.Mesh>(null);
  const points = useMemo(() => {
    if (!from.geo || !to.geo) return [];
    return greatCirclePoints(
      from.geo.lat,
      from.geo.lon,
      to.geo.lat,
      to.geo.lon,
    );
  }, [from, to]);

  useFrame((state) => {
    if (points.length < 2 || !pulseRef.current) return;
    const t = (state.clock.elapsedTime * 0.35 + index * 0.2) % 1;
    const idx = Math.floor(t * (points.length - 1));
    const frac = t * (points.length - 1) - idx;
    const a = points[idx];
    const b = points[Math.min(idx + 1, points.length - 1)];
    pulseRef.current.position.lerpVectors(a, b, frac);
  });

  if (points.length < 2) return null;

  return (
    <group ref={lineRef}>
      <Line points={points} color={color} lineWidth={1.5} transparent opacity={0.9} />
      <mesh ref={pulseRef}>
        <sphereGeometry args={[0.008, 8, 8]} />
        <meshBasicMaterial color="#ffffff" />
      </mesh>
      <mesh>
        <tubeGeometry
          args={[
            new THREE.CatmullRomCurve3(points),
            64,
            0.003,
            8,
            false,
          ]}
        />
        <meshBasicMaterial color={color} transparent opacity={0.35} />
      </mesh>
    </group>
  );
}

function HopMarker({ hop }: { hop: TraceHop }) {
  const selectedHop = useTraceStore((s) => s.selectedHop);
  const setSelectedHop = useTraceStore((s) => s.setSelectedHop);
  const [x, y, z] = latLonToVector3(hop.geo!.lat, hop.geo!.lon, MARKER_RADIUS);
  const active = selectedHop === hop.hop;
  const color = latencyColor(hop.avgMs);

  return (
    <group position={[x, y, z]}>
      <mesh
        onClick={(e) => {
          e.stopPropagation();
          setSelectedHop(hop.hop);
        }}
        onPointerOver={() => document.body.style.cursor = "pointer"}
        onPointerOut={() => document.body.style.cursor = "default"}
      >
        <sphereGeometry args={[active ? 0.022 : 0.015, 16, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={active ? 1.2 : 0.6}
        />
      </mesh>
      {active && (
        <mesh>
          <ringGeometry args={[0.028, 0.034, 32]} />
          <meshBasicMaterial color={color} transparent opacity={0.7} side={THREE.DoubleSide} />
        </mesh>
      )}
      <Html distanceFactor={1.8} style={{ pointerEvents: "none" }}>
        <div className="w-max max-w-[200px] rounded-lg border border-white/20 bg-black/80 px-2 py-1 text-[10px] text-white opacity-0 transition group-hover:opacity-100">
          Hop {hop.hop} · {hop.avgMs ?? "—"} ms
        </div>
      </Html>
    </group>
  );
}

function CameraRig() {
  const selectedHop = useTraceStore((s) => s.selectedHop);
  const result = useTraceStore((s) => s.result);
  const controlsRef = useRef<{ target: THREE.Vector3; update: () => void } | null>(null);
  const desired = useRef(new THREE.Vector3(0, 0, 0));

  useFrame((state, delta) => {
    const hop = result?.hops.find((h) => h.hop === selectedHop && h.geo);
    if (hop?.geo) {
      const [x, y, z] = latLonToVector3(hop.geo.lat, hop.geo.lon, 0);
      desired.current.set(x, y, z);
    } else {
      desired.current.set(0, 0, 0);
    }
    state.camera.position.lerp(
      new THREE.Vector3(
        desired.current.x * 0.3 + 0,
        desired.current.y * 0.3 + 0.2,
        2.4,
      ),
      1 - Math.exp(-delta * 2),
    );
    if (controlsRef.current) {
      controlsRef.current.target.lerp(desired.current, 1 - Math.exp(-delta * 3));
      controlsRef.current.update();
    }
  });

  return (
    <OrbitControls
      ref={controlsRef as never}
      enablePan={false}
      minDistance={1.6}
      maxDistance={5}
      autoRotate={false}
    />
  );
}

export function EarthScene() {
  const result = useTraceStore((s) => s.result);
  const hops = (result?.hops ?? []).filter((h) => h.geo && h.geo.lat != null);

  const segments = useMemo(() => {
    const out: { from: TraceHop; to: TraceHop; color: string; index: number }[] = [];
    for (let i = 0; i < hops.length - 1; i++) {
      out.push({
        from: hops[i],
        to: hops[i + 1],
        color: latencyColor(hops[i + 1].avgMs),
        index: i,
      });
    }
    return out;
  }, [hops]);

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight position={[5, 2, 5]} intensity={1.4} />
      <pointLight position={[-4, -2, -3]} intensity={0.4} color="#4fd1ff" />
      <Stars radius={80} depth={40} count={4000} factor={3} fade speed={0.5} />
      <Earth />
      <Atmosphere />
      {segments.map((seg) => (
        <RouteArc key={`${seg.from.hop}-${seg.to.hop}`} {...seg} />
      ))}
      {hops.map((hop) => (
        <HopMarker key={hop.hop} hop={hop} />
      ))}
      <CameraRig />
    </>
  );
}

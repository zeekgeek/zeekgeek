"use client";

import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { EarthScene } from "./globe/EarthScene";

export function Globe() {
  return (
    <div className="absolute inset-0 bg-[#020617]">
      <Canvas
        camera={{ position: [0, 0, 2.8], fov: 45, near: 0.1, far: 100 }}
        gl={{ antialias: true, alpha: false }}
        dpr={[1, 2]}
      >
        <color attach="background" args={["#020617"]} />
        <Suspense fallback={null}>
          <EarthScene />
        </Suspense>
      </Canvas>
    </div>
  );
}

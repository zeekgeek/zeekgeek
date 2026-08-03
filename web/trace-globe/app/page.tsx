"use client";

import dynamic from "next/dynamic";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import { StatusBar } from "@/components/StatusBar";
import { HopTooltip } from "@/components/HopTooltip";

const Globe = dynamic(() => import("@/components/Globe").then((m) => m.Globe), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 flex items-center justify-center bg-[#020617] text-slate-500">
      Loading 3D globe…
    </div>
  ),
});

export default function HomePage() {
  return (
    <main className="relative h-screen w-screen overflow-hidden">
      <Globe />

      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col gap-4 p-4 md:p-6">
        <TopBar />

        <div className="flex min-h-0 flex-1 gap-4">
          <Sidebar />
          <div className="flex-1" />
        </div>

        <StatusBar />
      </div>

      <HopTooltip />
    </main>
  );
}

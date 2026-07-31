# Trace Globe

Full-stack **Next.js** app that visualizes traceroute paths on an interactive **3D Earth globe** (React Three Fiber).

## Stack

- **Frontend:** Next.js 15 (App Router), React, Three.js / React Three Fiber, `@react-three/drei`, Tailwind CSS, Lucide React, Framer Motion, Zustand
- **Backend:** Next.js Route Handler `POST /api/trace`

## Quick start

```bash
cd web/trace-globe
npm install
npm run dev
```

Open **http://127.0.0.1:3000**

## Features

- Search bar + **Trace Route** button with presets (`github.com`, `google.com`, `bbc.co.uk`, `tokyo.ac.jp`, …)
- Collapsible **hop sidebar**: hop #, IP, hostname, city/country, latency, ISP/ASN, packet loss %
- **Status bar**: hops, average latency, total route distance (km), trace status
- **3D globe**: textured Earth, atmosphere, stars, latency-colored arcs (green / yellow / red), animated packet pulses
- **Camera** flies toward selected hops; click sidebar rows to focus
- Private IPs (`192.168.x.x`, `10.x.x.x`) mapped to your public origin or labeled *Internal Network*

## API

```bash
curl -X POST http://127.0.0.1:3000/api/trace \
  -H 'Content-Type: application/json' \
  -d '{"target":"google.com"}'
```

On cloud VMs without `traceroute`/`tracepath`, the API returns **realistic mock routes** with geolocation.

## Project layout

```
web/trace-globe/
├── app/
│   ├── page.tsx              # Dashboard shell
│   ├── layout.tsx
│   └── api/trace/route.ts    # Traceroute + GeoIP
├── components/
│   ├── Globe.tsx
│   ├── TopBar.tsx
│   ├── Sidebar.tsx
│   ├── StatusBar.tsx
│   ├── HopTooltip.tsx
│   └── globe/EarthScene.tsx
├── lib/
│   ├── traceroute.ts
│   ├── geolocation.ts
│   ├── traceEngine.ts
│   └── geo.ts
└── store/traceStore.ts
```

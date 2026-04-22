# idas-mobile

Expo mobile companion for `idas-scene-ai`. Triage camera streams and alerts
from your phone.

## Stack

- Expo SDK 52 + Expo Router v4 (file-based routing)
- React Native 0.76 (new architecture on)
- NativeWind v4 (Tailwind for RN)
- TanStack Query (server state) + Zustand + AsyncStorage (settings)
- Axios + Zod (typed, validated API client)

## Screens

| Route              | Purpose                                      |
|--------------------|----------------------------------------------|
| `/(tabs)/`         | Streams list (status, fps, active rules)     |
| `/(tabs)/alerts`   | Alert inbox (filter by stream, severity)     |
| `/(tabs)/settings` | API base URL + bearer token + health check   |
| `/alerts/[id]`     | Alert detail (frame, detections, reasoning)  |

## Run

```bash
cd mobile
pnpm install          # or npm install / yarn
pnpm start            # Expo dev server
pnpm android          # launch on Android emulator
pnpm ios              # launch on iOS simulator (macOS only)
```

First launch opens the Settings tab — set the API base URL:

- Android emulator → `http://10.0.2.2:8000`
- iOS simulator   → `http://localhost:8000`
- Physical device → your LAN IP, e.g. `http://192.168.1.20:8000`

## Build

```bash
pnpm dlx eas-cli build --platform android --profile preview
pnpm dlx eas-cli build --platform ios --profile preview
```

Requires an Expo account (`eas login`).

## Backend contract

The client mirrors `src/idas/api/` routes:

- `GET  /streams`           — list
- `GET  /streams/{id}`      — one
- `GET  /alerts`            — filter by `stream_id`, `severity`, `limit`
- `GET  /alerts/{id}`       — one
- `POST /detect`            — multipart frame upload
- `GET  /healthz`           — version check

Types live in `lib/types.ts` as Zod schemas. Update them when the backend
Pydantic models change.

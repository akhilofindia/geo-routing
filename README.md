# Route desk

A React and Django app that helps a truck driver compare routes by the weather they will meet, the weight they are hauling, and how long the trip takes.

The driver enters an origin, a destination, a departure time, and a load weight. The app asks a truck routing service for up to three paths, samples the forecast at the estimated arrival time every 10, 25, or 50 miles, and recommends the route with the least dangerous weather. A map draws each path in the color of its risk, and a slider plays a 0–48 hour forecast along the corridor without calling the network again.

## Run it locally

Use two terminals from the project root.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python backend\manage.py runserver
```

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. The Vite dev server proxies `/api` to Django on port 8000.

On macOS or Linux, use `.venv/bin/python` instead of `.venv\Scripts\python`.

Tests, from `backend`:

```bash
..\.venv\Scripts\python -m pytest
```

Docker serves the built frontend and the API on one port:

```bash
docker build -t truck-route-planner .
docker run -p 8000:8000 truck-route-planner
```

No API keys are required.

## How a trip is scored

Weather at each checkpoint is the forecast hour that contains the truck’s estimated arrival. Arrival time follows the router’s maneuver times, so a slow stretch is not treated as the same speed as the rest of the trip.

Wind, rain, and snow are classified separately. The checkpoint takes the worst of the three.

| Condition | Low | Moderate | High | Severe | No travel |
| --- | --- | --- | --- | --- | --- |
| Wind | < 25 mph | 25–34 | 35–44 | 45–54 | ≥ 55 mph |
| Rain | < 0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | > 1.00 |
| Snow | < 0.5 in/hr | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | > 3.0 |

A value on the line between two bands takes the higher band. Rain at 1.00 in/hr and snow at 3.0 in/hr are still severe.

Load weight changes wind only:

- 55 mph or more is no-travel for any load.
- 45–54 mph with more than 30,000 lb is no-travel.
- 35–44 mph with more than 40,000 lb is severe.

Each stretch between checkpoints counts toward the worse of its two ends. Unknown checkpoints, used when the arrival is outside the forecast, are left out of the mile totals.

Average risk is the distance-weighted score: Low 1, Moderate 2, High 3, Severe 4, No travel 5.

The recommended route is chosen in this order:

1. Fewest no-travel miles
2. Fewest severe miles
3. Fewest high-risk miles
4. Lowest average risk
5. Shortest travel time

No-travel miles are first so a banned stretch cannot outrank a route that is only severe.

## Services

- Map: Esri World Street Map tiles. No key. OpenStreetMap’s volunteer tile servers block this app, and Carto’s tiles now require a key.
- Places: [Open-Meteo Geocoding](https://open-meteo.com/en/docs/geocoding-api)
- Truck routes: the public [Valhalla](https://valhalla.openstreetmap.de/) server, with the load converted to metric tons. It is a fair-use demo and generally limits a route to about 1,500 km. If it is unavailable, driving routes come from the public OSRM server and are labeled as not truck-restricted.
- Weather: [Open-Meteo](https://open-meteo.com/en/docs) hourly wind, rain, showers, and snowfall. Liquid rain is rain plus showers. Snow is not counted as rain.

When the truck router returns fewer than three distinct paths, the app also requests a toll-avoiding route, a lower-highway route, and, if needed, a route offset from the middle of the fastest path.

The heatmap is a corridor sample about every 20 miles, plus points about 12 miles to either side. All 49 hours are returned with the trip. Dragging the slider only changes which hour the canvas draws.

## API

`GET /api/geocode?q=Dallas`

`GET /api/health`

`POST /api/plan`

```json
{
  "origin": "Dallas, Texas",
  "destination": {"label": "Oklahoma City, Oklahoma", "latitude": 35.4676, "longitude": -97.5164},
  "departure": "2026-10-10T15:00:00-05:00",
  "load_lb": 42000,
  "sample_miles": 25
}
```

`sample_miles` must be 10, 25, or 50. `departure` must include a time zone. Origin and destination can be a place name or coordinates from the geocoder.

## Hosting

[render.yaml](render.yaml) is a Render Docker web service. The image builds the frontend, then serves it and the API with gunicorn. Render sets `PORT`. The image reads that port. After the repo is on GitHub, create a Render service from this blueprint.

The public routing and weather servers can be slow or rate-limited. The plan request waits on them, so the gunicorn timeout is 120 seconds.

## Publish

This folder is the app. Publishing needs a GitHub login and a Render account, which are not set up in this environment.

```bash
git init
git add .
git commit -m "Add a truck route planner that ranks weather risk against travel time."
gh repo create truck-route-planner --public --source=. --remote=origin --push
```

In Render, create a new Blueprint and point it at the repo. It reads [render.yaml](render.yaml). The first request after a cold start can take a minute while the routing and weather services answer.

## Loom walkthrough

Record a 5–10 minute Loom while you use the running app. Suggested shots:

1. **0:00** Say what the page does: three truck routes, scored by weather at the truck’s arrival time, load, and trip length.
2. **0:40** Enter Dallas to Oklahoma City, a departure a few hours ahead, 42,000 lb, and a 25 mile sample. Submit.
3. **2:00** Show the three colored paths, the checkpoint dots, and the recommendation sentence. Point at no-travel, severe, and high miles on the cards.
4. **3:30** Open a checkpoint. Read wind, rain, snow, the level, and the ETA.
5. **4:30** Click another route and show that its line and checkpoints come forward.
6. **5:20** Drag the forecast slider from hour 0 to 48. Mention that the heatmap was already downloaded, so the slider does not send a new request. The colors follow the same legend as the route.
7. **6:40** Change the sample to 10 miles, or raise the load, and run it again. Explain that 45 mph wind above 30,000 lb is no-travel, and 35 mph wind above 40,000 lb is severe.
8. **8:00** Briefly show `backend/planner/risk.py` and `backend/planner/scoring.py` for the bands and the sort order, then `frontend/src/map/HeatmapLayer.ts` for the canvas redraw.
9. **9:00** Mention the Valhalla distance limit and that a missing truck router falls back to ordinary driving routes.

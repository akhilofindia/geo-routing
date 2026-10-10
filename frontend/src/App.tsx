import { useEffect, useRef, useState } from "react";

import { planTrip } from "./api";
import { PlannerForm } from "./components/PlannerForm";
import { RouteList } from "./components/RouteList";
import { MapView } from "./components/MapView";
import { formatClock, formatEtaShort, formatHourOffset, localInputToIso } from "./format";
import type { CorridorHeatmap } from "./map/HeatmapLayer";
import { LEVEL_LABEL, RISK_COLOR } from "./riskColors";
import type { Level, PlanResponse } from "./types";

function selectedCheckpoints(result: PlanResponse, selectedId: string | null): number {
  const route = result.routes.find((item) => item.id === selectedId) ?? result.routes[0];
  return route?.checkpoints.length ?? 0;
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  return <span className="clock">{formatClock(now)}</span>;
}

export function App() {
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planId, setPlanId] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = window.localStorage.getItem("route-desk-theme");
    return saved === "light" ? "light" : "dark";
  });
  const layerRef = useRef<CorridorHeatmap | null>(null);
  const offsetRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const sliderRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<PlanResponse | null>(null);
  const paintRef = useRef<(hour: number) => void>(() => {});
  resultRef.current = result;

  paintRef.current = (hour: number) => {
    layerRef.current?.setHour(hour);
    if (sliderRef.current) sliderRef.current.value = String(hour);
    const current = resultRef.current;
    const stamp = current?.heatmap.hours[hour];
    if (offsetRef.current) offsetRef.current.textContent = formatHourOffset(hour);
    if (detailRef.current) {
      detailRef.current.textContent = stamp
        ? `${formatClock(new Date(stamp))} · weather heat on the corridor`
        : "Weather heat on the corridor";
    }
  };

  useEffect(() => {
    if (!playing || !result) return;
    const timer = window.setInterval(() => {
      const slider = sliderRef.current;
      const max = result.heatmap.hours.length - 1;
      const next = Math.min(max, Number(slider?.value ?? 0) + 1);
      paintRef.current(next);
      if (next >= max) setPlaying(false);
    }, 700);
    return () => window.clearInterval(timer);
  }, [playing, result]);

  useEffect(() => {
    paintRef.current(0);
  }, [planId]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("route-desk-theme", theme);
  }, [theme]);

  async function onSubmit(body: {
    origin: PlanResponse["origin"] | string;
    destination: PlanResponse["destination"] | string;
    departure: string;
    loadLb: number;
    sampleMiles: number;
  }) {
    setLoading(true);
    setError(null);
    try {
      const plan = await planTrip({
        origin: body.origin,
        destination: body.destination,
        departure: localInputToIso(body.departure),
        load_lb: body.loadLb,
        sample_miles: body.sampleMiles,
      });
      setPlaying(false);
      setResult(plan);
      setSelectedId(plan.recommendation.route_id);
      setPlanId((value) => value + 1);
      if (window.matchMedia("(max-width: 860px)").matches) {
        window.setTimeout(() => {
          document.querySelector(".stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 50);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Could not plan that trip.");
    } finally {
      setLoading(false);
    }
  }

  const maxHour = result ? Math.max(0, result.heatmap.hours.length - 1) : 48;

  return (
    <div className="shell" data-theme={theme}>
      <aside>
        <div className="desk-top">
        <header className="brand">
          <div className="brand-mark">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 6h11v10H2zM13 9h4l4 4v3h-8" />
              <circle cx="7" cy="17.5" r="1.8" />
              <circle cx="17" cy="17.5" r="1.8" />
            </svg>
            <span>Route desk</span>
          </div>
          <Clock />
        </header>
        <div className="theme-switch" role="group" aria-label="Color theme">
          <button type="button" aria-pressed={theme === "light"} onClick={() => setTheme("light")}>
            Light
          </button>
          <button type="button" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>
            Dark
          </button>
        </div>
        <PlannerForm loading={loading} onSubmit={onSubmit} />
        {error && <p className="error">{error}</p>}
        </div>
        {result && (
          <RouteList
            result={result}
            selectedId={selectedId ?? result.recommendation.route_id}
            onSelect={(id) => {
              setSelectedId(id);
              if (window.matchMedia("(max-width: 860px)").matches) {
                document.querySelector(".stage")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
              }
            }}
          />
        )}
        <p className="hint">Above 30,000 lb, 45 mph wind becomes No Travel. Above 40,000 lb, 35 mph wind becomes Severe.</p>
      </aside>
      <section className="stage">
        <MapView
          routes={result?.routes ?? []}
          heatPoints={result?.heatmap.points ?? []}
          selectedId={selectedId}
          planId={planId}
          onSelect={setSelectedId}
          layerRef={layerRef}
          theme={theme}
        />
        <div className="legend-stack">
          <div className="legend">
            {(["low", "moderate", "high", "severe", "no_travel"] as Level[]).map((level) => (
              <span key={level}>
                <i style={{ background: RISK_COLOR[level] }} />
                {LEVEL_LABEL[level]}
              </span>
            ))}
          </div>
          {result && (
            <div className="legend map-chip">
              {selectedCheckpoints(result, selectedId)} checkpoints · every {result.sample_miles} mi
            </div>
          )}
        </div>
        {!result && !loading && (
          <div className="empty">
            <p>Three truck routes, scored by the weather the truck will actually meet.</p>
          </div>
        )}
        {loading && <div className="pending">Sampling the forecast along each route…</div>}
        {result && (
          <div className="forecast">
            <div className="forecast-row">
              <button
                type="button"
                className="play"
                aria-label={playing ? "Pause forecast" : "Play forecast"}
                onClick={() => setPlaying((value) => !value)}
              >
                {playing ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                    <path d="M7 4l13 8-13 8z" />
                  </svg>
                )}
              </button>
              <div>
                <div className="forecast-offset" ref={offsetRef}>
                  +00 h
                </div>
                <div className="forecast-detail" ref={detailRef}>
                  Weather heat on the corridor
                </div>
              </div>
              <span className="heat-note">Heat: wind + rain + snow</span>
            </div>
            <input
              key={planId}
              ref={sliderRef}
              type="range"
              min={0}
              max={maxHour}
              defaultValue={0}
              aria-label="Forecast hour, 0 to 48"
              onInput={(event) => {
                setPlaying(false);
                paintRef.current(Number(event.currentTarget.value));
              }}
            />
            <div className="ticks">
              {[0, 12, 24, 36, 48]
                .filter((hour) => hour <= maxHour)
                .map((hour) => (
                  <span key={hour}>{result.heatmap.hours[hour] ? formatEtaShort(result.heatmap.hours[hour]) : `+${hour} h`}</span>
                ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

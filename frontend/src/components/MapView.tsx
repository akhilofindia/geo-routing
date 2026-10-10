import { useEffect, type MutableRefObject } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, ZoomControl, useMap } from "react-leaflet";

import { formatMiles, formatWhen } from "../format";
import { CorridorHeatmap } from "../map/HeatmapLayer";
import { LEVEL_LABEL, RISK_COLOR, ROUTE_COLORS } from "../riskColors";
import type { HeatPoint, RouteOption } from "../types";

interface Props {
  routes: RouteOption[];
  heatPoints: HeatPoint[];
  selectedId: string | null;
  planId: number;
  onSelect: (id: string) => void;
  layerRef: MutableRefObject<CorridorHeatmap | null>;
  theme: "light" | "dark";
}

export function MapView({ routes, heatPoints, selectedId, planId, onSelect, layerRef, theme }: Props) {
  const dark = theme === "dark";
  return (
    <MapContainer
      center={[39.5, -96.5]}
      zoom={4}
      zoomControl={false}
      preferCanvas
      style={{ height: "100%", width: "100%", background: dark ? "#0E1620" : "#e7e1d6" }}
    >
      {dark ? (
        <>
          <TileLayer
            attribution='Tiles &copy; Esri'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          />
          <TileLayer
            attribution='Labels &copy; Esri'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
          />
        </>
      ) : (
        <TileLayer
          attribution='Tiles &copy; Esri'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        />
      )}
      <ZoomControl position="topright" />
      <MapResize />
      {heatPoints.length > 0 && <HeatmapOverlay points={heatPoints} layerRef={layerRef} />}
      {routes.length > 0 && <FitToRoutes routes={routes} planId={planId} />}
      {routes.map((route, index) =>
        route.id === selectedId ? null : (
          <RoutePaths
            key={route.id}
            route={route}
            color={ROUTE_COLORS[index % ROUTE_COLORS.length]}
            dash={index === 1 ? "12 7" : "2 8"}
            casing={dark ? "#071018" : "#fffdf8"}
            markerStroke={dark ? "#0E1620" : "#fffdf8"}
            selected={false}
            onSelect={onSelect}
          />
        ),
      )}
      {routes.map((route, index) =>
        route.id === selectedId ? (
          <RoutePaths
            key={route.id}
            route={route}
            color={ROUTE_COLORS[index % ROUTE_COLORS.length]}
            dash={undefined}
            casing={dark ? "#071018" : "#fffdf8"}
            markerStroke={dark ? "#0E1620" : "#fffdf8"}
            selected
            onSelect={onSelect}
          />
        ) : null,
      )}
    </MapContainer>
  );
}

function MapResize() {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);
  return null;
}

function HeatmapOverlay({
  points,
  layerRef,
}: {
  points: HeatPoint[];
  layerRef: MutableRefObject<CorridorHeatmap | null>;
}) {
  const map = useMap();
  useEffect(() => {
    const layer = new CorridorHeatmap(points);
    layer.addTo(map);
    layerRef.current = layer;
    return () => {
      layer.remove();
      if (layerRef.current === layer) layerRef.current = null;
    };
  }, [map, points, layerRef]);
  return null;
}

function FitToRoutes({ routes, planId }: { routes: RouteOption[]; planId: number }) {
  const map = useMap();
  useEffect(() => {
    let minLat = 90;
    let maxLat = -90;
    let minLon = 180;
    let maxLon = -180;
    let found = false;
    for (const route of routes) {
      for (const checkpoint of route.checkpoints) {
        found = true;
        minLat = Math.min(minLat, checkpoint.lat);
        maxLat = Math.max(maxLat, checkpoint.lat);
        minLon = Math.min(minLon, checkpoint.lon);
        maxLon = Math.max(maxLon, checkpoint.lon);
      }
    }
    if (!found) return;
    map.fitBounds(
      [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      { padding: [48, 48] },
    );
  }, [map, routes, planId]);
  return null;
}

function RoutePaths({
  route,
  color,
  dash,
  casing,
  markerStroke,
  selected,
  onSelect,
}: {
  route: RouteOption;
  color: string;
  dash?: string;
  casing: string;
  markerStroke: string;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const positions = route.segments.flatMap((segment) => segment.geometry);
  const choose = () => onSelect(route.id);
  return (
    <>
      {positions.length >= 2 && (
        <Polyline
          positions={positions}
          pathOptions={{ color: casing, weight: selected ? 10 : 6, opacity: 0.9 }}
          eventHandlers={{ click: choose }}
        />
      )}
      {positions.length >= 2 && (
        <Polyline
          positions={positions}
          pathOptions={{ color, weight: selected ? 6 : 3.5, opacity: 1, dashArray: dash }}
          eventHandlers={{ click: choose }}
        />
      )}
      {selected &&
        route.checkpoints.map((checkpoint) => (
        <CircleMarker
          key={`${route.id}-${checkpoint.mile}`}
          center={[checkpoint.lat, checkpoint.lon]}
          radius={5}
          pathOptions={{
            color: markerStroke,
            weight: 2,
            fillColor: RISK_COLOR[checkpoint.level],
            fillOpacity: 1,
          }}
          eventHandlers={{ click: choose }}
        >
          <Popup>
            <div className="popup">
              <strong>
                {route.label} · mile {formatMiles(checkpoint.mile)}
              </strong>
              <span>{formatWhen(checkpoint.eta)}</span>
              <em style={{ color: RISK_COLOR[checkpoint.level] }}>{LEVEL_LABEL[checkpoint.level]}</em>
              <ul>
                {checkpoint.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
              <p>
                Wind {reading(checkpoint.wind_mph, "mph")} · {LEVEL_LABEL[checkpoint.wind_level]}
                <br />
                Rain {reading(checkpoint.rain_in_hr, "in/hr")} · {LEVEL_LABEL[checkpoint.rain_level]}
                <br />
                Snow {reading(checkpoint.snow_in_hr, "in/hr")} · {LEVEL_LABEL[checkpoint.snow_level]}
              </p>
            </div>
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
}

function reading(value: number | null, unit: string): string {
  if (value === null) return "—";
  return `${value} ${unit}`;
}

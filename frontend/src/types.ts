export type Level = "low" | "moderate" | "high" | "severe" | "no_travel" | "unknown";

export interface Place {
  label: string;
  latitude: number;
  longitude: number;
}

export interface Checkpoint {
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  wind_mph: number | null;
  rain_in_hr: number | null;
  snow_in_hr: number | null;
  wind_level: Level;
  rain_level: Level;
  snow_level: Level;
  level: Level;
  reasons: string[];
}

export interface Segment {
  level: Level;
  miles: number;
  geometry: [number, number][];
}

export interface Summary {
  no_travel_mi: number;
  severe_mi: number;
  high_mi: number;
  moderate_mi: number;
  low_mi: number;
  unknown_mi: number;
  avg_risk: number | null;
}

export interface RouteOption {
  id: string;
  label: string;
  subtitle: string;
  truck_restricted: boolean;
  recommended: boolean;
  distance_mi: number;
  duration_min: number;
  summary: Summary;
  checkpoints: Checkpoint[];
  segments: Segment[];
}

export interface HeatPoint {
  lat: number;
  lon: number;
  levels: number[];
}

export interface PlanResponse {
  origin: Place;
  destination: Place;
  departure: string;
  load_lb: number;
  sample_miles: number;
  routes: RouteOption[];
  heatmap: {
    hours: string[];
    points: HeatPoint[];
  };
  recommendation: {
    route_id: string;
    explanation: string;
  };
  warnings: string[];
}

export interface PlanRequest {
  origin: Place | string;
  destination: Place | string;
  departure: string;
  load_lb: number;
  sample_miles: number;
}

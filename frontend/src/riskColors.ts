import type { Level } from "./types";

export const RISK_COLOR: Record<Level, string> = {
  low: "#3DDC97",
  moderate: "#F5D547",
  high: "#FF9A3C",
  severe: "#FF5A52",
  no_travel: "#B07CFF",
  unknown: "#7E8FA3",
};

export const LEVEL_LABEL: Record<Level, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  no_travel: "No travel",
  unknown: "Unknown",
};

export const ROUTE_COLORS = ["#5AA7FF", "#C7D2DF", "#7E8FA3"];

export const HEAT_STOPS: [number, number, number][] = [
  [61, 220, 151],
  [245, 213, 71],
  [255, 154, 60],
  [255, 90, 82],
  [176, 124, 255],
];

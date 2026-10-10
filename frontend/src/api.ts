import type { Place, PlanRequest, PlanResponse } from "./types";

export async function searchPlaces(query: string): Promise<Place[]> {
  const response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Place search failed.");
  }
  return data.results ?? [];
}

export async function planTrip(body: PlanRequest): Promise<PlanResponse> {
  const response = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: { error?: string } = {};
  try {
    data = await response.json();
  } catch {
    throw new Error("The planner returned an unreadable response.");
  }
  if (!response.ok) {
    throw new Error(data.error || "Could not plan that trip.");
  }
  return data as PlanResponse;
}

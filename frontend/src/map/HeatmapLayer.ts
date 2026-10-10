import L from "leaflet";

import { HEAT_STOPS } from "../riskColors";
import type { HeatPoint } from "../types";

const CORRIDOR_MILES = 18;
const MIN_RADIUS = 14;
const MAX_RADIUS = 46;

/**
 * Canvas corridor heatmap. The slider only changes `hour` and asks for one
 * redraw; React does not re-render the map while the thumb moves.
 * The canvas sits in its own pane, under the route lines. It is drawn in
 * container pixels from the current view origin so pan and zoom stay aligned.
 */
export class CorridorHeatmap extends L.Layer {
  private canvas: HTMLCanvasElement | null = null;
  private hour = 0;
  private frame = 0;
  private readonly points: HeatPoint[];

  constructor(points: HeatPoint[]) {
    super();
    this.points = points;
  }

  onAdd(map: L.Map): this {
    if (!map.getPane("corridor")) {
      const pane = map.createPane("corridor");
      pane.style.zIndex = "350";
      pane.style.pointerEvents = "none";
    }
    this.canvas = document.createElement("canvas");
    this.canvas.className = "corridor-heat";
    this.canvas.style.position = "absolute";
    this.canvas.style.pointerEvents = "none";
    map.getPane("corridor")?.appendChild(this.canvas);
    map.on("move zoom resize", this.schedule, this);
    this.schedule();
    return this;
  }

  onRemove(map: L.Map): this {
    map.off("move zoom resize", this.schedule, this);
    cancelAnimationFrame(this.frame);
    this.canvas?.remove();
    this.canvas = null;
    return this;
  }

  setHour(hour: number): void {
    this.hour = hour;
    this.schedule();
  }

  private schedule = (): void => {
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.draw());
  };

  private draw(): void {
    const map = this._map;
    const canvas = this.canvas;
    if (!map || !canvas) return;

    const size = map.getSize();
    const origin = map.containerPointToLayerPoint([0, 0]);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(size.x * dpr));
    canvas.height = Math.max(1, Math.floor(size.y * dpr));
    canvas.style.width = `${size.x}px`;
    canvas.style.height = `${size.y}px`;
    L.DomUtil.setPosition(canvas, origin);

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.x, size.y);

    const pad = MAX_RADIUS + 12;
    ctx.filter = "blur(7px)";
    for (const point of this.points) {
      const pixel = map.latLngToContainerPoint([point.lat, point.lon]);
      if (pixel.x < -pad || pixel.y < -pad || pixel.x > size.x + pad || pixel.y > size.y + pad) {
        continue;
      }
      const radius = ribbonRadius(map, point.lat);
      const [red, green, blue] = HEAT_STOPS[Math.max(0, Math.min(HEAT_STOPS.length - 1, point.levels[this.hour] ?? 0))];
      const gradient = ctx.createRadialGradient(pixel.x, pixel.y, 0, pixel.x, pixel.y, radius);
      gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, 0.62)`);
      gradient.addColorStop(0.55, `rgba(${red}, ${green}, ${blue}, 0.28)`);
      gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(pixel.x, pixel.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.filter = "none";
  }
}

function ribbonRadius(map: L.Map, lat: number): number {
  const metersPerPixel = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** map.getZoom();
  const pixels = (CORRIDOR_MILES * 1609.344) / metersPerPixel;
  return Math.max(MIN_RADIUS, Math.min(MAX_RADIUS, pixels));
}

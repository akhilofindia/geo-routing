import { formatDuration, formatDurationCompact, formatEtaShort, formatMiles } from "../format";
import { LEVEL_LABEL, RISK_COLOR, ROUTE_COLORS } from "../riskColors";
import type { PlanResponse, RouteOption, Summary } from "../types";

interface Props {
  result: PlanResponse;
  selectedId: string;
  onSelect: (id: string) => void;
}

export function RouteList({ result, selectedId, onSelect }: Props) {
  const recommended = result.routes.find((route) => route.id === result.recommendation.route_id) ?? result.routes[0];
  return (
    <div className="results">
      {recommended && (
        <section className="recommend">
          <div className="recommend-mark">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12l5 5 9-10" />
            </svg>
            Recommended
          </div>
          <div className="recommend-title">{recommended.label}</div>
          <div className="recommend-time">{formatDuration(recommended.duration_min)}</div>
          <p>{result.recommendation.explanation}</p>
        </section>
      )}
      {result.warnings.length > 0 && (
        <ul className="warnings">
          {result.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      <section className="cards">
        <div className="section-label">All routes</div>
        {result.routes.map((route, index) => (
          <RouteCard
            key={route.id}
            route={route}
            color={ROUTE_COLORS[index % ROUTE_COLORS.length]}
            selected={route.id === selectedId}
            onSelect={() => onSelect(route.id)}
          />
        ))}
      </section>
    </div>
  );
}

function RouteCard({
  route,
  color,
  selected,
  onSelect,
}: {
  route: RouteOption;
  color: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const arrival = route.checkpoints[route.checkpoints.length - 1];
  const summary = route.summary;
  return (
    <button type="button" className={selected ? "card selected" : "card"} aria-pressed={selected} onClick={onSelect}>
      <div className="card-top">
        <i className="swatch" style={{ background: color }} />
        <strong>{route.label}</strong>
        <span className="duration">{formatDurationCompact(route.duration_min)}</span>
      </div>
      <Mix summary={summary} />
      <div className="route-meta">
        <span>{Math.round(route.distance_mi).toLocaleString()} mi</span>
        <span>
          {formatMiles(summary.severe_mi)} sev · {formatMiles(summary.high_mi)} high
        </span>
        <span>ETA {arrival ? formatEtaShort(arrival.eta) : "—"}</span>
      </div>
      {!route.truck_restricted && <p className="flag">Not truck-restricted</p>}
      {summary.unknown_mi > 0 && <p className="flag">{formatMiles(summary.unknown_mi)} mi outside the forecast</p>}
    </button>
  );
}

function Mix({ summary }: { summary: Summary }) {
  const parts: [keyof typeof RISK_COLOR, number][] = [
    ["no_travel", summary.no_travel_mi],
    ["severe", summary.severe_mi],
    ["high", summary.high_mi],
    ["moderate", summary.moderate_mi],
    ["low", summary.low_mi],
    ["unknown", summary.unknown_mi],
  ];
  const total = parts.reduce((sum, part) => sum + part[1], 0);
  if (total <= 0) return null;
  return (
    <div className="mix" aria-hidden="true">
      {parts.map(([level, miles]) =>
        miles > 0 ? (
          <span
            key={level}
            style={{ width: `${(miles / total) * 100}%`, background: RISK_COLOR[level] }}
            title={`${LEVEL_LABEL[level]} ${formatMiles(miles)} mi`}
          />
        ) : null,
      )}
    </div>
  );
}

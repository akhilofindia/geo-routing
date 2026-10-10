import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { searchPlaces } from "../api";
import { defaultDeparture } from "../format";
import type { Place } from "../types";

interface Props {
  loading: boolean;
  onSubmit: (body: {
    origin: Place | string;
    destination: Place | string;
    departure: string;
    loadLb: number;
    sampleMiles: number;
  }) => void;
}

export function PlannerForm({ loading, onSubmit }: Props) {
  const [originText, setOriginText] = useState("");
  const [destinationText, setDestinationText] = useState("");
  const [originPlace, setOriginPlace] = useState<Place | null>(null);
  const [destinationPlace, setDestinationPlace] = useState<Place | null>(null);
  const [departure, setDeparture] = useState(defaultDeparture);
  const [loadLb, setLoadLb] = useState("35000");
  const [sampleMiles, setSampleMiles] = useState(25);

  function submit(event: FormEvent) {
    event.preventDefault();
    const load = Number(loadLb);
    if (!Number.isFinite(load)) return;
    onSubmit({
      origin: originPlace && originPlace.label === originText ? originPlace : originText.trim(),
      destination:
        destinationPlace && destinationPlace.label === destinationText ? destinationPlace : destinationText.trim(),
      departure,
      loadLb: load,
      sampleMiles,
    });
  }

  return (
    <form className="trip-form" onSubmit={submit}>
      <div className="place-row">
        <div className="place-rail" aria-hidden="true">
          <span className="rail-from" />
          <span className="rail-line" />
          <span className="rail-to" />
        </div>
        <div className="place-fields">
          <PlaceField
            label="From"
            value={originText}
            placeholder="Dallas, Texas"
            onText={(value) => {
              setOriginText(value);
              if (originPlace && originPlace.label !== value) setOriginPlace(null);
            }}
            onPick={(place) => {
              setOriginPlace(place);
              setOriginText(place.label);
            }}
          />
          <PlaceField
            label="To"
            value={destinationText}
            placeholder="California"
            onText={(value) => {
              setDestinationText(value);
              if (destinationPlace && destinationPlace.label !== value) setDestinationPlace(null);
            }}
            onPick={(place) => {
              setDestinationPlace(place);
              setDestinationText(place.label);
            }}
          />
        </div>
      </div>
      <div className="form-row">
        <label className="field">
          <span>Depart</span>
          <input type="datetime-local" value={departure} onChange={(event) => setDeparture(event.target.value)} required />
        </label>
        <label className="field load-field">
          <span>Load · lb</span>
          <input
            type="number"
            min={0}
            max={200000}
            step={500}
            value={loadLb}
            onChange={(event) => setLoadLb(event.target.value)}
            required
          />
        </label>
      </div>
      <fieldset className="interval">
        <legend>Sample</legend>
        <div className="segmented">
          {[10, 25, 50].map((miles) => (
            <label key={miles}>
              <input
                type="radio"
                name="sample"
                value={miles}
                checked={sampleMiles === miles}
                onChange={() => setSampleMiles(miles)}
              />
              <span>{miles} mi</span>
            </label>
          ))}
        </div>
      </fieldset>
      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Checking routes and weather…" : "Check routes and weather"}
      </button>
    </form>
  );
}

function PlaceField({
  label,
  value,
  placeholder,
  onText,
  onPick,
}: {
  label: string;
  value: string;
  placeholder: string;
  onText: (value: string) => void;
  onPick: (place: Place) => void;
}) {
  const listId = useId();
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const request = useRef(0);

  useEffect(() => {
    const query = value.trim();
    if (query.length < 2) {
      setResults([]);
      return;
    }
    const current = ++request.current;
    const timer = window.setTimeout(() => {
      searchPlaces(query)
        .then((places) => {
          if (current === request.current) setResults(places);
        })
        .catch(() => {
          if (current === request.current) setResults([]);
        });
    }, 280);
    return () => window.clearTimeout(timer);
  }, [value]);

  return (
    <label className="field place-field">
      <span>{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        onChange={(event) => {
          onText(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        required
      />
      {open && results.length > 0 && (
        <ul id={listId} className="suggestions" role="listbox">
          {results.map((place) => (
            <li key={`${place.latitude},${place.longitude},${place.label}`}>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onPick(place);
                  setOpen(false);
                }}
              >
                {place.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </label>
  );
}

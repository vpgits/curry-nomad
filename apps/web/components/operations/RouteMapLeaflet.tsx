"use client";

import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import L from "leaflet";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

import type { RouteStop } from "@/lib/ops-types";

// Colombo warehouse — mirrors operations/geo.py:DEPOT (lat, lng).
const DEPOT: [number, number] = [6.9344, 79.8428];

const INK = "#1c1917";
const TURMERIC = "#d97706"; // brand accent, matches the chart palette

// A numbered pin as an HTML divIcon — sidesteps Leaflet's default-marker asset/bundler issue and
// lets us label each stop with its visit order (depot = "D", brand-tinted).
function pinIcon(label: string, tinted: boolean) {
  return L.divIcon({
    className: "",
    html: `<span style="display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:9999px;font:600 11px/1 ui-sans-serif,system-ui,sans-serif;color:${
      tinted ? INK : "#fafaf9"
    };background:${tinted ? TURMERIC : INK};box-shadow:0 1px 3px rgba(0,0,0,.35)">${label}</span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

// Auto-fit the viewport to the whole tour whenever the stops change.
function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    map.fitBounds(points, { padding: [36, 36] });
  }, [map, points]);
  return null;
}

// The real OSM map for a planned route: depot + numbered stops + the optimizer's tour. Default
// export so RouteMap can next/dynamic-import it with ssr:false (Leaflet touches `window`).
export default function RouteMapLeaflet({
  stops,
  depot = DEPOT,
}: {
  stops: RouteStop[];
  depot?: [number, number];
}) {
  const stopLatLngs = stops.map((s) => [s.lat, s.lng] as [number, number]);
  const tour: [number, number][] = [depot, ...stopLatLngs];

  return (
    <div className="overflow-hidden rounded-[14px] border bg-card">
      <MapContainer
        center={depot}
        zoom={9}
        scrollWheelZoom={false}
        style={{ height: 330, width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Polyline
          positions={tour}
          pathOptions={{ color: INK, weight: 2, dashArray: "5 6", opacity: 0.6 }}
        />
        <Marker position={depot} icon={pinIcon("D", true)}>
          <Tooltip direction="top" offset={[0, -12]}>
            <span className="font-semibold">Depot</span> · Colombo warehouse
          </Tooltip>
        </Marker>
        {stops.map((s) => (
          <Marker key={s.delivery_id} position={[s.lat, s.lng]} icon={pinIcon(String(s.seq), false)}>
            <Tooltip direction="top" offset={[0, -12]}>
              <span className="font-semibold">Stop {s.seq}</span> · #{s.order_id}
              <br />
              {s.address}
            </Tooltip>
          </Marker>
        ))}
        <FitBounds points={tour} />
      </MapContainer>
    </div>
  );
}

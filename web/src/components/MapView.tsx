import { CircleMarker, MapContainer, Marker, Popup, TileLayer, useMapEvents } from "react-leaflet";
import type { StaticData } from "../data";
import type { SiteProfile } from "../types";

function ClickHandler({ onSelect }: { onSelect: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onSelect(e.latlng.lat, e.latlng.lng) });
  return null;
}

export function MapView({ data, selected, onSelect }: { data: StaticData; selected: SiteProfile | null; onSelect: (lat: number, lon: number) => void }) {
  return (
    <MapContainer center={[25, 0]} zoom={2} style={{ height: 360, borderRadius: 8 }} worldCopyJump>
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <ClickHandler onSelect={onSelect} />
      {data.cells.map((c) => (
        <CircleMarker key={c.cell_id} center={[c.lat, c.lon]} radius={5} pathOptions={{ color: "#2e7d32", fillOpacity: 0.7 }}
          eventHandlers={{ click: () => onSelect(c.lat, c.lon) }} />
      ))}
      {Object.entries(data.regions).map(([id, r]) => (
        <Marker key={id} position={[r.lat, r.lon]}><Popup>{r.name}<br />Click a green dot to analyse.</Popup></Marker>
      ))}
      {selected && <CircleMarker center={[selected.location.lat, selected.location.lon]} radius={11} pathOptions={{ color: "#e65100", fillOpacity: 0.2 }} />}
    </MapContainer>
  );
}


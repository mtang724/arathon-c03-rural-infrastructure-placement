import pandas as pd
import folium
from pathlib import Path
from html import escape
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent


def load_base_stations(path):
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}

    stations = data.get("base_stations", [])
    for station in stations:
        station["latitude"] = float(station["location"]["latitude"])
        station["longitude"] = float(station["location"]["longitude"])
    return stations


def add_base_stations(map_object, stations):
    layer = folium.FeatureGroup(name="Base stations", show=True)

    for station in stations:
        latitude = station["location"]["latitude"]
        longitude = station["location"]["longitude"]
        cell_ids = "<br>".join(escape(str(cell_id)) for cell_id in station["cell_ids"])
        popup = (
            f"<b>{escape(str(station['name']))}</b><br>"
            f"Latitude: {escape(str(latitude))}<br>"
            f"Longitude: {escape(str(longitude))}<br>"
            f"<b>Cell IDs</b><br>{cell_ids}"
        )

        folium.Marker(
            location=[station["latitude"], station["longitude"]],
            tooltip=f"Base station: {station['name']}",
            popup=folium.Popup(popup, max_width=300),
            icon=folium.Icon(color="red", icon="signal", prefix="fa"),
        ).add_to(layer)

    layer.add_to(map_object)

# Read CSV
df = pd.read_csv(SCRIPT_DIR / "COTS.csv")
base_stations = load_base_stations(SCRIPT_DIR / "Base_Station_Information.yaml")

# Remove rows with missing GPS
df = df.dropna(subset=["lat", "lon"])

# Center map at mean location
center_lat = df["lat"].mean()
center_lon = df["lon"].mean()

# Create map
m = folium.Map(location=[center_lat, center_lon], zoom_start=14)

# Add black dots
for _, row in df.iterrows():
    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=2,
        color="black",
        fill=True,
        fill_color="black",
        fill_opacity=1.0
    ).add_to(m)

# Add base-station icons from the YAML file
add_base_stations(m, base_stations)

# Ensure both measurement points and base stations are visible
all_latitudes = df["lat"].tolist() + [station["latitude"] for station in base_stations]
all_longitudes = df["lon"].tolist() + [station["longitude"] for station in base_stations]
if all_latitudes and all_longitudes:
    m.fit_bounds(
        [
            [min(all_latitudes), min(all_longitudes)],
            [max(all_latitudes), max(all_longitudes)],
        ]
    )

folium.LayerControl(collapsed=False).add_to(m)

# Save map
output_file = SCRIPT_DIR / "locations_map.html"
m.save(output_file)

print(f"Saved {output_file.name}")

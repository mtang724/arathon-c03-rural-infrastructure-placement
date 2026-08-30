import pandas as pd
import folium
from branca.colormap import linear
from pathlib import Path
from html import escape
import sys
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
filename = SCRIPT_DIR / "COTS.csv"
base_station_file = SCRIPT_DIR / "Base_Station_Information.yaml"


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


# Load CSV
df = pd.read_csv(filename)
base_stations = load_base_stations(base_station_file)

if len(sys.argv) != 2:
    raise SystemExit("Usage: python plot.py <throughput-column>")

# Choose which throughput column to plot (for example, "uplink" or "downlink")
throughput_col = sys.argv[1]

if throughput_col not in df.columns:
    raise SystemExit(f"Column not found in COTS.csv: {throughput_col}")

df[throughput_col] = pd.to_numeric(df[throughput_col], errors="coerce")

# Remove rows with missing values
df = df.dropna(subset=["lat", "lon", throughput_col])

cell_ids = ["00019C00B", "00019C015", "00019C01F"]
df = df[df["cellid"].isin(cell_ids)]


# Center map at mean location
center_lat = df["lat"].mean()
center_lon = df["lon"].mean()

m = folium.Map(location=[center_lat, center_lon], zoom_start=14)

# Create color scale
colormap = linear.YlOrRd_09.scale(
    df[throughput_col].min(), df[throughput_col].max())
colormap = linear.viridis.scale(
    df[throughput_col].min(), df[throughput_col].max())
colormap.caption = throughput_col
colormap.add_to(m)

# Add points
for _, row in df.iterrows():
    value = row[throughput_col]
    color = colormap(value)

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=5,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.8,
        popup=(
            f"Time: {row['timestamp_local']}<br>"
            f"Throughput: {value:.2f} Mbps<br>"
            f"Ping: {row['ping_ms']}"
        ),
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
output_file = SCRIPT_DIR / f"{throughput_col}_map.html"
m.save(output_file)

print(output_file.name)

"""
Optribute v3 — Visual Route Test
Usage: python3 visual_test.py https://YOUR-URL.up.railway.app
Opens an interactive map in your browser showing the optimized routes.
"""
import requests, sys, json, webbrowser, os

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

# ══════════════════════════════════════════════
# Real Istanbul delivery data — 30 points
# ══════════════════════════════════════════════

SCENARIOS = {
    "single_closed": {
        "title": "Single Depot · 30 pts · Closed · Distance",
        "payload": {
            "depots": [{"id": 0, "lat": 41.0550, "lon": 28.9500}],  # Kagithane
            "jobs": [
                # Beyoglu / Sisli area
                {"id": 1,  "lat": 41.0370, "lon": 28.9750, "demand": 40, "time_start": 540, "time_end": 1020},
                {"id": 2,  "lat": 41.0430, "lon": 28.9880, "demand": 25, "time_start": 540, "time_end": 1080},
                {"id": 3,  "lat": 41.0510, "lon": 28.9920, "demand": 55, "time_start": 480, "time_end": 720},
                {"id": 4,  "lat": 41.0600, "lon": 28.9730, "demand": 30, "time_start": 540, "time_end": 1080},
                # Fatih / Old city
                {"id": 5,  "lat": 41.0170, "lon": 28.9500, "demand": 60, "time_start": 540, "time_end": 1020},
                {"id": 6,  "lat": 41.0080, "lon": 28.9680, "demand": 35, "time_start": 480, "time_end": 900},
                {"id": 7,  "lat": 41.0120, "lon": 28.9350, "demand": 45, "time_start": 540, "time_end": 1080},
                # Eyup / Gaziosmanpasa
                {"id": 8,  "lat": 41.0530, "lon": 28.9330, "demand": 20, "time_start": 600, "time_end": 840},
                {"id": 9,  "lat": 41.0700, "lon": 28.9100, "demand": 50, "time_start": 540, "time_end": 1020},
                {"id": 10, "lat": 41.0650, "lon": 28.8900, "demand": 30, "time_start": 540, "time_end": 1080},
                # Bayrampasa / Esenler
                {"id": 11, "lat": 41.0400, "lon": 28.9050, "demand": 40, "time_start": 480, "time_end": 960},
                {"id": 12, "lat": 41.0300, "lon": 28.8800, "demand": 35, "time_start": 540, "time_end": 1080},
                # Bakirkoy / Zeytinburnu
                {"id": 13, "lat": 40.9830, "lon": 28.8700, "demand": 45, "time_start": 540, "time_end": 1020},
                {"id": 14, "lat": 41.0020, "lon": 28.9050, "demand": 25, "time_start": 600, "time_end": 900},
                {"id": 15, "lat": 40.9900, "lon": 28.8550, "demand": 50, "time_start": 540, "time_end": 1080},
                # Bahcelievler / Kucukcekmece
                {"id": 16, "lat": 41.0050, "lon": 28.8350, "demand": 30, "time_start": 480, "time_end": 1020},
                {"id": 17, "lat": 41.0100, "lon": 28.7800, "demand": 55, "time_start": 540, "time_end": 1080},
                {"id": 18, "lat": 40.9950, "lon": 28.7500, "demand": 20, "time_start": 540, "time_end": 1080},
                # Basaksehir / Sultangazi (north-west)
                {"id": 19, "lat": 41.0950, "lon": 28.8100, "demand": 45, "time_start": 540, "time_end": 1020},
                {"id": 20, "lat": 41.0850, "lon": 28.8400, "demand": 35, "time_start": 540, "time_end": 1080},
                # Besiktas / Sariyer (north-east)
                {"id": 21, "lat": 41.0450, "lon": 29.0020, "demand": 30, "time_start": 540, "time_end": 1020},
                {"id": 22, "lat": 41.0750, "lon": 29.0150, "demand": 40, "time_start": 540, "time_end": 1080},
                {"id": 23, "lat": 41.1100, "lon": 29.0250, "demand": 25, "time_start": 480, "time_end": 900},
                # Scattered extras
                {"id": 24, "lat": 41.0250, "lon": 28.9200, "demand": 35, "time_start": 540, "time_end": 1080},
                {"id": 25, "lat": 41.0480, "lon": 28.8600, "demand": 30, "time_start": 600, "time_end": 840},
                {"id": 26, "lat": 40.9700, "lon": 28.8200, "demand": 50, "time_start": 540, "time_end": 1020},
                {"id": 27, "lat": 41.0800, "lon": 28.9500, "demand": 20, "time_start": 540, "time_end": 1080},
                {"id": 28, "lat": 41.0350, "lon": 28.9600, "demand": 40, "time_start": 480, "time_end": 960},
                {"id": 29, "lat": 41.0200, "lon": 28.8500, "demand": 55, "time_start": 540, "time_end": 1080},
                {"id": 30, "lat": 40.9800, "lon": 28.7900, "demand": 25, "time_start": 540, "time_end": 1020},
            ],
            "vehicle_count": 5,
            "use_capacity": False,
            "open_route": False,
            "service_time": 10,
            "route_start_time": 480,
            "optimization_goal": "distance",
            "time_limit": 20,
        }
    },
    "single_open": {
        "title": "Single Depot · 30 pts · OPEN · Distance",
        "payload": None  # will copy from single_closed
    },
    "multi_depot": {
        "title": "Multi Depot · 30 pts · Closed · Distance",
        "payload": {
            "depots": [
                {"id": 0,  "lat": 41.0500, "lon": 28.8800},  # Bayrampasa
                {"id": -1, "lat": 40.9930, "lon": 29.1100},   # Atasehir
            ],
            "jobs": [
                # European side
                {"id": 1,  "lat": 41.0370, "lon": 28.9750, "demand": 40},
                {"id": 2,  "lat": 41.0510, "lon": 28.9920, "demand": 25},
                {"id": 3,  "lat": 41.0170, "lon": 28.9500, "demand": 60},
                {"id": 4,  "lat": 41.0530, "lon": 28.9330, "demand": 20},
                {"id": 5,  "lat": 41.0700, "lon": 28.9100, "demand": 50},
                {"id": 6,  "lat": 41.0300, "lon": 28.8800, "demand": 35},
                {"id": 7,  "lat": 40.9830, "lon": 28.8700, "demand": 45},
                {"id": 8,  "lat": 41.0050, "lon": 28.8350, "demand": 30},
                {"id": 9,  "lat": 41.0100, "lon": 28.7800, "demand": 55},
                {"id": 10, "lat": 41.0950, "lon": 28.8100, "demand": 45},
                {"id": 11, "lat": 41.0450, "lon": 29.0020, "demand": 30},
                {"id": 12, "lat": 40.9700, "lon": 28.8200, "demand": 50},
                # Asian side
                {"id": 13, "lat": 40.9850, "lon": 29.0600, "demand": 45},
                {"id": 14, "lat": 41.0250, "lon": 29.0150, "demand": 30},
                {"id": 15, "lat": 41.0300, "lon": 29.1050, "demand": 35},
                {"id": 16, "lat": 40.8900, "lon": 29.1900, "demand": 40},
                {"id": 17, "lat": 40.8750, "lon": 29.2500, "demand": 25},
                {"id": 18, "lat": 40.8200, "lon": 29.3000, "demand": 60},
                {"id": 19, "lat": 41.0050, "lon": 29.2200, "demand": 30},
                {"id": 20, "lat": 41.0180, "lon": 29.1300, "demand": 50},
                {"id": 21, "lat": 40.9600, "lon": 29.0800, "demand": 35},
                {"id": 22, "lat": 40.9300, "lon": 29.1500, "demand": 40},
                {"id": 23, "lat": 41.0400, "lon": 29.0900, "demand": 20},
                {"id": 24, "lat": 40.9500, "lon": 29.2000, "demand": 55},
            ],
            "vehicle_count": 6,
            "use_capacity": False,
            "open_route": False,
            "service_time": 10,
            "route_start_time": 480,
            "optimization_goal": "distance",
            "time_limit": 20,
        }
    },
}

# Copy single_closed payload and modify for open
SCENARIOS["single_open"]["payload"] = json.loads(json.dumps(SCENARIOS["single_closed"]["payload"]))
SCENARIOS["single_open"]["payload"]["open_route"] = True

# ══════════════════════════════════════════════
# Run all scenarios
# ══════════════════════════════════════════════

COLORS = [
    "#d50000", "#2962ff", "#00c853", "#aa00ff", "#ff6d00",
    "#00bfa5", "#ffd600", "#c51162", "#aeea00", "#00b8d4",
    "#ff3d00", "#304ffe", "#1b5e20", "#6200ea", "#ef6c00",
]

results = {}
for key, scenario in SCENARIOS.items():
    print(f"\n[{scenario['title']}]")
    print(f"  Sending {len(scenario['payload']['jobs'])} jobs, {scenario['payload']['vehicle_count']} vehicles...")
    try:
        r = requests.post(f"{BASE}/optimize", json=scenario["payload"], timeout=120)
        if r.status_code != 200:
            print(f"  FAILED: HTTP {r.status_code} — {r.text[:200]}")
            continue
        data = r.json()
        results[key] = data
        s = data["summary"]
        si = data["solver_info"]
        print(f"  OK — {s['active_vehicles']} vehicles, {s['total_km']} km, solved in {si['total_time']}s")
        for rt in data["routes"]:
            ids = [p["original_id"] for p in rt["path"] if p["original_id"] > 0]
            print(f"  V{rt['vehicle_id']}: {rt['stop_count']} stops, {rt['total_km']}km")
    except Exception as e:
        print(f"  ERROR: {e}")

if not results:
    print("\nNo results to visualize!")
    sys.exit(1)

# ══════════════════════════════════════════════
# Generate HTML with Leaflet maps
# ══════════════════════════════════════════════

def make_map_section(title, scenario_key, result, payload):
    depots = payload["depots"]
    routes = result["routes"]
    summary = result["summary"]
    solver = result["solver_info"]
    is_open = payload.get("open_route", False)

    depot_markers = ""
    for d in depots:
        depot_markers += f"""
        L.marker([{d['lat']}, {d['lon']}], {{
            icon: L.divIcon({{
                className: '',
                html: '<div style="background:#000;color:#fff;border-radius:4px;padding:2px 6px;font:bold 11px monospace;border:2px solid #fff;">D</div>',
                iconSize: [24, 24], iconAnchor: [12, 12]
            }})
        }}).addTo(map_{scenario_key}).bindTooltip('Depot: {d["lat"]:.4f}, {d["lon"]:.4f}');
        """

    route_js = ""
    for i, rt in enumerate(routes):
        color = COLORS[i % len(COLORS)]
        path = rt["path"]
        coords = [[p["lat"], p["lon"]] for p in path]
        coords_js = json.dumps(coords)

        route_js += f"""
        L.polyline({coords_js}, {{color: '{color}', weight: 4, opacity: 0.8}})
            .addTo(map_{scenario_key})
            .bindTooltip('V{rt["vehicle_id"]}: {rt["stop_count"]} stops, {rt["total_km"]}km');
        """

        for j, p in enumerate(path):
            if p["original_id"] <= 0:
                continue
            route_js += f"""
        L.circleMarker([{p['lat']}, {p['lon']}], {{
            radius: 7, fillColor: '{color}', color: '#fff', weight: 2, fillOpacity: 0.9
        }}).addTo(map_{scenario_key}).bindTooltip('V{rt["vehicle_id"]} #{j} — ID:{p["original_id"]}, {p["arrival_time"]}');
        """

    # Arrow direction markers for open routes
    if is_open:
        for i, rt in enumerate(routes):
            color = COLORS[i % len(COLORS)]
            path = rt["path"]
            if len(path) >= 2:
                last = path[-1]
                route_js += f"""
        L.circleMarker([{last['lat']}, {last['lon']}], {{
            radius: 10, fillColor: '{color}', color: '#fff', weight: 3, fillOpacity: 1.0
        }}).addTo(map_{scenario_key}).bindTooltip('V{rt["vehicle_id"]} END');
        """

    legend_items = ""
    for i, rt in enumerate(routes):
        color = COLORS[i % len(COLORS)]
        depot_label = f" (D{rt.get('depot_id', 0)})" if len(depots) > 1 else ""
        legend_items += f"""
        <div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <div style="width:16px;height:3px;background:{color};border-radius:2px;"></div>
            <span style="font-size:12px;">V{rt['vehicle_id']}{depot_label}: {rt['stop_count']} stops, {rt['total_km']}km</span>
        </div>"""

    return f"""
    <div style="margin-bottom:30px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <h2 style="margin:0;font-size:18px;color:#1a73e8;">{title}</h2>
            <div style="font-family:monospace;font-size:12px;color:#888;">
                {summary['active_vehicles']} vehicles · {summary['total_km']} km · {solver['total_time']}s
            </div>
        </div>
        <div id="map_{scenario_key}" style="height:500px;border-radius:10px;border:1px solid #ddd;"></div>
        <div style="display:flex;gap:20px;margin-top:8px;">
            <div style="background:#f8f9fa;border-radius:8px;padding:10px 14px;flex:1;">
                <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Routes</div>
                {legend_items}
            </div>
            <div style="background:#f8f9fa;border-radius:8px;padding:10px 14px;">
                <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">Mode</div>
                <div style="font-size:13px;">{'OPEN' if is_open else 'CLOSED'} · {payload.get('optimization_goal', 'distance').upper()}</div>
            </div>
        </div>
    </div>
    <script>
        var map_{scenario_key} = L.map('map_{scenario_key}').setView([{depots[0]['lat']}, {depots[0]['lon']}], 12);
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: 'OpenStreetMap, CARTO', maxZoom: 19
        }}).addTo(map_{scenario_key});
        {depot_markers}
        {route_js}
    </script>
    """

# Build full HTML
map_sections = ""
for key in ["single_closed", "single_open", "multi_depot"]:
    if key in results:
        map_sections += make_map_section(
            SCENARIOS[key]["title"], key,
            results[key], SCENARIOS[key]["payload"]
        )

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Optribute v3 — Visual Test</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
    body {{
        font-family: 'Inter', sans-serif;
        max-width: 1100px;
        margin: 0 auto;
        padding: 20px 30px;
        background: #fff;
        color: #333;
    }}
    h1 {{
        font-size: 28px;
        font-weight: 700;
        color: #1a73e8;
        margin-bottom: 4px;
    }}
    .subtitle {{
        font-size: 14px;
        color: #888;
        margin-bottom: 30px;
    }}
</style>
</head>
<body>
<h1>Optribute v3 — Route Visualization</h1>
<div class="subtitle">Real Istanbul coordinates · OR-Tools optimized · {BASE}</div>
{map_sections}
</body>
</html>"""

# Save and open
filename = "optribute_v3_routes.html"
with open(filename, "w", encoding="utf-8") as f:
    f.write(html)

filepath = os.path.abspath(filename)
print(f"\nMap saved: {filepath}")
webbrowser.open(f"file://{filepath}")

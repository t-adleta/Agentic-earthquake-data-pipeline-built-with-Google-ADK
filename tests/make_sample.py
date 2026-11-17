"""Generates tests/sample_feed.geojson: SYNTHETIC events in the USGS feed format.

Used only so the tests run offline. It is not real seismic data.
"""
import json
import random
from pathlib import Path

random.seed(7)
PLACES = ["12 km SSW of Volcano, Hawaii", "40 km W of Anchorage, Alaska", "8 km NE of Ridgecrest, CA",
          "102 km E of Hachinohe, Japan", "south of the Fiji Islands", "55 km S of Hualien City, Taiwan",
          "30 km N of Ensenada, B.C., MX", "Kermadec Islands region", "15 km SE of Mina, Nevada"]
START = 1794268800000  # 2026-11-10 00:00 UTC
features = []
for i in range(120):
    mag = round(min(7.4, random.expovariate(0.9) + 0.8), 1)
    features.append({
        "type": "Feature", "id": f"syn{i:04d}",
        "properties": {"mag": mag, "place": random.choice(PLACES),
                       "time": START + random.randint(0, 7 * 86400000 - 1),
                       "type": "earthquake", "sig": int(mag * 60), "tsunami": int(mag >= 6.8)},
        "geometry": {"type": "Point", "coordinates": [round(random.uniform(-180, 180), 3),
                     round(random.uniform(-60, 65), 3), round(random.choice([5, 10, 35, 120, 410]) + random.random(), 1)]},
    })
# Deliberate dirty rows for the data-quality checks:
features.append(dict(features[0]))                                    # duplicate id
features.append({"type": "Feature", "id": "synblast",                 # not an earthquake
                 "properties": {"mag": 1.9, "place": "5 km N of Quarry, Nevada", "time": START, "type": "quarry blast"},
                 "geometry": {"type": "Point", "coordinates": [-117.0, 38.0, 0.0]}})
features.append({"type": "Feature", "id": "synnull",                  # missing magnitude
                 "properties": {"mag": None, "place": "10 km E of Nowhere, Alaska", "time": START, "type": "earthquake"},
                 "geometry": {"type": "Point", "coordinates": [-150.0, 61.0, 20.0]}})
Path(__file__).with_name("sample_feed.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))

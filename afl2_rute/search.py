"""Pencarian tempat: dari data OSM lokal (cepat, tanpa internet), atau online lewat geocoding OSM (Nominatim)."""
import re
from dataclasses import dataclass

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point

from . import config

PRIORITY = {"Favorit": 0, "Jalan": 2}  # jenis lain = 1
ONLINE_KIND = "Hasil online"


@dataclass
class Place:
    """Satu hasil pencarian: nama, jenis tempat, dan lokasinya (meter)."""
    name: str
    kind: str
    point: Point


def normalize(value):
    """Huruf kecil, tanda baca jadi spasi, spasi ganda dirapikan (supaya "G-Walk" cocok dengan "g walk")."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", value.lower()).split())


class PlaceIndex:
    """Daftar semua tempat yang bisa dicari: landmark favorit, tempat OSM, titik hidrasi, dan nama jalan."""

    def __init__(self, data):
        layers = [data.landmarks[["name", "kind", "geometry"]], data.places, data.points[["name", "kind", "geometry"]]]
        table = pd.concat(layers, ignore_index=True)
        table = table.drop_duplicates(subset=["name", "kind"]).reset_index(drop=True)
        table["key"] = table["name"].map(normalize)
        table["flat"] = table["key"].str.replace(" ", "")  # "g walk" -> "gwalk", supaya ketikan tanpa spasi tetap cocok
        table["priority"] = table["kind"].map(PRIORITY).fillna(1)
        self.table = table
        self.bounds = data.edges.total_bounds

    def find(self, name):
        """Tempat dengan nama persis `name` (dipakai untuk titik awal/akhir bawaan), atau None."""
        rows = self.table[self.table["name"] == name]
        return None if rows.empty else self.place(rows.iloc[0])

    def favorites(self):
        """Landmark favorit dari config, ditampilkan saat kotak pencarian masih kosong."""
        rows = self.table[self.table["kind"] == "Favorit"].head(config.SEARCH_RESULTS)
        return [self.place(row) for _, row in rows.iterrows()]

    def place(self, row):
        """Ubah satu baris tabel jadi Place."""
        return Place(row["name"], row["kind"], row.geometry)

    def search(self, query, limit=config.SEARCH_RESULTS):
        """Cari tempat yang namanya mengandung semua kata di `query`.

        Urutan hasil: nama yang diawali kata kunci dulu, lalu kata di tengah nama; landmark favorit
        sebelum tempat lain, nama jalan paling akhir; nama yang lebih pendek (lebih persis) didahulukan.
        """
        words = normalize(query).split()
        if not words or len(" ".join(words)) < config.SEARCH_MIN_CHARS:
            return []
        table = self.table
        match = pd.Series(True, index=table.index)
        for word in words:
            match &= table["key"].str.contains(word, regex=False) | table["flat"].str.contains(word, regex=False)
        found = table[match].copy()
        first = words[0]
        found["rank"] = 2
        found.loc[found["key"].str.contains(rf"\b{re.escape(first)}", regex=True), "rank"] = 1
        found.loc[found["key"].str.startswith(first) | found["flat"].str.startswith(first), "rank"] = 0
        found["size"] = found["key"].str.len()
        found = found.sort_values(["rank", "priority", "size"]).head(limit)
        return [self.place(row) for _, row in found.iterrows()]

    def search_online(self, query):
        """Cari lewat geocoding OSM (butuh internet). None kalau tidak ketemu atau di luar area peta."""
        try:
            lat, lon = ox.geocode(f"{query}, {config.AREA_PLACE}")
        except Exception:  # tidak ada internet, server sibuk, atau tidak ketemu
            return None
        point = gpd.GeoSeries([Point(lon, lat)], crs=config.SOURCE_CRS).to_crs(config.ANALYSIS_CRS).iloc[0]
        min_x, min_y, max_x, max_y = self.bounds
        if not (min_x <= point.x <= max_x and min_y <= point.y <= max_y):
            return None
        return Place(query, ONLINE_KIND, point)

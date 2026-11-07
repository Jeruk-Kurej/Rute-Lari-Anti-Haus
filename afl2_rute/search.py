"""Pencarian tempat: dari data OSM lokal (cepat, tanpa internet), atau online lewat geocoding OSM (Nominatim)."""
import re
from dataclasses import dataclass

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point

from . import config

PRIORITY = {"Jalan": 2}  # jenis lain = 1: nama jalan paling akhir di hasil pencarian
ONLINE_KIND = "Hasil online"
PICKED_KIND = "Titik di peta"


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
    """Daftar semua tempat yang bisa dicari: tempat OSM, titik hidrasi, dan nama jalan. Landmark di config hanya untuk titik bawaan."""

    def __init__(self, data):
        layers = [data.places, data.points[["name", "kind", "geometry"]]]
        self.landmarks = data.landmarks.set_index("name").geometry
        table = pd.concat(layers, ignore_index=True)
        table = table.drop_duplicates(subset=["name", "kind"]).reset_index(drop=True)
        table["key"] = table["name"].map(normalize)
        table["flat"] = table["key"].str.replace(" ", "")  # "g walk" -> "gwalk", supaya ketikan tanpa spasi tetap cocok
        table["priority"] = table["kind"].map(PRIORITY).fillna(1)
        self.table = table
        self.boundary = data.boundary
        self.roads = data.edges[data.edges["road_name"].notna()]  # untuk memberi nama pada titik yang dipilih di peta

    def find(self, name):
        """Tempat bawaan dengan nama `name` (landmark di config, atau tempat di data), dipakai untuk titik awal/akhir saat dibuka."""
        if name in self.landmarks.index:
            return Place(name, "Landmark", self.landmarks[name])
        rows = self.table[self.table["name"] == name]
        return None if rows.empty else self.place(rows.iloc[0])

    def at_point(self, point):
        """Tempat untuk titik yang dipilih langsung di peta: dinamai "Dekat <jalan terdekat>" (jalan sejauh MAP_PICK_ROAD_M).

        None kalau titiknya di luar batas Surabaya (tidak ada data jalan di sana).
        """
        if not self.boundary.contains(point):
            return None
        found, nearest = self.roads.sindex.nearest(point, max_distance=config.MAP_PICK_ROAD_M, return_all=False)
        name = f"Dekat {self.roads['road_name'].iloc[nearest[0]]}" if len(nearest) else "Titik di peta"
        return Place(name, PICKED_KIND, point)

    def place(self, row):
        """Ubah satu baris tabel jadi Place."""
        return Place(row["name"], row["kind"], row.geometry)

    def search(self, query, limit=config.SEARCH_RESULTS):
        """Cari tempat yang namanya mengandung semua kata di `query`.

        Urutan hasil: nama yang diawali kata kunci dulu, lalu kata di tengah nama;
        nama jalan paling akhir; nama yang lebih pendek (lebih persis) didahulukan.
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
        """Cari lewat geocoding OSM (butuh internet). Hasilnya (Place, None), atau (None, alasan gagalnya dalam kalimat)."""
        try:
            lat, lon = ox.geocode(f"{query}, {config.AREA_PLACE}")
        except ox._errors.InsufficientResponseError:
            return None, f"\"{query}\" tidak ditemukan, juga lewat internet. Coba nama lain."
        except Exception:  # tidak ada internet, atau server peta sedang sibuk
            return None, "Pencarian lewat internet gagal. Cek koneksimu, lalu coba lagi."
        point = gpd.GeoSeries([Point(lon, lat)], crs=config.SOURCE_CRS).to_crs(config.ANALYSIS_CRS).iloc[0]
        if not self.boundary.contains(point):
            return None, f"\"{query}\" ada, tapi di luar Surabaya."
        return Place(query, ONLINE_KIND, point), None

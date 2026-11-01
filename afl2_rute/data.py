"""Memuat data: jalan, titik hidrasi, dan landmark dari OSM (atau dari cache), lalu menyiapkannya untuk analisis."""
from dataclasses import dataclass

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, box

from . import config
from .network import RoadNetwork

ox.settings.cache_folder = config.CACHE_DIR / "http"
ox.settings.use_cache = True


@dataclass
class Dataset:
    """Semua data yang dibutuhkan program, sudah dalam satuan meter (EPSG:32749)."""
    network: RoadNetwork
    nodes: gpd.GeoDataFrame
    edges: gpd.GeoDataFrame
    points: gpd.GeoDataFrame
    landmarks: gpd.GeoDataFrame
    buildings: gpd.GeoDataFrame


# --- Landmark dan area ---
def geocode_landmarks(landmarks):
    """Cari koordinat tiap landmark: dari kata kunci OSM, atau langsung dari (lat, lon) di config."""
    rows, missing = [], []
    for name, query in landmarks.items():
        try:
            lat, lon = query if isinstance(query, tuple) else ox.geocode(query)
        except ox._errors.InsufficientResponseError:
            missing.append(name)
            continue
        rows.append({"name": name, "geometry": Point(lon, lat)})
    if missing:
        print(f"Landmark tidak ditemukan di OSM: {missing}. Isi LANDMARKS dengan (lat, lon) dari Google Maps.")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.SOURCE_CRS) if rows else None


def with_new_landmarks(cached):
    """Landmark baru di config langsung ikut (tanpa hapus cache). Landmark yang sudah ada di cache dipakai apa adanya."""
    new = geocode_landmarks({name: query for name, query in config.LANDMARKS.items() if name not in set(cached["name"])})
    return cached if new is None else pd.concat([cached, new], ignore_index=True)


def area_bbox(landmarks, padding_m):
    """Kotak area peta: membungkus semua landmark ditambah `padding_m` meter di sekelilingnya."""
    bounds = landmarks.to_crs(config.ANALYSIS_CRS).buffer(padding_m).total_bounds
    return tuple(gpd.GeoSeries([box(*bounds)], crs=config.ANALYSIS_CRS).to_crs(config.SOURCE_CRS).total_bounds)


# --- Titik hidrasi ---
def fetch_features(bbox, tags):
    """Ambil objek OSM di dalam bbox sesuai tags. Kalau tidak ada, hasilnya tabel kosong."""
    try:
        return ox.features.features_from_bbox(bbox, tags=tags)
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=config.SOURCE_CRS)


def as_points(raw, kind):
    """Ubah objek OSM (bisa berupa bangunan/area) jadi titik: nama, jenis, dan titik tengahnya."""
    names = raw["name"] if "name" in raw else pd.Series(None, index=raw.index, dtype=object)
    layer = gpd.GeoDataFrame({"name": names.fillna(kind), "kind": kind}, geometry=raw.geometry, crs=raw.crs)
    layer = layer.reset_index(drop=True).to_crs(config.ANALYSIS_CRS)
    layer["geometry"] = layer.geometry.centroid
    return layer


def brand(name):
    """Merek sebuah toko = kata pertama namanya, huruf kecil (misal "Alfamart Raya" -> "alfamart")."""
    return name.split()[0].lower()


def without_duplicates(osm, manual):
    """Buang titik OSM yang sama merek dan berdekatan (DUPLICATE_RADIUS_M) dengan titik manual: dianggap toko yang sama."""
    duplicate = [
        any(brand(name) == brand(other) and geom.distance(other_geom) < config.DUPLICATE_RADIUS_M
            for other, other_geom in zip(manual["name"], manual.geometry))
        for name, geom in zip(osm["name"], osm.geometry)
    ]
    return osm[[not d for d in duplicate]]


def manual_points(entries):
    """Ubah titik manual dari config (nama: (jenis, (lat, lon))) jadi tabel titik dalam satuan meter."""
    return gpd.GeoDataFrame(
        {"name": list(entries), "kind": [kind for kind, _ in entries.values()]},
        geometry=[Point(lon, lat) for _, (lat, lon) in entries.values()],
        crs=config.SOURCE_CRS,
    ).to_crs(config.ANALYSIS_CRS)


def merge_manual(osm):
    """Gabungkan titik OSM dengan titik manual di config (Google Maps), tanpa duplikat."""
    manual = manual_points(config.MANUAL_POINTS)
    return pd.concat([without_duplicates(osm, manual), manual], ignore_index=True)


def load_hydration_points(bbox):
    """Unduh titik hidrasi dari OSM (minimarket, supermarket, kedai minuman), lalu gabung dengan titik manual."""
    parts = [as_points(fetch_features(bbox, {"shop": tag}), kind) for tag, kind in config.OSM_SHOP_KINDS.items()]
    parts.append(as_points(fetch_features(bbox, config.OSM_DRINK_TAGS), "Kedai minuman"))
    return merge_manual(pd.concat([p for p in parts if not p.empty], ignore_index=True))


def refresh_manual_points(cached):
    """Titik manual di cache diganti dengan yang ada di config sekarang, jadi menambah/mengubah titik cukup edit config."""
    return merge_manual(cached[~cached["name"].isin(config.MANUAL_POINTS)])


# --- Bangunan (layer polygon, hanya untuk tampilan) ---
def polygons_only(raw):
    """Ambil hanya bentuk poligon dari hasil unduhan OSM, dan pecah MultiPolygon jadi poligon tunggal."""
    layer = raw[["geometry"]].copy()
    layer["name"] = raw["name"] if "name" in raw else None
    layer = layer[layer.geom_type.isin(["Polygon", "MultiPolygon"])]
    return layer.explode(index_parts=False).reset_index(drop=True)


def load_buildings(bbox):
    """Unduh semua bangunan (tag OSM building) di dalam bbox sebagai poligon."""
    return polygons_only(fetch_features(bbox, {"building": True}))


def read_buildings(file):
    """Baca bangunan dari cache. Kalau file-nya tidak ada, hasilnya kosong: program tetap jalan tanpa bangunan."""
    if not file.exists():
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=config.SOURCE_CRS)
    return gpd.read_file(file)


# --- Nama: kelas jalan, nama jalan, nama titik ---
def road_name(name):
    """Nama jalan yang rapi: ambil nama pertama kalau ada beberapa, dan singkat "Jalan" jadi "Jl."."""
    name = name[0] if isinstance(name, list) else name
    return name.replace("Jalan ", "Jl. ", 1) if isinstance(name, str) else None


def road_class(highway):
    """Kelompokkan jenis jalan OSM (highway) ke kelas di config: jalan raya, perumahan, atau setapak/servis."""
    tags = [tag.removesuffix("_link") for tag in (highway if isinstance(highway, list) else [highway])]
    for name, kinds in config.ROAD_CLASSES.items():
        if any(tag in kinds for tag in tags):
            return name
    return config.OTHER_ROAD_CLASS


def unique_names(points, edges):
    """Bedakan titik yang namanya kembar: tambah nama jalan terdekat, lalu nomor (#1, #2) kalau masih sama."""
    named = edges[edges["road_name"].notna()]
    generic = points["name"].duplicated(keep=False)
    for i in points.index[generic]:
        distances = named.distance(points.geometry[i])
        if distances.min() <= config.STREET_SEARCH_M:
            points.loc[i, "name"] += f" {named['road_name'][distances.idxmin()]}"
    duplicated = points["name"].duplicated(keep=False)
    suffix = (points.groupby("name").cumcount() + 1).astype(str)
    points.loc[duplicated, "name"] += " #" + suffix[duplicated]
    return points


# --- Dataset ---
def build_dataset(G, points, landmarks, buildings):
    """Siapkan semua data untuk analisis.

    Langkah penting: setiap toko dan landmark dijadikan node di ruas jalan terdekatnya
    (RoadNetwork.attach). Kolom `node` menyimpan node-nya, `offset_m` jarak toko ke node itu.
    """
    network = RoadNetwork(G)
    points = points.to_crs(config.ANALYSIS_CRS).reset_index(drop=True)
    landmarks = landmarks.to_crs(config.ANALYSIS_CRS)
    buildings = buildings.to_crs(config.ANALYSIS_CRS)
    attached = network.attach(list(points.geometry) + list(landmarks.geometry))
    points["node"], points["offset_m"] = zip(*attached[:len(points)])
    landmarks["node"] = [node for node, _ in attached[len(points):]]

    nodes, edges = ox.convert.graph_to_gdfs(network.G)
    edges["road_class"] = edges["highway"].map(road_class)
    edges["road_name"] = edges["name"].map(road_name)
    return Dataset(network, nodes, edges, unique_names(points, edges), landmarks, buildings)


def load_dataset():
    """Muat dataset dari cache. Kalau cache belum ada, unduh dari OSM lalu simpan."""
    graph_file = config.CACHE_DIR / "jalan.graphml"
    points_file = config.CACHE_DIR / "titik_hidrasi.gpkg"
    landmarks_file = config.CACHE_DIR / "landmark.gpkg"
    buildings_file = config.CACHE_DIR / "bangunan.gpkg"
    if graph_file.exists() and points_file.exists() and landmarks_file.exists():
        points = refresh_manual_points(gpd.read_file(points_file))
        landmarks = with_new_landmarks(gpd.read_file(landmarks_file))
        return build_dataset(ox.io.load_graphml(graph_file), points, landmarks, read_buildings(buildings_file))

    landmarks = geocode_landmarks(config.LANDMARKS)
    if landmarks is None or len(landmarks) < 2:
        raise ValueError("Butuh minimal 2 landmark.")
    bbox = area_bbox(landmarks, config.AREA_PADDING_M)
    G = ox.projection.project_graph(ox.graph.graph_from_bbox(bbox, network_type="walk"), to_crs=config.ANALYSIS_CRS)
    points = load_hydration_points(bbox)
    buildings = load_buildings(bbox)

    config.CACHE_DIR.mkdir(exist_ok=True)
    ox.io.save_graphml(G, graph_file)
    points.to_file(points_file, driver="GPKG")
    landmarks.to_file(landmarks_file, driver="GPKG")
    buildings.to_file(buildings_file, driver="GPKG")
    return build_dataset(G, points, landmarks, buildings)

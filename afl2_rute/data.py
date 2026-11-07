"""Memuat data satu kota: jalan, titik hidrasi, tempat yang bisa dicari, dan landmark, dari OSM (atau dari cache)."""
from dataclasses import dataclass

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import Point

from . import config
from .network import RoadNetwork

ox.settings.cache_folder = config.CACHE_DIR / "http"
ox.settings.use_cache = True


@dataclass
class Dataset:
    """Semua data yang dibutuhkan program, sudah dalam satuan meter (EPSG:32749)."""
    network: RoadNetwork
    edges: gpd.GeoDataFrame
    points: gpd.GeoDataFrame
    landmarks: gpd.GeoDataFrame
    places: gpd.GeoDataFrame
    buildings: gpd.GeoDataFrame
    boundary: object  # batas wilayah kota (MultiPolygon), di luarnya tidak ada data

    def attach(self, geometries):
        """Jadikan titik-titik ini node di ruas jalan terdekat, lalu samakan tabel ruas dengan graph.

        Dipakai saat program dibuka (titik hidrasi) dan saat pengguna memilih tempat baru sebagai stop.
        Hasilnya daftar (node, jarak_titik_ke_node).
        """
        attached = self.network.attach(list(geometries), self.edges)
        net = self.network
        if net.removed:
            kept = self.edges.drop(index=net.removed)
            self.edges = pd.concat([kept, edge_table(net.G.edge_subgraph(net.added))])
        return attached


def cached(file, make, read=gpd.read_file):
    """Baca `file` dari cache kalau ada. Kalau belum, buat dengan `make()` (unduh dari OSM) lalu simpan."""
    if file.exists():
        return read(file)
    print(f"Mengunduh {file.name} dari OpenStreetMap (sekali saja)...")
    layer = make()
    config.CACHE_DIR.mkdir(exist_ok=True)
    if isinstance(layer, gpd.GeoDataFrame):
        layer.to_file(file, driver="GPKG")
    else:
        ox.io.save_graphml(layer, file)
    return layer


def as_points(raw):
    """Objek OSM (bisa berupa bangunan/area) -> titik di tengahnya, dalam meter."""
    layer = raw.reset_index(drop=True).to_crs(config.ANALYSIS_CRS)
    layer["geometry"] = layer.geometry.centroid
    return layer


# --- Jalan ---
def download_roads():
    """Unduh jaringan jalan pejalan kaki seluruh kota, lalu ubah ke meter."""
    return ox.projection.project_graph(ox.graph.graph_from_place(config.AREA_PLACE, network_type="walk"), to_crs=config.ANALYSIS_CRS)


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


def edge_table(G):
    """Tabel ruas jalan dari graph (satu baris per ruas, index = (u, v, key)), plus kelas dan nama jalannya."""
    edges = ox.convert.graph_to_gdfs(G, nodes=False)
    edges["road_class"] = edges["highway"].map(road_class)
    edges["road_name"] = edges["name"].map(road_name) if "name" in edges else None
    return edges[["geometry", "length", "road_class", "road_name"]]


# --- Titik hidrasi ---
def download_hydration_points():
    """Unduh minimarket, supermarket, kedai minuman, dan restoran seluruh kota dari OSM (restoran yang tak bernama dibuang)."""
    raw = ox.features.features_from_place(config.AREA_PLACE, tags=config.OSM_HYDRATION_TAGS)
    kind = raw["shop"].map(config.OSM_SHOP_KINDS) if "shop" in raw else pd.Series(None, index=raw.index, dtype=object)
    if "amenity" in raw:
        kind = kind.fillna(raw["amenity"].map(config.OSM_AMENITY_KINDS))
    kind = kind.fillna("Kedai minuman")
    if "name" in raw:
        raw, kind = raw[~(raw["name"].isna() & (kind == "Restoran"))], kind[~(raw["name"].isna() & (kind == "Restoran"))]
    layer = as_points(gpd.GeoDataFrame({"name": raw["name"].fillna(kind), "kind": kind}, geometry=raw.geometry, crs=raw.crs))
    return layer.to_crs(config.SOURCE_CRS)


def brand(name):
    """Merek sebuah toko = kata pertama namanya, huruf kecil (misal "Alfamart Raya" -> "alfamart")."""
    return name.split()[0].lower()


def without_duplicates(osm, manual):
    """Buang titik OSM yang sama merek dan berdekatan (DUPLICATE_RADIUS_M) dengan titik manual: dianggap toko yang sama."""
    near, other = manual.sindex.query(osm.geometry, predicate="dwithin", distance=config.DUPLICATE_RADIUS_M)
    duplicate = {i for i, j in zip(near, other) if brand(osm["name"].iloc[i]) == brand(manual["name"].iloc[j])}
    return osm[[i not in duplicate for i in range(len(osm))]]


def manual_points(entries):
    """Ubah titik manual dari config (nama: (jenis, (lat, lon))) jadi tabel titik dalam satuan meter."""
    return gpd.GeoDataFrame(
        {"name": list(entries), "kind": [kind for kind, _ in entries.values()]},
        geometry=[Point(lon, lat) for _, (lat, lon) in entries.values()],
        crs=config.SOURCE_CRS,
    ).to_crs(config.ANALYSIS_CRS)


def with_manual_points(osm):
    """Gabungkan titik OSM dengan titik manual di config (Google Maps), tanpa duplikat."""
    osm = osm.to_crs(config.ANALYSIS_CRS)
    manual = manual_points(config.MANUAL_POINTS)
    return pd.concat([without_duplicates(osm, manual), manual], ignore_index=True)


# --- Tempat yang bisa dicari ---
def download_places():
    """Unduh tempat bernama (kampus, taman, mal, kawasan, ...) seluruh kota untuk fitur pencarian."""
    raw = ox.features.features_from_place(config.AREA_PLACE, tags=config.PLACE_TAGS)
    raw = raw[raw["name"].notna()]
    kind = pd.Series(None, index=raw.index, dtype=object)
    for tag in reversed(list(config.PLACE_TAGS)):  # tag pertama di config paling diutamakan
        if tag in raw:
            kind = raw[tag].map(config.PLACE_KINDS).fillna(kind)
    layer = gpd.GeoDataFrame({"name": raw["name"], "kind": kind.fillna("Tempat")}, geometry=raw.geometry, crs=raw.crs)
    return as_points(layer).to_crs(config.SOURCE_CRS)


def street_places(edges):
    """Setiap nama jalan jadi satu tempat yang bisa dicari, letaknya di tengah ruas terpanjangnya."""
    named = edges[edges["road_name"].notna()]
    longest = named.loc[named.groupby("road_name")["length"].idxmax()]
    points = [line.interpolate(0.5, normalized=True) for line in longest.geometry]
    return gpd.GeoDataFrame({"name": longest["road_name"].to_numpy(), "kind": "Jalan"}, geometry=points, crs=edges.crs)


# --- Batas kota ---
def download_boundary():
    """Unduh batas wilayah kota (poligon) dari OSM. Dipakai untuk menandai area di luar data di peta."""
    return ox.geocoder.geocode_to_gdf(config.AREA_PLACE)[["geometry"]]


# --- Landmark ---
def geocode_landmarks(landmarks):
    """Cari koordinat tiap landmark: dari kata kunci OSM, atau langsung dari (lat, lon) di config."""
    rows, missing = [], []
    for name, query in landmarks.items():
        try:
            lat, lon = query if isinstance(query, tuple) else ox.geocode(query)
        except ox._errors.InsufficientResponseError:
            missing.append(name)
            continue
        rows.append({"name": name, "kind": "Landmark", "geometry": Point(lon, lat)})
    if missing:
        print(f"Landmark tidak ditemukan di OSM: {missing}. Isi LANDMARKS dengan (lat, lon) dari Google Maps.")
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.SOURCE_CRS) if rows else None


def with_new_landmarks(cached_landmarks):
    """Landmark baru di config langsung ikut (tanpa hapus cache). Landmark yang sudah ada di cache dipakai apa adanya."""
    known = set(cached_landmarks["name"])
    new = geocode_landmarks({name: query for name, query in config.LANDMARKS.items() if name not in known})
    layer = cached_landmarks if new is None else pd.concat([cached_landmarks, new], ignore_index=True)
    layer["kind"] = "Landmark"
    return layer


# --- Bangunan (layer polygon, hanya untuk tampilan) ---
def read_buildings(file):
    """Baca bangunan dari cache. Kalau file-nya tidak ada, hasilnya kosong: program tetap jalan tanpa bangunan."""
    if not file.exists():
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=config.SOURCE_CRS)
    return gpd.read_file(file)


# --- Nama titik ---
def unique_names(points, edges):
    """Bedakan titik yang namanya kembar: tambah nama jalan terdekat, lalu nomor (#1, #2) kalau masih sama."""
    named = edges[edges["road_name"].notna()]
    generic = points.index[points["name"].duplicated(keep=False)]
    if len(generic):
        found, nearest = named.sindex.nearest(points.geometry[generic], max_distance=config.STREET_SEARCH_M, return_all=False)
        for i, row in zip(found, nearest):
            points.loc[generic[i], "name"] += f" {named['road_name'].iloc[row]}"
    duplicated = points["name"].duplicated(keep=False)
    suffix = (points.groupby("name").cumcount() + 1).astype(str)
    points.loc[duplicated, "name"] += " #" + suffix[duplicated]
    return points


# --- Dataset ---
def load_dataset():
    """Muat dataset dari cache. Bagian yang belum ada di cache diunduh dari OSM lalu disimpan."""
    folder = config.CACHE_DIR
    G = cached(folder / "jalan.graphml", download_roads, ox.io.load_graphml)
    osm_points = cached(folder / "titik_hidrasi.gpkg", download_hydration_points)
    places = cached(folder / "tempat.gpkg", download_places)
    boundary = cached(folder / "batas_kota.gpkg", download_boundary)
    landmarks_file = folder / "landmark.gpkg"
    if landmarks_file.exists():
        landmarks = with_new_landmarks(gpd.read_file(landmarks_file))
    else:
        landmarks = geocode_landmarks(config.LANDMARKS)
        landmarks.to_file(landmarks_file, driver="GPKG")

    data = Dataset(
        network=RoadNetwork(G),
        edges=edge_table(G),
        points=with_manual_points(osm_points),
        landmarks=landmarks.to_crs(config.ANALYSIS_CRS),
        places=places.to_crs(config.ANALYSIS_CRS),
        buildings=read_buildings(folder / "bangunan.gpkg").to_crs(config.ANALYSIS_CRS),
        boundary=boundary.to_crs(config.ANALYSIS_CRS).union_all(),
    )
    # Setiap toko jadi node di ruas jalan terdekatnya: kolom `node`, dan `offset_m` = jarak toko ke node itu
    data.points["node"], data.points["offset_m"] = zip(*data.attach(data.points.geometry))
    data.points = unique_names(data.points, data.edges)
    data.places = pd.concat([data.places, street_places(data.edges)], ignore_index=True)
    return data

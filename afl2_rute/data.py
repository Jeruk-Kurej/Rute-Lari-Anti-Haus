from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import Point, box

from . import config

ox.settings.cache_folder = config.CACHE_DIR / "http"
ox.settings.use_cache = True


@dataclass
class Dataset:
    G: nx.MultiDiGraph
    nodes: gpd.GeoDataFrame
    edges: gpd.GeoDataFrame
    points: gpd.GeoDataFrame
    landmarks: gpd.GeoDataFrame


# --- Landmark dan area ---
def geocode_landmarks(landmarks):
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
    if len(rows) < 2:
        raise ValueError("Butuh minimal 2 landmark.")
    return gpd.GeoDataFrame(rows, crs=config.SOURCE_CRS)


def area_bbox(landmarks, padding_m):
    bounds = landmarks.to_crs(config.ANALYSIS_CRS).buffer(padding_m).total_bounds
    return tuple(gpd.GeoSeries([box(*bounds)], crs=config.ANALYSIS_CRS).to_crs(config.SOURCE_CRS).total_bounds)


# --- Titik hidrasi ---
def fetch_features(bbox, tags):
    try:
        return ox.features.features_from_bbox(bbox, tags=tags)
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=config.SOURCE_CRS)


def as_points(raw, kind):
    names = raw["name"] if "name" in raw else pd.Series(None, index=raw.index, dtype=object)
    layer = gpd.GeoDataFrame({"name": names.fillna(kind), "kind": kind}, geometry=raw.geometry, crs=raw.crs)
    layer = layer.reset_index(drop=True).to_crs(config.ANALYSIS_CRS)
    layer["geometry"] = layer.geometry.centroid
    return layer


def brand(name):
    return name.split()[0].lower()


def without_duplicates(osm, manual):
    duplicate = [
        any(brand(name) == brand(other) and geom.distance(other_geom) < config.DUPLICATE_RADIUS_M
            for other, other_geom in zip(manual["name"], manual.geometry))
        for name, geom in zip(osm["name"], osm.geometry)
    ]
    return osm[[not d for d in duplicate]]


def load_hydration_points(bbox):
    parts = [as_points(fetch_features(bbox, {"shop": tag}), kind) for tag, kind in config.OSM_SHOP_KINDS.items()]
    parts.append(as_points(fetch_features(bbox, config.OSM_DRINK_TAGS), "Kedai minuman"))
    osm = pd.concat([p for p in parts if not p.empty], ignore_index=True)

    manual = gpd.GeoDataFrame(
        {"name": list(config.MANUAL_POINTS), "kind": [kind for kind, _ in config.MANUAL_POINTS.values()]},
        geometry=[Point(lon, lat) for _, (lat, lon) in config.MANUAL_POINTS.values()],
        crs=config.SOURCE_CRS,
    ).to_crs(config.ANALYSIS_CRS)
    return pd.concat([without_duplicates(osm, manual), manual], ignore_index=True)


# --- Nama: kelas jalan, nama jalan, nama titik ---
def road_name(name):
    name = name[0] if isinstance(name, list) else name
    return name.replace("Jalan ", "Jl. ", 1) if isinstance(name, str) else None


def road_class(highway):
    tags = [tag.removesuffix("_link") for tag in (highway if isinstance(highway, list) else [highway])]
    for name, kinds in config.ROAD_CLASSES.items():
        if any(tag in kinds for tag in tags):
            return name
    return config.OTHER_ROAD_CLASS


def unique_names(points, edges):
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
def build_dataset(G, points, landmarks):
    nodes, edges = ox.convert.graph_to_gdfs(G)
    edges["road_class"] = edges["highway"].map(road_class)
    edges["road_name"] = edges["name"].map(road_name)
    points = unique_names(points.to_crs(config.ANALYSIS_CRS).reset_index(drop=True), edges)
    return Dataset(G, nodes, edges, points, landmarks.to_crs(config.ANALYSIS_CRS))


def load_dataset():
    graph_file = config.CACHE_DIR / "jalan.graphml"
    points_file = config.CACHE_DIR / "titik_hidrasi.gpkg"
    landmarks_file = config.CACHE_DIR / "landmark.gpkg"
    if graph_file.exists() and points_file.exists() and landmarks_file.exists():
        return build_dataset(ox.io.load_graphml(graph_file), gpd.read_file(points_file), gpd.read_file(landmarks_file))

    landmarks = geocode_landmarks(config.LANDMARKS)
    bbox = area_bbox(landmarks, config.AREA_PADDING_M)
    G = ox.projection.project_graph(ox.graph.graph_from_bbox(bbox, network_type="walk"), to_crs=config.ANALYSIS_CRS)
    points = load_hydration_points(bbox)

    config.CACHE_DIR.mkdir(exist_ok=True)
    ox.io.save_graphml(G, graph_file)
    points.to_file(points_file, driver="GPKG")
    landmarks.to_file(landmarks_file, driver="GPKG")
    return build_dataset(G, points, landmarks)

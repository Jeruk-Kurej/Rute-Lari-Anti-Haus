from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import substring

from . import config


@dataclass
class Scene:
    tolerance_m: int
    points: gpd.GeoDataFrame
    zone: shapely.Geometry
    safe_edges: gpd.GeoDataFrame
    safe_graph: nx.MultiDiGraph


@dataclass
class Comparison:
    baseline: LineString
    safe: LineString | None
    status: str


@dataclass
class Reroute:
    line: LineString
    via_outside: bool


@dataclass
class NextHydration:
    name: str
    distance_m: float
    path: LineString | None


# --- Operasi GIS: buffer + union, lalu spatial selection (within) ---
def radius_zone(data, points, tolerance_m):
    zone = points.buffer(tolerance_m).union_all()
    return zone, data.edges[data.edges.within(zone.buffer(1))]


# --- Zona lewat jalan: jarak menyusuri jalan dari titik hidrasi terdekat ---
def road_distances(data, points):
    sources = {}
    for geom in points.geometry:
        node = nearest_node(data, geom.x, geom.y)
        sources[node] = min(sources.get(node, float("inf")), data.nodes.geometry[node].distance(geom))
    G, source = data.G, "titik_hidrasi"
    G.add_node(source)
    G.add_weighted_edges_from(((source, node, offset) for node, offset in sources.items()), weight="length")
    try:
        return nx.single_source_dijkstra_path_length(G, source, weight="length")
    finally:
        G.remove_node(source)


def road_zone(data, points, tolerance_m):
    distances = road_distances(data, points)
    u = data.edges.index.get_level_values(0).map(distances)
    v = data.edges.index.get_level_values(1).map(distances)
    farthest = (u.to_numpy(float) + v.to_numpy(float) + data.edges["length"].to_numpy()) / 2
    safe_edges = data.edges[farthest <= tolerance_m]
    return shapely.MultiLineString(list(safe_edges.geometry)), safe_edges


def build_scene(data, tolerance_m, closed=(), mode=config.ZONE_MODES[0]):
    points = data.points[~data.points["name"].isin(closed)]
    zone, safe_edges = (radius_zone if mode == config.ZONE_MODES[0] else road_zone)(data, points, tolerance_m)
    return Scene(tolerance_m, points, zone, safe_edges, data.G.edge_subgraph(safe_edges.index))


# --- Graph jalan ---
def nearest_node(data, x, y):
    return data.nodes.distance(Point(x, y)).idxmin()


def landmark_node(data, name):
    geom = data.landmarks.set_index("name").geometry[name]
    return nearest_node(data, geom.x, geom.y)


def edge_line(G, u, v):
    attrs = min(G.get_edge_data(u, v).values(), key=lambda d: d["length"])
    start, end = (G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])
    if "geometry" not in attrs:
        return LineString([start, end])
    line = attrs["geometry"]
    return line if Point(line.coords[0]).distance(Point(start)) <= Point(line.coords[-1]).distance(Point(start)) else line.reverse()


def route_coords(G, path):
    coords = []
    for u, v in zip(path[:-1], path[1:]):
        part = list(edge_line(G, u, v).coords)
        coords.extend(part if not coords else part[1:])
    return coords


def route_line(G, path):
    return LineString(route_coords(G, path))


def join(*parts):
    coords = []
    for part in parts:
        coords.extend(part if not coords else part[1:])
    return coords


def shortest_path(G, origin, target):
    try:
        return nx.shortest_path(G, origin, target, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


# --- Routing: baseline vs anti-haus ---
def compare(data, scene, origin, target):
    baseline = route_line(data.G, shortest_path(data.G, origin, target))
    outside = [label for label, node in (("awal", origin), ("akhir", target)) if not scene.safe_graph.has_node(node)]
    if outside:
        return Comparison(baseline, None, f"Tidak ada rute anti-haus: titik {' & '.join(outside)} di luar zona")
    path = shortest_path(scene.safe_graph, origin, target)
    if path is None:
        return Comparison(baseline, None, "Tidak ada rute anti-haus: zona tidak tersambung")
    return Comparison(baseline, route_line(scene.safe_graph, path), "Rute anti-haus ditemukan")


# --- Rute ulang dari posisi pelari (dihitung lagi tiap keluar jalur) ---
def paths_to_target(scene, target):
    if not scene.safe_graph.has_node(target):
        return {}, {}
    return nx.single_source_dijkstra(scene.safe_graph, target, weight="length")


def reroute(data, scene, to_target, u, v, offset_m):
    lengths, paths = to_target
    line = edge_line(data.G, u, v)
    ends = ((u, offset_m, 0.0), (v, line.length - offset_m, line.length))
    options = []
    if scene.safe_graph.has_edge(u, v):
        options = [(lead + lengths[node], node, [node], end) for node, lead, end in ends if node in lengths]
    via_outside = not options
    if via_outside:
        for node, lead, end in ends:
            reach, approach = nx.single_source_dijkstra(data.G, node, weight="length")
            options += [(lead + reach[entry], entry, approach[entry], end) for entry in lengths if entry in reach]
    if not options:
        return None
    _, entry, approach, end = min(options, key=lambda option: option[0])
    coords = join(
        list(substring(line, offset_m, end).coords),
        route_coords(data.G, approach),
        route_coords(scene.safe_graph, paths[entry][::-1]),
    )
    return Reroute(LineString(coords), via_outside) if len(coords) > 1 else None


def minimum_tolerance(data, origin, target, closed=(), mode=config.ZONE_MODES[0]):
    for tolerance in config.TOLERANCE_SEARCH_M:
        G = build_scene(data, tolerance, closed, mode).safe_graph
        if G.has_node(origin) and G.has_node(target) and nx.has_path(G, origin, target):
            return tolerance
    return None


# --- Metrik ---
def max_gap_to_points(line, points):
    if points.empty:
        return None
    samples = shapely.points(shapely.get_coordinates(shapely.segmentize(line, config.SAMPLE_STEP_M)))
    return float(shapely.distance(samples, points.union_all()).max())


def route_stats(line, points):
    return {"panjang_m": line.length, "jarak_terjauh_m": max_gap_to_points(line, points)}


def next_hydration(data, points, u, v, offset_m):
    if points.empty:
        return None
    point_nodes = {}
    for name, geom in zip(points["name"], points.geometry):
        point_nodes.setdefault(nearest_node(data, geom.x, geom.y), name)
    line = edge_line(data.G, u, v)
    best = None
    for node, lead_m, end_m in ((u, offset_m, 0.0), (v, line.length - offset_m, line.length)):
        distance, path = nx.multi_source_dijkstra(data.G, set(point_nodes), target=node, weight="length")
        if best is None or lead_m + distance < best[0]:
            best = (lead_m + distance, path[::-1], end_m)
    distance, path, end_m = best
    coords = join(list(substring(line, offset_m, end_m).coords), route_coords(data.G, path))
    return NextHydration(point_nodes[path[-1]], distance, LineString(coords) if len(coords) > 1 else None)

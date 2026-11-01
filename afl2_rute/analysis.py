"""Perhitungan rute: zona aman, rute terpendek vs anti-haus, rute ulang, dan titik hidrasi terdekat."""
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import shapely
from shapely.geometry import LineString
from shapely.ops import substring

from . import config
from .network import join
from .zones import ZONES


@dataclass
class Scene:
    """Hasil satu kali pengaturan: titik yang buka, zona aman, dan graph yang hanya berisi ruas aman."""
    tolerance_m: int
    points: gpd.GeoDataFrame
    zone: shapely.Geometry
    safe_edges: gpd.GeoDataFrame
    safe_graph: nx.MultiDiGraph


@dataclass
class Comparison:
    """Rute terpendek (baseline) dan rute anti-haus, plus keterangan hasilnya."""
    baseline: LineString
    safe: LineString | None
    status: str


@dataclass
class Reroute:
    """Rute baru dari posisi pelari. via_outside = True kalau pelari harus kembali ke zona dulu."""
    line: LineString
    via_outside: bool


@dataclass
class NextHydration:
    """Titik hidrasi terdekat dari posisi pelari: nama, jarak lewat jalan, dan garis jalurnya."""
    name: str
    distance_m: float
    path: LineString | None


class RoutePlanner:
    """Semua perhitungan rute. Dibuat sekali dari Dataset, lalu dipakai berulang oleh aplikasi."""

    def __init__(self, data):
        self.data = data
        self.network = data.network
        self.zones = {name: kind(data) for name, kind in ZONES.items()}

    # --- Zona dan graph aman ---
    def build_scene(self, tolerance_m, closed=(), mode=config.ZONE_MODES[0]):
        """Hitung zona aman untuk toleransi tertentu. Titik di `closed` dianggap tutup."""
        points = self.data.points[~self.data.points["name"].isin(closed)]
        zone, safe_edges = self.zones[mode].build(points, tolerance_m)
        return Scene(tolerance_m, points, zone, safe_edges, self.network.G.edge_subgraph(safe_edges.index))

    def minimum_tolerance(self, origin, target, closed=(), mode=config.ZONE_MODES[0]):
        """Toleransi terkecil yang membuat rute anti-haus ada. None kalau sampai batas pencarian tetap tidak ada."""
        for tolerance in config.TOLERANCE_SEARCH_M:
            G = self.build_scene(tolerance, closed, mode).safe_graph
            if G.has_node(origin) and G.has_node(target) and nx.has_path(G, origin, target):
                return tolerance
        return None

    def landmark_node(self, name):
        """Node jalan tempat landmark (titik awal/akhir) berada."""
        return self.data.landmarks.set_index("name")["node"][name]

    # --- Rute terpendek vs anti-haus ---
    def compare(self, scene, origin, target):
        """Bandingkan rute terpendek di semua jalan dengan rute terpendek yang hanya lewat ruas aman."""
        net = self.network
        baseline = net.route(net.shortest_path(origin, target))
        outside = [label for label, node in (("awal", origin), ("akhir", target)) if not scene.safe_graph.has_node(node)]
        if outside:
            return Comparison(baseline, None, f"Tidak ada rute anti-haus: titik {' & '.join(outside)} di luar zona")
        path = net.shortest_path(origin, target, scene.safe_graph)
        if path is None:
            return Comparison(baseline, None, "Tidak ada rute anti-haus: zona tidak tersambung")
        return Comparison(baseline, net.route(path, scene.safe_graph), "Rute anti-haus ditemukan")

    def paths_to_target(self, scene, target):
        """Jarak dan jalur dari setiap persimpangan aman ke titik akhir (dipakai untuk rute ulang)."""
        if not scene.safe_graph.has_node(target):
            return {}, {}
        return nx.single_source_dijkstra(scene.safe_graph, target, weight="length")

    def reroute(self, scene, to_target, u, v, offset_m):
        """Rute baru ke titik akhir dari posisi pelari (di ruas u-v, sudah offset_m meter dari u).

        Kalau pelari masih di ruas aman, ia langsung menuju titik akhir lewat zona. Kalau tidak,
        ia kembali dulu ke persimpangan zona terdekat (via_outside = True).
        """
        net = self.network
        lengths, paths = to_target
        line = net.line(u, v)
        ends = ((u, offset_m, 0.0), (v, line.length - offset_m, line.length))
        options = []  # (jarak total, titik masuk zona, jalur menuju titik masuk, ujung ruas yang dipakai)
        if scene.safe_graph.has_edge(u, v):
            options = [(lead + lengths[node], node, [node], end) for node, lead, end in ends if node in lengths]
        via_outside = not options
        if via_outside:
            for node, lead, end in ends:
                reach, approach = nx.single_source_dijkstra(net.G, node, weight="length")
                options += [(lead + reach[entry], entry, approach[entry], end) for entry in lengths if entry in reach]
        if not options:
            return None
        _, entry, approach, end = min(options, key=lambda option: option[0])
        coords = join(
            list(substring(line, offset_m, end).coords),
            net.coords(approach),
            net.coords(paths[entry][::-1], scene.safe_graph),
        )
        return Reroute(LineString(coords), via_outside) if len(coords) > 1 else None

    # --- Metrik ---
    def farthest_gap(self, line, points):
        """Jarak terjauh (garis lurus) dari rute ke titik hidrasi terdekat, diperiksa tiap SAMPLE_STEP_M meter."""
        if points.empty:
            return None
        samples = shapely.points(shapely.get_coordinates(shapely.segmentize(line, config.SAMPLE_STEP_M)))
        return float(shapely.distance(samples, points.union_all()).max())

    def stats(self, line, points):
        """Angka untuk tabel hasil: panjang rute dan jarak terjauhnya ke titik hidrasi."""
        return {"panjang_m": line.length, "jarak_terjauh_m": self.farthest_gap(line, points)}

    # --- Titik hidrasi terdekat dari posisi pelari ---
    def next_hydration(self, points, u, v, offset_m):
        """Cari titik hidrasi terdekat lewat jalan dari pelari (di ruas u-v, offset_m meter dari u)."""
        if points.empty:
            return None
        net = self.network
        nearest = {}  # node -> (jarak toko ke node, nama, koordinat) untuk toko terdekat di node itu
        for name, geom, node, gap in zip(points["name"], points.geometry, points["node"], points["offset_m"]):
            if node not in nearest or gap < nearest[node][0]:
                nearest[node] = (gap, name, (geom.x, geom.y))

        line = net.line(u, v)
        best = None  # (jarak total, jalur dari ujung ruas ke toko, posisi ujung ruas)
        with net.virtual_source({node: found[0] for node, found in nearest.items()}) as source:
            for node, lead_m, end_m in ((u, offset_m, 0.0), (v, line.length - offset_m, line.length)):
                try:
                    distance, path = nx.single_source_dijkstra(net.G, source, target=node, weight="length")
                except nx.NetworkXNoPath:
                    continue
                if best is None or lead_m + distance < best[0]:
                    best = (lead_m + distance, path[:0:-1], end_m)
        if best is None:
            return None
        distance, path, end_m = best
        _, name, shop_xy = nearest[path[-1]]
        coords = join(list(substring(line, offset_m, end_m).coords), net.coords(path)) + [shop_xy]
        return NextHydration(name, distance, LineString(coords) if len(coords) > 1 else None)

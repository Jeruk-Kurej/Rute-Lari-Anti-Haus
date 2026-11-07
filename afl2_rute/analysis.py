"""Perhitungan rute: zona aman di sekitar rute, rute terpendek vs anti-haus (dengan stop dan alternatif),
pos minum di sepanjang rute, rute ulang pelari, dan daftar titik hidrasi terdekat."""
from dataclasses import dataclass, field

import geopandas as gpd
import networkx as nx
import shapely
from shapely.geometry import LineString, Point, box
from shapely.ops import substring

from . import config
from .network import join
from .zones import make_zones


@dataclass
class Stop:
    """Satu titik di rute (awal, stop, atau akhir): nama, jenis tempat, node jalannya, dan lokasinya."""
    name: str
    kind: str
    node: int
    point: Point


@dataclass
class Scene:
    """Hasil satu kali pengaturan: kotak area hitung, titik yang buka, zona aman, dan graph berisi ruas aman."""
    area: shapely.Geometry
    points: gpd.GeoDataFrame
    zone: shapely.Geometry
    safe_edges: gpd.GeoDataFrame
    safe_graph: nx.MultiDiGraph


@dataclass
class Route:
    """Satu rute utuh dari awal sampai akhir: rangkaian node, garisnya, dan garis per potongan (antar stop)."""
    path: list
    line: LineString
    legs: list
    new_share: float = 0.0  # untuk rute alternatif: berapa bagian jalannya yang belum dipakai rute sebelumnya (0 sampai 1)


@dataclass
class Comparison:
    """Rute terpendek (baseline), pilihan rute anti-haus (yang pertama = terbaik), dan keterangan hasilnya."""
    baseline: Route | None
    options: list
    status: str


@dataclass
class Reroute:
    """Rute baru dari posisi pelari. via_outside = True kalau pelari harus kembali ke zona dulu."""
    line: LineString
    via_outside: bool


@dataclass
class Hydration:
    """Titik hidrasi yang bisa dicapai pelari: nama, jenis, jarak lewat jalan, dan garis jalurnya."""
    name: str
    kind: str
    distance_m: float
    path: LineString | None


@dataclass
class DrinkStop:
    """Titik hidrasi yang dilewati rute: posisinya (meter dari awal rute) dan jaraknya dari rute."""
    name: str
    kind: str
    along_m: float
    offset_m: float


@dataclass
class RouteStats:
    """Angka untuk tabel hasil dan daftar pos minum."""
    length_m: float
    farthest_m: float | None
    drinks: list = field(default_factory=list)
    longest_dry_m: float | None = None


class RoutePlanner:
    """Semua perhitungan rute. Dibuat sekali dari Dataset, lalu dipakai berulang oleh aplikasi."""

    def __init__(self, data):
        self.data = data
        self.network = data.network
        self.zones = make_zones(data, config.ZONE_MODES)

    def empty_scene(self):
        """Scene kosong untuk saat rute belum lengkap (misal kotak "Dari" masih kosong): tanpa zona dan tanpa ruas aman."""
        edges = self.data.edges.iloc[0:0]
        return Scene(box(0, 0, 0, 0), self.data.points.iloc[0:0], shapely.Polygon(), edges, self.network.G.edge_subgraph([]))

    # --- Stop ---
    def make_stop(self, name, kind, point):
        """Jadikan tempat pilihan pengguna sebuah stop: titiknya ditempel jadi node di ruas jalan terdekat."""
        (node, _), = self.data.attach([point])
        return Stop(name, kind, node, point)

    # --- Zona dan graph aman, hanya di sekitar rute ---
    def corridor(self, stops, padding_m=config.CORRIDOR_PADDING_M):
        """Kotak yang membungkus semua stop, ditambah padding. Zona hanya dihitung di dalam kotak ini."""
        xs, ys = [s.point.x for s in stops], [s.point.y for s in stops]
        return box(min(xs) - padding_m, min(ys) - padding_m, max(xs) + padding_m, max(ys) + padding_m)

    def build_scene(self, stops, tolerance_m, closed=(), mode=config.ZONE_MODES[0]):
        """Hitung zona aman di sekitar rute untuk toleransi tertentu. Titik di `closed` dianggap tutup."""
        area = self.corridor(stops)
        edges = self.data.edges.iloc[self.data.edges.sindex.query(area)]
        points = self.data.points[~self.data.points["name"].isin(closed)]
        points = points.iloc[points.sindex.query(area.buffer(tolerance_m))]  # toko di luar kotak tapi masih menjangkau
        zone, safe_edges = self.zones[mode].build(points, tolerance_m, edges)
        return Scene(area, points, zone, safe_edges, self.network.G.edge_subgraph(safe_edges.index))

    def connected(self, scene, stops):
        """True kalau semua stop ada di zona aman dan tiap potongan rute tersambung."""
        G = scene.safe_graph
        nodes = [s.node for s in stops]
        return all(G.has_node(n) for n in nodes) and all(nx.has_path(G, a, b) for a, b in zip(nodes, nodes[1:]))

    def minimum_tolerance(self, stops, closed=(), mode=config.ZONE_MODES[0]):
        """Toleransi terkecil yang membuat rute anti-haus ada (binary search). None kalau sampai batas tetap tidak ada.

        Binary search boleh dipakai karena zona selalu membesar saat toleransi naik:
        kalau toleransi t berhasil, semua toleransi di atas t juga berhasil.
        """
        options = list(config.TOLERANCE_SEARCH_M)
        if not self.connected(self.build_scene(stops, options[-1], closed, mode), stops):
            return None
        low, high = 0, len(options) - 1
        while low < high:
            middle = (low + high) // 2
            if self.connected(self.build_scene(stops, options[middle], closed, mode), stops):
                high = middle
            else:
                low = middle + 1
        return options[low]

    # --- Rute terpendek vs anti-haus ---
    def route_through(self, stops, graph, weight="length"):
        """Rute terpendek yang melewati stop satu per satu (awal -> stop -> ... -> akhir). None kalau ada yang putus."""
        net, paths = self.network, []
        for a, b in zip(stops, stops[1:]):
            try:
                paths.append(nx.shortest_path(graph, a.node, b.node, weight=weight))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return None
        legs = [net.route(p, graph) if len(p) > 1 else LineString([net.xy(p[0])] * 2) for p in paths]
        return Route(join(*paths), LineString(join(*(list(leg.coords) for leg in legs))), legs)

    def alternatives(self, scene, stops, best):
        """Cari rute anti-haus lain: ruas yang sudah dipakai dibuat "lebih panjang" (penalti), lalu dicari ulang."""
        used, found = set(), [best]
        while len(found) < config.ROUTE_OPTIONS:
            used |= {frozenset(pair) for pair in zip(found[-1].path, found[-1].path[1:])}

            def weight(u, v, edges):
                length = min(attrs["length"] for attrs in edges.values())
                return length * (config.ALTERNATIVE_PENALTY if frozenset((u, v)) in used else 1)

            route = self.route_through(stops, scene.safe_graph, weight)
            if route is None or route.line.length > best.line.length * config.ALTERNATIVE_MAX_RATIO:
                break
            pairs = list(zip(route.path, route.path[1:]))
            new = sum(1 for pair in pairs if frozenset(pair) not in used) / max(len(pairs), 1)
            if new < config.ALTERNATIVE_MIN_NEW:
                break
            route.new_share = new
            found.append(route)
        return found

    def compare(self, scene, stops):
        """Bandingkan rute terpendek di semua jalan dengan rute anti-haus yang hanya lewat ruas aman."""
        baseline = self.route_through(stops, self.network.G)
        outside = [s.name for s in stops if not scene.safe_graph.has_node(s.node)]
        if outside:
            names = ", ".join(dict.fromkeys(outside))
            return Comparison(baseline, [], f"{names} terlalu jauh dari tempat minum.")
        best = self.route_through(stops, scene.safe_graph)
        if best is None:
            return Comparison(baseline, [], "Ada bagian jalan di antara tempat-tempat ini yang terlalu jauh dari tempat minum.")
        options = self.alternatives(scene, stops, best)
        return Comparison(baseline, options, f"{len(options)} rute aman minum ditemukan")

    # --- Metrik ---
    def farthest_gap(self, line, points):
        """Jarak terjauh (garis lurus) dari rute ke titik hidrasi terdekat, diperiksa tiap SAMPLE_STEP_M meter."""
        if points.empty:
            return None
        samples = shapely.points(shapely.get_coordinates(shapely.segmentize(line, config.SAMPLE_STEP_M)))
        return float(shapely.distance(samples, points.union_all()).max())

    def drink_stops(self, line, points):
        """Titik hidrasi yang sedekat ON_ROUTE_M dari rute, diurutkan dari awal rute."""
        near = points.iloc[points.sindex.query(line, predicate="dwithin", distance=config.ON_ROUTE_M)]
        drinks = [DrinkStop(name, kind, line.project(geom), line.distance(geom))
                  for name, kind, geom in zip(near["name"], near["kind"], near.geometry)]
        return sorted(drinks, key=lambda d: d.along_m)

    def stats(self, line, points, with_drinks=False):
        """Angka untuk tabel hasil: panjang, jarak terjauh ke titik hidrasi, dan (opsional) pos minum di rute."""
        result = RouteStats(line.length, self.farthest_gap(line, points))
        if with_drinks:
            result.drinks = self.drink_stops(line, points)
            marks = [0.0, *(d.along_m for d in result.drinks), line.length]
            result.longest_dry_m = max(b - a for a, b in zip(marks, marks[1:]))
        return result

    # --- Rute ulang pelari ---
    def paths_to_target(self, scene, target):
        """Jarak dan jalur dari setiap persimpangan aman ke `target` (stop berikutnya yang dituju pelari)."""
        if not scene.safe_graph.has_node(target):
            return {}, {}
        return nx.single_source_dijkstra(scene.safe_graph, target, weight="length")

    def reroute(self, scene, to_target, u, v, offset_m):
        """Rute baru ke stop berikutnya dari posisi pelari (di ruas u-v, sudah offset_m meter dari u).

        Kalau pelari masih di ruas aman, ia langsung menuju stop lewat zona. Kalau tidak,
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
                reach, approach = nx.single_source_dijkstra(net.G, node, cutoff=config.NEAREST_SEARCH_M, weight="length")
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

    # --- Titik hidrasi terdekat dari posisi pelari ---
    def nearest_hydrations(self, points, u, v, offset_m, count=config.NEAREST_COUNT):
        """Daftar `count` titik hidrasi terdekat lewat jalan dari pelari (di ruas u-v, offset_m meter dari u).

        Pelari dipasang sebagai node sementara yang tersambung ke kedua ujung ruasnya, lalu satu kali
        Dijkstra (sampai NEAREST_SEARCH_M) memberi jarak ke semua persimpangan. Jarak ke tiap toko =
        jarak ke node toko + jarak toko ke node itu. Hasilnya diurutkan dari yang terdekat.
        """
        net = self.network
        line = net.line(u, v)
        with net.virtual_source({u: offset_m, v: line.length - offset_m}) as source:
            reach, paths = nx.single_source_dijkstra(net.G, source, cutoff=config.NEAREST_SEARCH_M, weight="length")
        found = sorted(
            ((reach[node] + gap, name, kind, node, geom)
             for name, kind, node, gap, geom in zip(points["name"], points["kind"], points["node"], points["offset_m"], points.geometry)
             if node in reach),
            key=lambda row: row[0],
        )[:count]
        result = []
        for distance, name, kind, node, geom in found:
            path = paths[node][1:]  # tanpa node sementara
            end = 0.0 if path[0] == u else line.length
            coords = join(list(substring(line, offset_m, end).coords), net.coords(path)) + [(geom.x, geom.y)]
            result.append(Hydration(name, kind, distance, LineString(coords) if len(coords) > 1 else None))
        return result

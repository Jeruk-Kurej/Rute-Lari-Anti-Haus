"""Jaringan jalan: membungkus graph networkx beserta semua operasi dasar di atasnya."""
from contextlib import contextmanager

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.ops import substring

MIN_PIECE_M = 1.0  # potongan ruas yang lebih pendek dari ini tidak dibuat
SOURCE_NODE = "sumber_hidrasi"  # nama node sementara (lihat virtual_source)


def join(*parts):
    """Sambung beberapa daftar koordinat jadi satu. Titik sambungannya tidak diulang."""
    coords = []
    for part in parts:
        coords.extend(part if not coords else part[1:])
    return coords


class RoadNetwork:
    """Jalan sebagai graph: persimpangan = node, ruas jalan = edge yang punya panjang (meter)."""

    def __init__(self, G):
        self.G = G
        self.next_id = max(G.nodes) + 1  # nomor untuk node baru

    # --- Membaca graph ---
    def xy(self, node):
        """Koordinat (x, y) sebuah node, dalam meter."""
        return self.G.nodes[node]["x"], self.G.nodes[node]["y"]

    def facing(self, line, u, v):
        """Arahkan garis ruas supaya mulai dari node u. Kalau ruas tak punya bentuk, pakai garis lurus u-v."""
        if line is None:
            return LineString([self.xy(u), self.xy(v)])
        start = Point(self.xy(u))
        near_start = Point(line.coords[0]).distance(start) <= Point(line.coords[-1]).distance(start)
        return line if near_start else line.reverse()

    def line(self, u, v, graph=None):
        """Bentuk garis ruas dari node u ke node v. Kalau ada ruas kembar, diambil yang terpendek."""
        graph = self.G if graph is None else graph
        attrs = min(graph.get_edge_data(u, v).values(), key=lambda d: d["length"])
        return self.facing(attrs.get("geometry"), u, v)

    def coords(self, path, graph=None):
        """Daftar koordinat sepanjang rangkaian node (path), menyusuri bentuk asli jalannya."""
        coords = []
        for u, v in zip(path[:-1], path[1:]):
            coords = join(coords, list(self.line(u, v, graph).coords))
        return coords

    def route(self, path, graph=None):
        """Sama seperti coords(), tapi hasilnya berupa satu garis (LineString)."""
        return LineString(self.coords(path, graph))

    def shortest_path(self, origin, target, graph=None):
        """Rangkaian node terpendek dari origin ke target. None kalau tidak tersambung."""
        try:
            return nx.shortest_path(self.G if graph is None else graph, origin, target, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    @contextmanager
    def virtual_source(self, offsets):
        """Pasang node sementara yang tersambung ke tiap node di `offsets` {node: jarak}.

        Berguna untuk bertanya "jarak ke titik hidrasi TERDEKAT dari mana saja" cukup dengan
        satu kali Dijkstra dari node sementara ini. Setelah selesai, node-nya dilepas lagi.
        """
        self.G.add_node(SOURCE_NODE)
        self.G.add_weighted_edges_from(((SOURCE_NODE, node, gap) for node, gap in offsets.items()), weight="length")
        try:
            yield SOURCE_NODE
        finally:
            self.G.remove_node(SOURCE_NODE)

    # --- Menambah node di tengah ruas ---
    def attach(self, points):
        """Jadikan tiap titik (toko, landmark) sebuah node tepat di ruas jalan terdekatnya.

        Ruas yang dilalui dipecah jadi dua (atau lebih) potongan, jadi jarak dari kedua ujung
        ruas dihitung benar. Hasilnya daftar (node, jarak_titik_ke_node), urut sesuai input.
        """
        edges = ox.convert.graph_to_gdfs(self.G, nodes=False)
        hits = {}  # ruas -> daftar (posisi sepanjang ruas, nomor titik)
        for index, point in enumerate(points):
            u, v, key = edges.distance(point).idxmin()
            line = self.exact_line(u, v, key)
            s = line.project(point)
            twin = self.twin_key(u, v, key)
            if u > v and twin is not None:  # ruas dua arah dihitung sekali saja (arah u < v)
                u, v, key, s = v, u, twin, line.length - s
            hits.setdefault((u, v, key), []).append((s, index))

        nodes = [None] * len(points)
        for (u, v, key), found in hits.items():
            line = self.exact_line(u, v, key)
            stops = []  # (posisi, node) di tengah ruas
            for s, index in sorted(found):
                if s < MIN_PIECE_M:
                    nodes[index] = u
                elif line.length - s < MIN_PIECE_M:
                    nodes[index] = v
                elif stops and s - stops[-1][0] < MIN_PIECE_M:
                    nodes[index] = stops[-1][1]
                else:
                    nodes[index] = self.add_node_at(line.interpolate(s))
                    stops.append((s, nodes[index]))
            if stops:
                self.split_edge(u, v, key, stops)
        return [(node, Point(self.xy(node)).distance(point)) for node, point in zip(nodes, points)]

    def exact_line(self, u, v, key):
        """Bentuk garis satu ruas tertentu (key membedakan ruas kembar antara u dan v)."""
        return self.facing(self.G.edges[u, v, key].get("geometry"), u, v)

    def twin_key(self, u, v, key):
        """Key ruas kebalikannya (v ke u) yang panjangnya sama. None kalau jalannya satu arah."""
        if u == v:
            return None
        length = self.G.edges[u, v, key]["length"]
        for other, attrs in (self.G.get_edge_data(v, u) or {}).items():
            if abs(attrs["length"] - length) < 1:
                return other
        return None

    def add_node_at(self, point):
        """Tambah node baru di koordinat `point`, lalu kembalikan nomornya."""
        node, self.next_id = self.next_id, self.next_id + 1
        self.G.add_node(node, x=point.x, y=point.y)
        return node

    def split_edge(self, u, v, key, stops):
        """Ganti ruas u-v (dan arah baliknya) dengan potongan-potongan yang berhenti di tiap node di `stops`."""
        attrs = dict(self.G.edges[u, v, key])
        line = self.exact_line(u, v, key)
        twin = self.twin_key(u, v, key)
        twin_attrs = dict(self.G.edges[v, u, twin]) if twin is not None else None
        self.G.remove_edge(u, v, key)
        if twin is not None:
            self.G.remove_edge(v, u, twin)

        ends = [u, *(node for _, node in stops), v]
        positions = [0.0, *(s for s, _ in stops), line.length]
        for a, b, start, end in zip(ends, ends[1:], positions, positions[1:]):
            piece = substring(line, start, end)
            self.add_piece(a, b, piece, attrs, line.length)
            if twin_attrs is not None:
                self.add_piece(b, a, piece.reverse(), twin_attrs, line.length)

    def add_piece(self, a, b, piece, attrs, whole_length):
        """Pasang satu potongan ruas a-b. Panjangnya dibagi sebanding, jadi total panjang jalan tetap sama."""
        meters = attrs["length"] * piece.length / whole_length
        self.G.add_edge(a, b, **{**attrs, "geometry": piece, "length": meters})

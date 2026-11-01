"""Zona aman: ruas jalan mana yang masih cukup dekat dengan titik hidrasi."""
import networkx as nx
import shapely

from . import config


class Zone:
    """Kerangka semua jenis zona. Setiap jenis zona mengisi build() dengan caranya sendiri."""

    def __init__(self, data):
        self.data = data

    def build(self, points, tolerance_m):
        """Kembalikan (bentuk_zona, ruas_aman). Diisi oleh kelas turunan."""
        raise NotImplementedError


class RadiusZone(Zone):
    """Zona lingkaran, sesuai proposal: buffer tiap titik hidrasi, gabung (union), lalu seleksi dengan within."""

    def build(self, points, tolerance_m):
        zone = points.buffer(tolerance_m).union_all()
        edges = self.data.edges
        return zone, edges[edges.within(zone.buffer(1))]  # buffer(1): toleransi 1 m untuk pembulatan


class RoadZone(Zone):
    """Zona mengikuti jalan: ruas aman kalau jarak tempuh lewat jalan ke titik hidrasi terdekat <= toleransi."""

    def __init__(self, data):
        super().__init__(data)
        self.cache = {}  # jarak tidak bergantung toleransi, jadi cukup dihitung sekali per kumpulan titik

    def distances(self, points):
        """Jarak lewat jalan dari setiap persimpangan ke titik hidrasi terdekat."""
        key = tuple(points.index)
        if key not in self.cache:
            offsets = {}  # node -> jarak toko ke node itu (kalau ada beberapa toko, ambil yang terdekat)
            for node, gap in zip(points["node"], points["offset_m"]):
                offsets[node] = min(gap, offsets.get(node, float("inf")))
            network = self.data.network
            with network.virtual_source(offsets) as source:
                self.cache[key] = nx.single_source_dijkstra_path_length(network.G, source, weight="length")
        return self.cache[key]

    def build(self, points, tolerance_m):
        distances = self.distances(points)
        edges = self.data.edges
        u = edges.index.get_level_values(0).map(distances).to_numpy(float)
        v = edges.index.get_level_values(1).map(distances).to_numpy(float)
        # Titik terjauh di sebuah ruas ada di tempat dua jalur dari kedua ujungnya bertemu
        farthest = (u + v + edges["length"].to_numpy()) / 2
        safe_edges = edges[farthest <= tolerance_m]
        return shapely.MultiLineString(list(safe_edges.geometry)), safe_edges


# Nama zona (tampil di tombol "Zona") -> kelas yang menghitungnya
ZONES = dict(zip(config.ZONE_MODES, (RadiusZone, RoadZone)))

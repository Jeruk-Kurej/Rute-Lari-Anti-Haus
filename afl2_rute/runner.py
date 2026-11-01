"""Pelari virtual yang bergerak di sepanjang jalan sesuai tombol W/A/S/D."""
import math

from shapely.ops import substring

from .network import join

TURN_MIN_DOT = 0.5
MOVE_MIN_DOT = 0.3
HEADING_SAMPLE_M = 10


def unit(dx, dy):
    """Ubah arah (dx, dy) jadi vektor sepanjang 1, supaya hanya arahnya yang dihitung."""
    norm = math.hypot(dx, dy)
    return (dx / norm, dy / norm) if norm else (0.0, 0.0)


def dot(a, b):
    """Ukur kemiripan dua arah: 1 = searah, 0 = tegak lurus, -1 = berlawanan."""
    return a[0] * b[0] + a[1] * b[1]


# --- Pelari virtual: selalu berada di salah satu ruas jalan ---
class Runner:
    """Pelari virtual. Posisinya selalu di sebuah ruas jalan: ruas u-v, sudah berjalan s meter dari u."""

    def __init__(self, network, node):
        """Taruh pelari di node awal."""
        self.network = network
        self.place(node)

    def place(self, node):
        """Mulai dari node ini: kosongkan jejak dan hadapkan pelari ke salah satu ruas yang keluar dari node."""
        self.path = [node]
        self.enter(node, next(iter(self.network.G[node])))

    def arrive(self, node):
        """Catat kedatangan di node. Kalau kembali ke node sebelumnya, jejak ditarik mundur."""
        if len(self.path) > 1 and self.path[-2] == node:
            self.path.pop()
        elif self.path[-1] != node:
            self.path.append(node)

    def trail(self):
        """Koordinat jejak pelari dari titik awal sampai posisinya sekarang."""
        coords = self.network.coords(self.path) or [self.network.xy(self.path[-1])]
        start = 0.0 if self.path[-1] == self.u else self.line.length
        if abs(self.s - start) > 1e-6:
            coords = join(coords, list(substring(self.line, start, self.s).coords))
        return coords

    def enter(self, u, v):
        """Pindahkan pelari ke awal ruas u-v."""
        self.u, self.v, self.line, self.s = u, v, self.network.line(u, v), 0.0

    @property
    def position(self):
        """Posisi pelari sekarang sebagai (x, y) dalam meter."""
        point = self.line.interpolate(self.s)
        return point.x, point.y

    def heading(self):
        """Arah hadap pelari di ruasnya saat ini."""
        a = self.line.interpolate(max(self.s - 1, 0))
        b = self.line.interpolate(min(self.s + 1, self.line.length))
        return unit(b.x - a.x, b.y - a.y)

    def turn(self, node, direction):
        """Di persimpangan, pilih ruas yang paling searah dengan tombol. False kalau tidak ada yang cocok."""
        x, y = self.network.xy(node)
        best, best_dot = None, TURN_MIN_DOT
        for neighbor in self.network.G[node]:
            line = self.network.line(node, neighbor)
            if line.length < 0.5:
                continue
            ahead = line.interpolate(min(HEADING_SAMPLE_M, line.length))
            score = dot(unit(ahead.x - x, ahead.y - y), direction)
            if score > best_dot:
                best, best_dot = neighbor, score
        if best is None:
            return False
        self.enter(node, best)
        return True

    def move(self, direction, distance):
        """Gerakkan pelari sejauh `distance` meter ke arah tombol; belok otomatis di persimpangan."""
        while distance > 1e-6:
            node = self.u if self.s <= 0 else self.v if self.s >= self.line.length else None
            if node is not None:
                self.arrive(node)
                if not self.turn(node, direction):
                    return
            along = dot(self.heading(), direction)
            if abs(along) < MOVE_MIN_DOT:
                return
            end = self.line.length if along > 0 else 0.0
            step = min(distance, abs(end - self.s))
            self.s = end if step == abs(end - self.s) else self.s + math.copysign(step, along)
            distance -= step

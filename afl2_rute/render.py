"""Semua urusan menggambar peta: kamera, jalan, zona, rute, ikon titik hidrasi, dan label nama."""
import copy
import math

import pygame
from shapely.geometry import box

from .runner import unit

# Palet: biru = air/aman (rute anti-haus, tempat minum), oranye = panas/haus (rute tercepat), ungu = kamu (pelari)
COLORS = {
    "background": (236, 240, 238),
    "zone": (64, 170, 200),
    "building": (221, 226, 223),
    "road": (210, 216, 214),
    "safe_road": (150, 163, 168),
    "baseline": (226, 84, 44),
    "safe": (15, 111, 168),
    "alternative": (141, 185, 216),
    "outside": (222, 225, 223),
    "Minimarket": (16, 128, 120),
    "Supermarket": (19, 90, 115),
    "Kedai minuman": (58, 147, 196),
    "Restoran": (92, 102, 168),
    "closed": (165, 172, 175),
    "landmark": (29, 43, 51),
    "runner": (142, 91, 217),
    "hydration_path": (142, 91, 217),
    "trail": (142, 91, 217),
    "reroute": (240, 162, 59),
    "text": (29, 43, 51),
    "muted": (94, 110, 119),
    "line": (213, 221, 218),
    "surface": (242, 245, 244),
    "warning": (253, 240, 220),
    "white": (255, 255, 255),
}
RUNNER_HALO = (226, 212, 247)
ARROW_EVERY_M = 120
ARROW_GAP_PX = 70  # saat di-zoom jauh, panah tetap berjarak minimal segini di layar
SCALE_STEPS_M = (5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)
SCALE_BAR_MAX_PX = 160
MIN_ZOOM, MAX_SCALE = 0.8, 6  # zoom terjauh = 80% seluruh kota; terdekat = 6 piksel per meter
DASH_PX = 6
ZONE_ROAD_M, ZONE_ROAD_MIN_PX = 40, 6
LABEL_SCALE = 0.35  # piksel per meter: mulai tampilkan nama toko dan jalan
# Level of detail: jalan kecil, bangunan, dan ikon baru digambar saat cukup di-zoom (piksel per meter)
ROAD_MIN_SCALE = {"Jl. raya": 0, "Jl. perumahan": 0.06, "Setapak/servis": 0.15}
BUILDING_MIN_SCALE = 0.25
ICON_MIN_SCALE = 0.05
SMALL_ICON_SCALE, SMALL_ICON_RADIUS = 0.15, 7  # di bawah skala ini ikon digambar lebih kecil
ROAD_LABEL_GAP_PX = 300
ICON_RADIUS = 10
CASING_MIN_PX = 5
ROAD_FILL = {"road": (236, 238, 241), "safe_road": COLORS["white"]}
ROAD_CASING = {"road": (210, 216, 214), "safe_road": (150, 163, 168)}
ROAD_STYLES = {"Jl. raya": (4, 8, False), "Jl. perumahan": (2, 5, False), "Setapak/servis": (1, 2, True)}  # (min px, lebar m, putus-putus)


def text(surface, font, value, pos, color=COLORS["text"], anchor="topleft", rotation=0):
    """Tulis teks di layar. `anchor` menentukan titik mana dari teks yang ditaruh di `pos`; `rotation` dalam derajat."""
    if hasattr(font, "draw"):  # font Avenir (fonts.Face): ditulis langsung tanpa gambar perantara
        rect = pygame.Rect((0, 0), font.size(value, rotation))
        setattr(rect, anchor, pos)
        font.draw(surface, value, rect, color, rotation)
        return rect
    rendered = pygame.transform.rotate(font.render(value, True, color), rotation)
    rect = rendered.get_rect(**{anchor: pos})
    surface.blit(rendered, rect)
    return rect


def text_size(font, value, rotation=0):
    """Ukuran (lebar, tinggi) teks dalam piksel, termasuk kalau diputar."""
    if hasattr(font, "draw"):
        return font.size(value, rotation)
    return pygame.transform.rotate(font.render(value, True, (0, 0, 0)), rotation).get_size()


def parts(geom):
    """Pecah geometri gabungan (Multi...) jadi daftar bagian-bagiannya."""
    return list(getattr(geom, "geoms", [geom]))


# --- Transformasi koordinat meter (UTM) ke layar, dengan zoom dan geser ---
class MapView:
    """Kamera peta: mengubah koordinat meter (UTM) jadi piksel layar, lengkap dengan zoom dan geser."""

    def __init__(self, rect, bounds):
        """`bounds` = seluruh area data (satu kota): batas zoom terjauh. Tampilan awal diatur lewat fit()."""
        self.rect = rect
        self.min_scale = self.scale_for(bounds) * MIN_ZOOM
        self.home = bounds
        self.fit(bounds)

    def scale_for(self, bounds, padding=40):
        """Skala (piksel per meter) supaya kotak `bounds` muat di layar peta."""
        min_x, min_y, max_x, max_y = bounds
        return min((self.rect.w - 2 * padding) / max(max_x - min_x, 1), (self.rect.h - 2 * padding) / max(max_y - min_y, 1))

    def fit(self, bounds):
        """Atur kamera supaya kotak `bounds` (misal area rute) pas di tengah layar. Jadi tampilan "reset" juga."""
        self.home = bounds
        min_x, min_y, max_x, max_y = bounds
        self.scale = min(max(self.scale_for(bounds), self.min_scale), MAX_SCALE)
        self.offset_x = self.rect.centerx - (min_x + max_x) / 2 * self.scale
        self.offset_y = self.rect.centery + (min_y + max_y) / 2 * self.scale

    def reset(self):
        """Kembalikan tampilan ke area rute terakhir."""
        self.fit(self.home)

    def zoom_at(self, pos, factor):
        """Zoom sebesar `factor` dengan titik `pos` (posisi mouse) tetap di tempatnya."""
        scale = min(max(self.scale * factor, self.min_scale), MAX_SCALE)
        ratio = scale / self.scale
        self.offset_x = pos[0] + (self.offset_x - pos[0]) * ratio
        self.offset_y = pos[1] + (self.offset_y - pos[1]) * ratio
        self.scale = scale

    def pan(self, dx, dy):
        """Geser peta sejauh (dx, dy) piksel."""
        self.offset_x += dx
        self.offset_y += dy

    def resize(self, rect):
        """Jendela diubah ukurannya: pindahkan kamera ke kotak `rect` baru, titik tengah peta tetap sama."""
        center = self.to_world(*self.rect.center)
        self.rect = rect
        self.offset_x = rect.centerx - center[0] * self.scale
        self.offset_y = rect.centery + center[1] * self.scale

    def to_screen(self, x, y):
        """Koordinat meter -> piksel layar."""
        return self.offset_x + x * self.scale, self.offset_y - y * self.scale

    def to_world(self, x, y):
        """Piksel layar -> koordinat meter (kebalikan to_screen)."""
        return (x - self.offset_x) / self.scale, (self.offset_y - y) / self.scale

    def path(self, line):
        """Garis (LineString) -> daftar titik piksel."""
        return [self.to_screen(x, y) for x, y in line.coords]

    def visible_box(self):
        """Kotak area peta yang sedang terlihat (dalam meter), untuk melewati objek di luar layar."""
        left, top = self.to_world(self.rect.left, self.rect.top)
        right, bottom = self.to_world(self.rect.right, self.rect.bottom)
        return box(left, bottom, right, top)

    def width(self, min_px, width_m):
        """Lebar garis dalam piksel: mengikuti zoom (width_m meter), tapi tidak lebih tipis dari min_px."""
        return max(min_px, round(width_m * self.scale))

    def zoomed_in(self):
        """True kalau peta sudah cukup di-zoom untuk menampilkan nama toko dan jalan."""
        return self.scale >= LABEL_SCALE


# --- Layer statis: bangunan, zona buffer, dan jalan ---
def draw_buildings(surface, view, buildings, area):
    """Gambar bangunan sebagai poligon. Hanya bangunan yang masuk kotak `area` (bagian peta yang terlihat) yang digambar."""
    for polygon in buildings.geometry.iloc[buildings.sindex.query(area)]:
        pygame.draw.polygon(surface, COLORS["building"], view.path(polygon.exterior))


def draw_zone(surface, view, zone, color, alpha=38):
    """Gambar zona aman: poligon biru transparan (mode Radius) atau koridor di sepanjang jalan (mode Lewat jalan)."""
    layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    if zone.geom_type == "MultiLineString":
        width = max(ZONE_ROAD_MIN_PX, round(ZONE_ROAD_M * view.scale))
        for line in zone.geoms:
            draw_polyline(layer, view.path(line), (*color, alpha * 2), width)
        surface.blit(layer, (0, 0))
        return
    for polygon in parts(zone):
        if polygon.is_empty:
            continue
        pygame.draw.polygon(layer, (*color, alpha), view.path(polygon.exterior))
        for hole in polygon.interiors:
            pygame.draw.polygon(layer, (0, 0, 0, 0), view.path(hole))
        pygame.draw.lines(layer, (*color, 180), True, view.path(polygon.exterior), 1)
    surface.blit(layer, (0, 0))


def draw_dashes(surface, color, points, width):
    """Gambar garis putus-putus."""
    on, left = True, DASH_PX
    for a, b in zip(points[:-1], points[1:]):
        length, start = math.dist(a, b), 0.0
        while start < length:
            step = min(left, length - start)
            if on:
                p, q = start / length, (start + step) / length
                pygame.draw.line(surface, color, (a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p), (a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q), width)
            start, left = start + step, left - step
            if left <= 0:
                on, left = not on, DASH_PX


def draw_polyline(surface, points, color, width, dashed=False):
    """Gambar garis dari daftar titik piksel; ujung-ujungnya dibulatkan kalau garisnya tebal."""
    if dashed:
        draw_dashes(surface, color, points, width)
        return
    pygame.draw.lines(surface, color, False, points, width)
    if width > 2:
        for point in points:
            pygame.draw.circle(surface, color, point, width / 2)


def draw_line(surface, view, line, color, width, dashed=False):
    """Gambar garis dari geometri Shapely (bisa terdiri dari beberapa bagian)."""
    for part in parts(line):
        points = view.path(part)
        if len(points) >= 2:
            draw_polyline(surface, points, color, width, dashed)


def scale_label(meters):
    """Teks skala: 500 -> "500 m", 2000 -> "2 km"."""
    return f"{meters // 1000} km" if meters >= 1000 else f"{meters} m"


def draw_scale_bar(surface, view, font):
    """Gambar skala jarak di pojok kanan bawah peta."""
    meters = max((m for m in SCALE_STEPS_M if m * view.scale <= SCALE_BAR_MAX_PX), default=SCALE_STEPS_M[0])
    length = meters * view.scale
    x, y = view.rect.right - 24 - length, view.rect.bottom - 22
    pygame.draw.line(surface, COLORS["text"], (x, y), (x + length, y), 3)
    for end in (x, x + length):
        pygame.draw.line(surface, COLORS["text"], (end, y - 5), (end, y), 2)
    text(surface, font, scale_label(meters), (x + length / 2, y - 6), anchor="midbottom")


def draw_boundary(surface, view, boundary):
    """Latar peta: wilayah kota berwarna terang, di luar kota abu-abu (tidak ada data jalan di sana)."""
    surface.fill(COLORS["outside"])
    for polygon in parts(boundary):
        pygame.draw.polygon(surface, COLORS["background"], view.path(polygon.exterior))
        for hole in polygon.interiors:
            pygame.draw.polygon(surface, COLORS["outside"], view.path(hole))
    for polygon in parts(boundary):
        draw_dashes(surface, COLORS["muted"], view.path(polygon.exterior), 1)


def draw_base(surface, view, data, scene, font):
    """Gambar lapisan dasar yang jarang berubah: latar, bangunan, zona, jalan (jalan aman lebih gelap), dan nama jalan.

    Level of detail: makin jauh di-zoom, makin sedikit yang digambar (jalan kecil dan bangunan disembunyikan),
    supaya peta satu kota tetap ringan.
    """
    draw_boundary(surface, view, data.boundary)
    area = view.visible_box()
    if view.scale >= BUILDING_MIN_SCALE:
        draw_buildings(surface, view, data.buildings, area)
    draw_zone(surface, view, scene.zone, COLORS["zone"])
    shown = [name for name, scale in ROAD_MIN_SCALE.items() if view.scale >= scale]
    for edges, key in ((data.edges, "road"), (scene.safe_edges, "safe_road")):
        visible = edges.iloc[edges.sindex.query(area)]
        for road_class, group in visible[visible["road_class"].isin(shown)].groupby("road_class"):
            min_px, width_m, dashed = ROAD_STYLES[road_class]
            width = view.width(min_px, width_m)
            if dashed or width < CASING_MIN_PX:
                for line in group.geometry:
                    draw_line(surface, view, line, COLORS[key], width, dashed)
                continue
            for color, extra in ((ROAD_CASING[key], 2), (ROAD_FILL[key], 0)):
                for line in group.geometry:
                    draw_line(surface, view, line, color, width + extra)
    if view.zoomed_in():
        draw_road_names(surface, view, data.edges.iloc[data.edges.sindex.query(area)], font)


class MapLayer:
    """Peta dasar (bangunan, zona, jalan) yang sudah digambar dan disimpan, supaya geser dan zoom terasa lancar.

    Menggambar ribuan ruas jalan itu berat, jadi peta dasar tidak digambar ulang tiap frame:
    - Digambar sedikit lebih luas dari layar (MARGIN_PX di tiap sisi). Saat peta digeser, gambar yang
      sudah ada cukup dipindah. Baru digambar ulang kalau geserannya melewati batas itu.
    - Saat zoom, gambar lama diperbesar/diperkecil dulu sebagai pratinjau, lalu digambar ulang dengan
      tajam setelah scroll berhenti sebentar.
    """

    MARGIN_PX = 400

    def __init__(self, rect):
        self.resize(rect)

    def resize(self, rect):
        """Siapkan kanvas seukuran peta + margin di tiap sisi."""
        self.surface = pygame.Surface((rect.w + 2 * self.MARGIN_PX, rect.h + 2 * self.MARGIN_PX)).convert()
        self.dirty = True

    def render(self, view, data, scene, font):
        """Gambar ulang peta dasar untuk posisi kamera sekarang."""
        canvas = copy.copy(view)
        canvas.rect = self.surface.get_rect()
        canvas.offset_x = view.offset_x - view.rect.x + self.MARGIN_PX
        canvas.offset_y = view.offset_y - view.rect.y + self.MARGIN_PX
        draw_base(self.surface, canvas, data, scene, font)
        self.offset, self.scale, self.dirty = (canvas.offset_x, canvas.offset_y), view.scale, False

    def zooming(self, view):
        """True kalau kamera sudah di-zoom sejak peta dasar terakhir digambar."""
        return abs(view.scale / self.scale - 1) > 1e-9

    def blit(self, screen, view):
        """Tempel peta dasar ke layar sesuai kamera sekarang. False kalau gambarnya tidak lagi menutup layar peta."""
        ratio = view.scale / self.scale
        x, y = view.offset_x - self.offset[0] * ratio, view.offset_y - self.offset[1] * ratio
        if not self.zooming(view):
            if not self.surface.get_rect(topleft=(x, y)).contains(view.rect):
                return False
            screen.blit(self.surface, (x, y))
            return True
        # Pratinjau zoom: ambil bagian kanvas yang tampil di layar, lalu ubah ukurannya
        source = pygame.Rect((view.rect.x - x) / ratio, (view.rect.y - y) / ratio, view.rect.w / ratio + 2, view.rect.h / ratio + 2)
        source = source.clip(self.surface.get_rect())
        screen.fill(COLORS["outside"], view.rect)
        if source.w > 0 and source.h > 0:
            scaled = pygame.transform.scale(self.surface.subsurface(source), (round(source.w * ratio), round(source.h * ratio)))
            screen.blit(scaled, (x + source.x * ratio, y + source.y * ratio))
        return True


def draw_road_names(surface, view, edges, font):
    """Tulis nama jalan di tengah ruas, miring mengikuti jalan, tanpa saling menimpa."""
    placed, by_name = [], {}
    named = edges[edges["road_name"].notna()]
    for name, line in sorted(zip(named["road_name"], named.geometry), key=lambda row: -row[1].length):
        center = view.to_screen(*line.interpolate(0.5, normalized=True).coords[0])
        if not view.rect.collidepoint(center) or font.size(name)[0] + 20 > line.length * view.scale:
            continue
        if any(math.dist(center, other) < ROAD_LABEL_GAP_PX for other in by_name.get(name, [])):
            continue
        a = view.to_screen(*line.interpolate(line.length / 2 - 2).coords[0])
        b = view.to_screen(*line.interpolate(line.length / 2 + 2).coords[0])
        angle = (math.degrees(math.atan2(a[1] - b[1], b[0] - a[0])) + 90) % 180 - 90
        rect = pygame.Rect((0, 0), text_size(font, name, angle))
        rect.center = center
        if rect.collidelist(placed) != -1:
            continue
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):  # tepi putih supaya terbaca di atas jalan
            text(surface, font, name, (center[0] + dx, center[1] + dy), COLORS["white"], "center", angle)
        text(surface, font, name, center, COLORS["text"], "center", angle)
        placed.append(rect)
        by_name.setdefault(name, []).append(center)


# --- Rute dengan panah arah ---
def draw_arrow(surface, view, line, distance, color, size=8):
    """Gambar satu panah arah di titik `distance` meter sepanjang rute."""
    center = view.to_screen(*line.interpolate(distance).coords[0])
    ahead = view.to_screen(*line.interpolate(distance + 3).coords[0])
    ux, uy = unit(ahead[0] - center[0], ahead[1] - center[1])
    nx, ny = -uy, ux
    tip = (center[0] + ux * size, center[1] + uy * size)
    back = (center[0] - ux * size * 0.6, center[1] - uy * size * 0.6)
    triangle = [tip, (back[0] + nx * size * 0.7, back[1] + ny * size * 0.7), (back[0] - nx * size * 0.7, back[1] - ny * size * 0.7)]
    pygame.draw.polygon(surface, color, triangle)
    pygame.draw.polygon(surface, COLORS["white"], triangle, 1)


def draw_route(surface, view, line, color, width, dashed=False, arrows=True):
    """Gambar rute beserta panah arah di sepanjang garisnya (jarak antar panah ikut zoom)."""
    draw_line(surface, view, line, color, width, dashed)
    if not arrows:
        return
    every = max(ARROW_EVERY_M, ARROW_GAP_PX / view.scale)
    distance = every / 2
    while distance < line.length - 3:
        draw_arrow(surface, view, line, distance, color)
        distance += every


# --- Titik: hidrasi, landmark, pelari ---
def draw_icon(surface, kind, center, radius):
    """Gambar ikon titik hidrasi: lingkaran berwarna dengan gambar gelas/keranjang, atau tanda X kalau ditutup."""
    x, y = center
    s, white = radius * 0.45, COLORS["white"]
    pygame.draw.circle(surface, COLORS[kind], center, radius)
    pygame.draw.circle(surface, white, center, radius, 2)
    if kind == "closed":
        pygame.draw.line(surface, white, (x - s, y - s), (x + s, y + s), 2)
        pygame.draw.line(surface, white, (x - s, y + s), (x + s, y - s), 2)
    elif kind == "Kedai minuman":
        pygame.draw.polygon(surface, white, [(x - s, y - s * 0.6), (x + s, y - s * 0.6), (x + s * 0.7, y + s * 1.2), (x - s * 0.7, y + s * 1.2)])
        pygame.draw.line(surface, white, (x + s * 0.2, y - s * 0.6), (x + s * 0.6, y - s * 1.6), 2)
    elif kind == "Restoran":  # piring: lingkaran putih dengan lingkaran berwarna di dalamnya
        pygame.draw.circle(surface, white, center, s * 1.5)
        pygame.draw.circle(surface, COLORS[kind], center, s * 0.9)
    else:
        pygame.draw.polygon(surface, white, [(x - s * 1.2, y - s * 0.2), (x + s * 1.2, y - s * 0.2), (x + s * 0.8, y + s * 1.1), (x - s * 0.8, y + s * 1.1)])
        pygame.draw.arc(surface, white, (x - s * 0.7, y - s * 1.3, s * 1.4, s * 2), 0, math.pi, 2)


def draw_points(surface, view, points, closed, font, highlight=None):
    """Gambar titik hidrasi yang terlihat (dan namanya kalau peta di-zoom). `highlight` diberi lingkaran penanda.

    Saat peta di-zoom sangat jauh, titik hanya digambar sebagai bulatan kecil.
    """
    placed = []
    visible = points.iloc[points.sindex.query(view.visible_box())]
    for name, kind, geom in zip(visible["name"], visible["kind"], visible.geometry):
        x, y = view.to_screen(geom.x, geom.y)
        key = "closed" if name in closed else kind
        if view.scale < ICON_MIN_SCALE:
            pygame.draw.circle(surface, COLORS[key], (x, y), 3)
            continue
        radius = ICON_RADIUS if view.scale >= SMALL_ICON_SCALE else SMALL_ICON_RADIUS
        if name == highlight:
            pygame.draw.circle(surface, COLORS["hydration_path"], (x, y), radius + 5, 3)
        draw_icon(surface, key, (x, y), radius)
        if view.zoomed_in():
            draw_label(surface, font, name, (x + ICON_RADIUS + 4, y), COLORS[key], placed)


def draw_label(surface, font, value, pos, color, placed=None):
    """Gambar label bernama di atas kotak putih. Dilewati kalau menimpa label lain di `placed`."""
    rect = pygame.Rect((0, 0), text_size(font, value))
    rect.midleft = pos
    if placed is not None:
        if rect.collidelist(placed) != -1:
            return
        placed.append(rect)
    pygame.draw.rect(surface, COLORS["white"], rect.inflate(8, 4), border_radius=4)
    text(surface, font, value, rect.topleft, color)


def stop_marks(count, loop):
    """Tanda tiap stop di peta dan panel: A (awal), 1, 2, ... (stop), B (akhir). Rute muter: akhirnya juga A."""
    return ["A", *(str(i) for i in range(1, count - 1)), "A" if loop else "B"]


def draw_marker(surface, center, mark, font, radius=11):
    """Gambar satu penanda stop: lingkaran gelap berisi huruf/angka."""
    pygame.draw.circle(surface, COLORS["landmark"], center, radius)
    pygame.draw.circle(surface, COLORS["white"], center, radius, 2)
    text(surface, font, mark, center, COLORS["white"], anchor="center")


def draw_stops(surface, view, marked, font, bold_font):
    """Gambar tempat yang sudah dipilih di peta beserta namanya. `marked` = daftar (stop, tanda A/1/2/B)."""
    for stop, mark in marked:
        x, y = view.to_screen(stop.point.x, stop.point.y)
        draw_marker(surface, (x, y), mark, bold_font)
        draw_label(surface, font, stop.name, (x + 16, y), COLORS["text"])


def draw_runner(surface, view, position):
    """Gambar pelari (titik ungu dengan lingkaran muda di sekelilingnya, supaya mudah ditemukan)."""
    x, y = view.to_screen(*position)
    pygame.draw.circle(surface, RUNNER_HALO, (x, y), 18)
    pygame.draw.circle(surface, COLORS["runner"], (x, y), 18, 2)
    pygame.draw.circle(surface, COLORS["runner"], (x, y), 8)
    pygame.draw.circle(surface, COLORS["white"], (x, y), 8, 3)


# --- Legenda yang selalu tampil di pojok peta ---
MAP_LEGEND = [
    ("line", "safe", "Rute aman minum"),
    ("line", "baseline", "Rute tercepat"),
    ("zone", "zone", "Dekat tempat minum"),
    ("icon", "Minimarket", "Tempat minum"),
    ("dot", "runner", "Kamu (saat simulasi)"),
    ("outside", "outside", "Di luar Surabaya (tanpa data)"),
]


def draw_map_legend(surface, rect, font):
    """Legenda ringkas di pojok kiri bawah peta: hanya arti warna yang paling penting."""
    row = 20
    box = pygame.Rect(rect.x + 16, rect.bottom - 16 - (len(MAP_LEGEND) * row + 16), 252, len(MAP_LEGEND) * row + 16)
    pygame.draw.rect(surface, COLORS["white"], box, border_radius=8)
    pygame.draw.rect(surface, COLORS["line"], box, 1, border_radius=8)
    for i, (shape, key, label) in enumerate(MAP_LEGEND):
        x, y = box.x + 14, box.y + 18 + i * row
        if shape == "line":
            draw_polyline(surface, [(x, y), (x + 22, y)], COLORS[key], 5)
        elif shape == "zone":
            pygame.draw.rect(surface, (210, 234, 242), (x, y - 6, 22, 12), border_radius=3)
            pygame.draw.rect(surface, COLORS[key], (x, y - 6, 22, 12), 1, border_radius=3)
        elif shape == "outside":
            pygame.draw.rect(surface, COLORS[key], (x, y - 6, 22, 12), border_radius=3)
            pygame.draw.rect(surface, COLORS["muted"], (x, y - 6, 22, 12), 1, border_radius=3)
        elif shape == "icon":
            draw_icon(surface, key, (x + 11, y), 8)
        else:
            pygame.draw.circle(surface, COLORS[key], (x + 11, y), 7)
            pygame.draw.circle(surface, COLORS["white"], (x + 11, y), 7, 2)
        text(surface, font, label, (x + 32, y), anchor="midleft")

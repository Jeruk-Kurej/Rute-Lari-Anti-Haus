"""Semua urusan menggambar peta: kamera, jalan, zona, rute, ikon titik hidrasi, dan label nama."""
import math

import pygame
from shapely.geometry import box

from .runner import unit

COLORS = {
    "background": (246, 244, 239),
    "zone": (76, 155, 232),
    "road": (196, 201, 206),
    "safe_road": (110, 122, 132),
    "baseline": (224, 123, 57),
    "safe": (30, 142, 90),
    "Minimarket": (214, 40, 57),
    "Supermarket": (150, 30, 70),
    "Kedai minuman": (123, 79, 191),
    "closed": (160, 160, 160),
    "landmark": (27, 31, 35),
    "runner": (0, 102, 204),
    "hydration_path": (0, 160, 200),
    "trail": (200, 40, 160),
    "reroute": (232, 168, 0),
    "text": (27, 31, 35),
    "muted": (110, 116, 122),
    "white": (255, 255, 255),
}
ARROW_EVERY_M = 120
SCALE_STEPS_M = (5, 10, 20, 50, 100, 200, 500, 1000, 2000)
SCALE_BAR_MAX_PX = 160
MIN_ZOOM, MAX_ZOOM = 0.8, 60
DASH_PX = 6
ZONE_ROAD_M, ZONE_ROAD_MIN_PX = 40, 6
LABEL_ZOOM = 3
ROAD_LABEL_GAP_PX = 300
ICON_RADIUS = 10
CASING_MIN_PX = 5
ROAD_FILL = {"road": (236, 238, 241), "safe_road": COLORS["white"]}
ROAD_CASING = {"road": (210, 214, 219), "safe_road": (128, 140, 152)}
ROAD_STYLES = {"Jl. raya": (4, 8, False), "Jl. perumahan": (2, 5, False), "Setapak/servis": (1, 2, True)}  # (min px, lebar m, putus-putus)


def text(surface, font, value, pos, color=COLORS["text"], anchor="topleft"):
    """Tulis teks di layar. `anchor` menentukan titik mana dari teks yang ditaruh di `pos`."""
    rendered = font.render(value, True, color)
    rect = rendered.get_rect(**{anchor: pos})
    surface.blit(rendered, rect)
    return rect


def parts(geom):
    """Pecah geometri gabungan (Multi...) jadi daftar bagian-bagiannya."""
    return list(getattr(geom, "geoms", [geom]))


# --- Transformasi koordinat meter (UTM) ke layar, dengan zoom dan geser ---
class MapView:
    """Kamera peta: mengubah koordinat meter (UTM) jadi piksel layar, lengkap dengan zoom dan geser."""

    def __init__(self, rect, bounds, padding=24):
        """Atur kamera supaya seluruh peta (bounds) muat di dalam kotak `rect`."""
        min_x, min_y, max_x, max_y = bounds
        self.rect = rect
        self.fit_scale = min((rect.w - 2 * padding) / (max_x - min_x), (rect.h - 2 * padding) / (max_y - min_y))
        self.fit_offset = (
            rect.x + (rect.w - (max_x - min_x) * self.fit_scale) / 2 - min_x * self.fit_scale,
            rect.y + (rect.h + (max_y - min_y) * self.fit_scale) / 2 + min_y * self.fit_scale,
        )
        self.reset()

    def reset(self):
        """Kembalikan zoom dan posisi ke tampilan awal."""
        self.scale = self.fit_scale
        self.offset_x, self.offset_y = self.fit_offset

    def zoom_at(self, pos, factor):
        """Zoom sebesar `factor` dengan titik `pos` (posisi mouse) tetap di tempatnya."""
        scale = min(max(self.scale * factor, self.fit_scale * MIN_ZOOM), self.fit_scale * MAX_ZOOM)
        ratio = scale / self.scale
        self.offset_x = pos[0] + (self.offset_x - pos[0]) * ratio
        self.offset_y = pos[1] + (self.offset_y - pos[1]) * ratio
        self.scale = scale

    def pan(self, dx, dy):
        """Geser peta sejauh (dx, dy) piksel."""
        self.offset_x += dx
        self.offset_y += dy

    def to_screen(self, x, y):
        """Koordinat meter -> piksel layar."""
        return self.offset_x + x * self.scale, self.offset_y - y * self.scale

    def path(self, line):
        """Garis (LineString) -> daftar titik piksel."""
        return [self.to_screen(x, y) for x, y in line.coords]

    def visible_box(self):
        """Kotak area peta yang sedang terlihat (dalam meter), untuk melewati objek di luar layar."""
        return box(
            (self.rect.left - self.offset_x) / self.scale, (self.offset_y - self.rect.bottom) / self.scale,
            (self.rect.right - self.offset_x) / self.scale, (self.offset_y - self.rect.top) / self.scale,
        )

    def width(self, min_px, width_m):
        """Lebar garis dalam piksel: mengikuti zoom (width_m meter), tapi tidak lebih tipis dari min_px."""
        return max(min_px, round(width_m * self.scale))

    def zoomed_in(self):
        """True kalau peta sudah cukup di-zoom untuk menampilkan nama toko dan jalan."""
        return self.scale >= self.fit_scale * LABEL_ZOOM


# --- Layer statis: zona buffer dan jalan ---
def draw_zone(surface, view, zone, color, alpha=55):
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


def draw_scale_bar(surface, view, font):
    """Gambar skala jarak di pojok kiri bawah peta."""
    meters = max((m for m in SCALE_STEPS_M if m * view.scale <= SCALE_BAR_MAX_PX), default=SCALE_STEPS_M[0])
    x, y = view.rect.x + 20, view.rect.bottom - 20
    length = meters * view.scale
    pygame.draw.line(surface, COLORS["text"], (x, y), (x + length, y), 3)
    text(surface, font, f"{meters} m", (x + length / 2, y - 4), anchor="midbottom")


def draw_base(surface, view, data, scene, font):
    """Gambar lapisan dasar yang jarang berubah: latar, zona, semua jalan (jalan aman lebih gelap), dan nama jalan."""
    surface.fill(COLORS["background"])
    draw_zone(surface, view, scene.zone, COLORS["zone"])
    area = view.visible_box()
    for edges, key in ((data.edges, "road"), (scene.safe_edges, "safe_road")):
        visible = edges.iloc[edges.sindex.query(area)]
        for road_class, group in visible.groupby("road_class"):
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
    draw_scale_bar(surface, view, font)


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
        label = pygame.transform.rotate(font.render(name, True, COLORS["text"]), angle)
        halo = pygame.transform.rotate(font.render(name, True, COLORS["white"]), angle)
        rect = label.get_rect(center=center)
        if rect.collidelist(placed) != -1:
            continue
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            surface.blit(halo, rect.move(dx, dy))
        surface.blit(label, rect)
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


def draw_route(surface, view, line, color, width, dashed=False):
    """Gambar rute beserta panah arah di sepanjang garisnya."""
    draw_line(surface, view, line, color, width, dashed)
    distance = ARROW_EVERY_M / 2
    while distance < line.length - 3:
        draw_arrow(surface, view, line, distance, color)
        distance += ARROW_EVERY_M


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
    else:
        pygame.draw.polygon(surface, white, [(x - s * 1.2, y - s * 0.2), (x + s * 1.2, y - s * 0.2), (x + s * 0.8, y + s * 1.1), (x - s * 0.8, y + s * 1.1)])
        pygame.draw.arc(surface, white, (x - s * 0.7, y - s * 1.3, s * 1.4, s * 2), 0, math.pi, 2)


def draw_points(surface, view, points, closed, font, highlight=None):
    """Gambar semua titik hidrasi (dan namanya kalau peta di-zoom). `highlight` diberi lingkaran penanda."""
    placed = []
    for name, kind, geom in zip(points["name"], points["kind"], points.geometry):
        x, y = view.to_screen(geom.x, geom.y)
        if name == highlight:
            pygame.draw.circle(surface, COLORS["hydration_path"], (x, y), ICON_RADIUS + 5, 3)
        draw_icon(surface, "closed" if name in closed else kind, (x, y), ICON_RADIUS)
        if view.zoomed_in():
            draw_label(surface, font, name, (x + ICON_RADIUS + 4, y), COLORS["closed" if name in closed else kind], placed)


def draw_label(surface, font, value, pos, color, placed=None):
    """Gambar label bernama di atas kotak putih. Dilewati kalau menimpa label lain di `placed`."""
    label = font.render(value, True, color)
    rect = label.get_rect(midleft=pos)
    if placed is not None:
        if rect.collidelist(placed) != -1:
            return
        placed.append(rect)
    pygame.draw.rect(surface, COLORS["white"], rect.inflate(8, 4), border_radius=4)
    surface.blit(label, rect)


def draw_landmarks(surface, view, landmarks, start, end, font, bold_font):
    """Gambar landmark. Titik awal dan akhir ditandai khusus dan diberi label tebal."""
    for name, geom in zip(landmarks["name"], landmarks.geometry):
        x, y = view.to_screen(geom.x, geom.y)
        if name in (start, end):
            pygame.draw.circle(surface, COLORS["landmark"], (x, y), 9)
            pygame.draw.circle(surface, COLORS["white"], (x, y), 9, 2)
            draw_label(surface, bold_font, f"{'Awal' if name == start else 'Akhir'} · {name}", (x + 14, y), COLORS["text"])
        else:
            diamond = [(x, y - 7), (x + 7, y), (x, y + 7), (x - 7, y)]
            pygame.draw.polygon(surface, COLORS["white"], diamond)
            pygame.draw.polygon(surface, COLORS["landmark"], diamond, 2)
            draw_label(surface, font, name, (x + 12, y), COLORS["muted"])


def draw_runner(surface, view, position):
    """Gambar pelari (titik biru)."""
    x, y = view.to_screen(*position)
    pygame.draw.circle(surface, COLORS["runner"], (x, y), 8)
    pygame.draw.circle(surface, COLORS["white"], (x, y), 8, 3)

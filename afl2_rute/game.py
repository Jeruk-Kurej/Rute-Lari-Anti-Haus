"""Aplikasi utama: loop pygame, input mouse/keyboard, dan penghubung antara data, analisis, dan tampilan."""
import math

import pygame
import shapely
from shapely.geometry import LineString

from . import config
from .analysis import RoutePlanner
from .panel import Panel, meters
from .render import (
    COLORS, MapView, draw_base, draw_landmarks, draw_points, draw_route, draw_runner,
)
from .network import join
from .runner import Runner, unit

WINDOW_SIZE = (1240, 780)
MAP_WIDTH = 820
RUNNER_SPEED_MPS = 80
POINT_PICK_PX = 11
DRAG_MIN_PX = 4
ZOOM_PER_NOTCH = 1.1
FOLLOW_MARGIN_PX = 60
TRAIL_STEP_M = 2
OFF_ROUTE_M = 15
ARRIVE_M = 15
FONT = "Arial,Helvetica"
MOVE_KEYS = {pygame.K_w: (0, 1), pygame.K_s: (0, -1), pygame.K_a: (-1, 0), pygame.K_d: (1, 0)}


class App:
    """Aplikasi utama. Menyimpan pengaturan pengguna, menghitung ulang hasil saat berubah, dan menggambar semuanya."""

    def __init__(self, data):
        """Buka jendela, siapkan font, kamera, panel, dan nilai awal (dua landmark pertama, toleransi default)."""
        pygame.init()
        pygame.display.set_caption("Generator Rute Lari Anti-Haus · Citraland Surabaya")
        self.screen = pygame.display.set_mode(WINDOW_SIZE)
        self.fonts = {
            "small": pygame.font.SysFont(FONT, 13),
            "body": pygame.font.SysFont(FONT, 15),
            "bold": pygame.font.SysFont(FONT, 15, bold=True),
            "title": pygame.font.SysFont(FONT, 20, bold=True),
        }
        self.data = data
        self.planner = RoutePlanner(data)
        self.map_rect = pygame.Rect(0, 0, MAP_WIDTH, WINDOW_SIZE[1])
        self.view = MapView(self.map_rect, data.edges.total_bounds)
        self.base = pygame.Surface(WINDOW_SIZE)
        self.panel = Panel(self, pygame.Rect(MAP_WIDTH, 0, WINDOW_SIZE[0] - MAP_WIDTH, WINDOW_SIZE[1]), self.fonts)

        self.names = data.landmarks["name"].tolist()
        self.start, self.end = self.names[0], self.names[1]
        self.tolerance = config.DEFAULT_TOLERANCE_M
        self.zone_mode = config.ZONE_MODES[0]
        self.closed = set()
        self.min_message = None
        self.drag = None
        self.trail, self.arrived, self.trail_stats, self.reroute = [], False, None, None
        self.refresh()
        self.reset_runner()

    # --- Perhitungan ulang saat input berubah ---
    def refresh(self):
        """Hitung ulang zona, rute terpendek vs anti-haus, dan tabel hasil. Dipanggil tiap pengaturan berubah."""
        self.scene = self.planner.build_scene(self.tolerance, self.closed, self.zone_mode)
        self.origin = self.planner.landmark_node(self.start)
        self.target = self.planner.landmark_node(self.end)
        self.comparison = self.planner.compare(self.scene, self.origin, self.target)
        routes = {"Baseline": self.comparison.baseline, "Anti-haus": self.comparison.safe}
        self.stats = {label: self.planner.stats(line, self.scene.points) for label, line in routes.items() if line is not None}
        self.to_target = self.planner.paths_to_target(self.scene, self.target)
        self.calculated, self.hit = False, None
        self.base_dirty = True
        self.update_trail()

    def select(self, which, name):
        """Ganti titik awal atau akhir. Kalau sama dengan lawannya, keduanya ditukar."""
        other = "end" if which == "start" else "start"
        if name == getattr(self, other):
            setattr(self, other, getattr(self, which))
        setattr(self, which, name)
        self.min_message = None
        self.refresh()
        self.reset_runner()

    def change_tolerance(self, direction):
        """Naik/turunkan toleransi satu langkah (direction = +1 atau -1), dalam batas pencarian."""
        limits = config.TOLERANCE_SEARCH_M
        self.tolerance = min(max(self.tolerance + direction * config.TOLERANCE_STEP_M, limits.start), limits[-1])
        self.refresh()

    def find_minimum_tolerance(self):
        """Cari toleransi terkecil yang membuat rute anti-haus ada, lalu terapkan."""
        found = self.planner.minimum_tolerance(self.origin, self.target, self.closed, self.zone_mode)
        if found is None:
            self.min_message = f"Toleransi minimum: tidak ada sampai {meters(config.TOLERANCE_SEARCH_M[-1])}"
            return
        self.min_message = f"Toleransi minimum agar rute ada: {meters(found)} (diterapkan)"
        self.tolerance = found
        self.refresh()

    def toggle_zone_mode(self):
        """Ganti mode zona antara Radius dan Lewat jalan."""
        modes = config.ZONE_MODES
        self.zone_mode = modes[(modes.index(self.zone_mode) + 1) % len(modes)]
        self.min_message = None
        self.refresh()

    def toggle_point(self, name):
        """Tutup titik hidrasi kalau sedang buka, atau buka kalau sedang tutup (skenario proposal)."""
        self.closed ^= {name}
        self.min_message = None
        self.refresh()

    def open_all(self):
        """Buka kembali semua titik hidrasi."""
        self.closed.clear()
        self.min_message = None
        self.refresh()

    # --- Pelari ---
    def reset_runner(self):
        """Kembalikan pelari ke titik awal dan hapus jejaknya."""
        self.runner = Runner(self.data.network, self.origin)
        self.calculated, self.hit = False, None
        self.trail, self.arrived, self.reroute = self.runner.trail(), False, None
        self.tracked_at = self.runner.position
        self.update_trail()

    def track_runner(self):
        """Catat jejak pelari tiap TRAIL_STEP_M meter dan cek apakah sudah sampai tujuan."""
        position = self.runner.position
        if self.arrived or math.dist(position, self.tracked_at) < TRAIL_STEP_M:
            return
        self.tracked_at = position
        self.trail = self.runner.trail()
        self.arrived = math.dist(position, self.data.network.xy(self.target)) <= ARRIVE_M
        self.update_trail()

    def update_trail(self):
        """Cek apakah pelari keluar rute anjuran. Kalau ya, buat rute baru dari posisinya dan hitung statistiknya."""
        planned = self.comparison.safe if self.comparison.safe is not None else self.comparison.baseline
        samples = shapely.get_coordinates(shapely.segmentize(LineString(self.trail), TRAIL_STEP_M)) if len(self.trail) > 1 else []
        off_route = len(samples) > 0 and shapely.distance(shapely.points(samples), planned).max() > OFF_ROUTE_M
        self.reroute = None
        if off_route and not self.arrived:
            runner = self.runner
            self.reroute = self.planner.reroute(self.scene, self.to_target, runner.u, runner.v, runner.s)
        line = join(self.trail, list(self.reroute.line.coords)) if self.reroute else self.trail
        self.trail_stats = self.planner.stats(LineString(line), self.scene.points) if off_route else None

    def calculate(self):
        """Tombol Hitung: cari titik hidrasi terdekat lewat jalan dari posisi pelari."""
        self.calculated = True
        runner = self.runner
        self.hit = self.planner.next_hydration(self.scene.points, runner.u, runner.v, runner.s)

    def point_at(self, pos):
        """Nama titik hidrasi yang ada di bawah posisi mouse `pos`, atau None."""
        if not self.map_rect.collidepoint(pos):
            return None
        for name, geom in zip(self.data.points["name"], self.data.points.geometry):
            x, y = self.view.to_screen(geom.x, geom.y)
            if (x - pos[0]) ** 2 + (y - pos[1]) ** 2 <= POINT_PICK_PX ** 2:
                return name
        return None

    # --- Input ---
    def handle(self, event):
        """Terima satu event pygame. False kalau program harus berhenti."""
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.KEYDOWN:
            return self.on_key(event.key)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.on_press(event.pos)
        elif event.type == pygame.MOUSEMOTION and self.drag:
            self.on_drag(event)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.on_release(event.pos)
        elif event.type == pygame.MOUSEWHEEL:
            self.on_wheel(event.precise_y)
        return True

    def on_key(self, key):
        """Tombol keyboard: H hitung, R reset pelari, 0 reset zoom, F1 atau / bantuan, Esc keluar."""
        if self.panel.help_open:
            self.panel.help_open = False
        elif key == pygame.K_ESCAPE:
            return False
        elif key == pygame.K_h:
            self.calculate()
        elif key == pygame.K_r:
            self.reset_runner()
        elif key == pygame.K_0:
            self.view.reset()
            self.base_dirty = True
        elif key in (pygame.K_F1, pygame.K_SLASH):
            self.panel.show_help()
        return True

    def on_press(self, pos):
        """Mouse ditekan: diteruskan ke panel, atau mulai geser peta."""
        if self.panel.help_open:
            self.panel.help_open = False
        elif not self.panel.click(pos) and self.map_rect.collidepoint(pos):
            self.drag = {"start": pos, "moved": False}

    def on_drag(self, event):
        """Geser peta mengikuti mouse (setelah bergerak lebih dari DRAG_MIN_PX)."""
        if not self.drag["moved"] and math.dist(event.pos, self.drag["start"]) < DRAG_MIN_PX:
            return
        self.drag["moved"] = True
        self.view.pan(*event.rel)
        self.base_dirty = True

    def on_release(self, pos):
        """Mouse dilepas tanpa menggeser: kalau mengenai titik hidrasi, titik itu ditutup/dibuka."""
        drag, self.drag = self.drag, None
        if drag and not drag["moved"]:
            name = self.point_at(pos)
            if name:
                self.toggle_point(name)

    def on_wheel(self, notches):
        """Scroll mouse di atas peta: zoom in/out."""
        mouse = pygame.mouse.get_pos()
        if self.map_rect.collidepoint(mouse):
            self.view.zoom_at(mouse, ZOOM_PER_NOTCH ** notches)
            self.base_dirty = True

    # --- Update dan gambar ---
    def update(self, dt):
        """Dipanggil tiap frame: gerakkan pelari sesuai tombol W/A/S/D yang sedang ditekan."""
        pressed = pygame.key.get_pressed()
        dx = sum(vector[0] for key, vector in MOVE_KEYS.items() if pressed[key])
        dy = sum(vector[1] for key, vector in MOVE_KEYS.items() if pressed[key])
        if dx or dy:
            self.runner.move(unit(dx, dy), RUNNER_SPEED_MPS * dt)
            self.track_runner()
            self.follow_runner()

    def follow_runner(self):
        """Geser peta kalau pelari mendekati tepi layar, supaya tetap terlihat."""
        x, y = self.view.to_screen(*self.runner.position)
        if not self.map_rect.inflate(-2 * FOLLOW_MARGIN_PX, -2 * FOLLOW_MARGIN_PX).collidepoint(x, y):
            self.view.pan(self.map_rect.centerx - x, self.map_rect.centery - y)
            self.base_dirty = True

    def draw(self):
        """Gambar satu frame: peta dasar, rute, titik, pelari, tooltip, lalu panel."""
        if self.base_dirty:
            draw_base(self.base, self.view, self.data, self.scene, self.fonts["small"])
            self.base_dirty = False
        mouse = pygame.mouse.get_pos()
        self.screen.set_clip(self.map_rect)
        self.screen.blit(self.base, self.map_rect, self.map_rect)
        view = self.view
        draw_route(self.screen, view, self.comparison.baseline, COLORS["baseline"], view.width(8, 5))
        if self.comparison.safe is not None:
            draw_route(self.screen, view, self.comparison.safe, COLORS["safe"], view.width(4, 2.5))
        if self.reroute is not None:
            draw_route(self.screen, view, self.reroute.line, COLORS["reroute"], view.width(4, 2.5))
        if self.trail_stats is not None:
            draw_route(self.screen, view, LineString(self.trail), COLORS["trail"], view.width(3, 1.5), dashed=True)
        if self.hit is not None and self.hit.path is not None:
            draw_route(self.screen, view, self.hit.path, COLORS["hydration_path"], view.width(3, 1.5))
        draw_landmarks(self.screen, self.view, self.data.landmarks, self.start, self.end, self.fonts["small"], self.fonts["bold"])
        draw_points(self.screen, self.view, self.data.points, self.closed, self.fonts["small"], self.hit.name if self.hit else None)
        draw_runner(self.screen, self.view, self.runner.position)
        self.draw_tooltip(mouse)
        self.screen.set_clip(None)
        self.panel.draw(self.screen, mouse)
        pygame.display.flip()

    def draw_tooltip(self, mouse):
        """Kotak kecil berisi nama, jenis, dan status buka/tutup saat mouse di atas titik hidrasi."""
        name = self.point_at(mouse)
        if name is None:
            return
        kind = self.data.points.set_index("name").at[name, "kind"]
        label = self.fonts["small"].render(f"{name} · {kind} · {'ditutup' if name in self.closed else 'buka'}", True, COLORS["white"])
        rect = label.get_rect(topleft=(mouse[0] + 14, mouse[1] - 24))
        pygame.draw.rect(self.screen, COLORS["text"], rect.inflate(12, 8), border_radius=4)
        self.screen.blit(label, rect)

    def run(self):
        """Loop utama: baca input, update, gambar, ulangi 60 kali per detik sampai jendela ditutup."""
        clock = pygame.time.Clock()
        running = True
        while running:
            dt = clock.tick(60) / 1000
            for event in pygame.event.get():
                running = running and self.handle(event)
            self.update(dt)
            self.draw()
        pygame.quit()

"""Aplikasi utama: loop pygame, input mouse/keyboard, dan penghubung antara data, analisis, dan tampilan."""
import math

import pygame
import shapely
from shapely.geometry import LineString, Point

from . import config
from .analysis import Comparison, RoutePlanner
from .fonts import load_fonts
from .network import join
from .panel import Panel, distance_text, meters
from .render import (
    COLORS, MapLayer, MapView, draw_points, draw_route, draw_runner, draw_scale_bar, draw_stops, stop_marks, text, text_size,
)
from .runner import Runner, unit
from .search import Place, PlaceIndex

SCREEN_MARGIN_PX = 80  # jendela awal = selebar layar, setinggi layar dikurangi menu bar dan judul jendela
WINDOW_MIN = (1100, 860)  # lebih pendek dari ini, isi panel tidak muat
PANEL_WIDTH = 440
RUNNER_SPEED_MPS = 80
POINT_PICK_PX = 11
DRAG_MIN_PX = 4
ZOOM_PER_NOTCH = 1.1
ZOOM_SETTLE_MS = 150  # setelah zoom berhenti selama ini, peta dasar digambar ulang dengan tajam
FOLLOW_MARGIN_PX = 60
TRAIL_STEP_M = 2
OFF_ROUTE_M = 15
ARRIVE_M = 15
VIEW_PADDING_M = 400
MOVE_KEYS = {pygame.K_w: (0, 1), pygame.K_s: (0, -1), pygame.K_a: (-1, 0), pygame.K_d: (1, 0)}


class App:
    """Aplikasi utama. Menyimpan pengaturan pengguna, menghitung ulang hasil saat berubah, dan menggambar semuanya."""

    def __init__(self, load):
        """Buka jendela, tampilkan layar memuat, muat data lewat `load()`, lalu siapkan rute awal bawaan."""
        pygame.init()
        pygame.key.set_repeat(400, 35)
        pygame.display.set_caption("Rute Lari Anti-Haus - Surabaya")
        screen = pygame.display.Info()
        size = (max(screen.current_w, WINDOW_MIN[0]), max(screen.current_h - SCREEN_MARGIN_PX, WINDOW_MIN[1]))
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.window = pygame.Window.from_display_module()
        self.window.minimum_size = WINDOW_MIN
        self.fullscreen = False
        self.fonts = load_fonts()
        self.show_message("Memuat peta Surabaya...")
        self.data = data = load()
        self.planner = RoutePlanner(data)
        self.places = PlaceIndex(data)
        width, height = self.screen.get_size()
        self.map_rect = pygame.Rect(PANEL_WIDTH, 0, width - PANEL_WIDTH, height)
        self.view = MapView(self.map_rect, data.edges.total_bounds)
        self.layer = MapLayer(self.map_rect)
        self.zoomed_at = 0
        self.cursor = pygame.SYSTEM_CURSOR_ARROW

        self.slots = [self.stop_from(self.places.find(name)) for name in config.DEFAULT_STOPS]  # awal, stop..., akhir
        self.active, self.loop, self.choice = len(self.slots) - 1, False, 0
        self.results, self.search_note = [], None
        self.tolerance = config.DEFAULT_TOLERANCE_M
        self.zone_mode = config.ZONE_MODES[0]
        self.closed = set()
        self.min_message = None
        self.drag, self.pending = None, None
        self.comparison, self.needs_input = Comparison(None, [], ""), True
        self.stats, self.trail_stats, self.nearest = {}, None, []
        self.simulating = False  # pelari hanya tampil dan bisa digerakkan saat simulasi lari
        self.panel = Panel(self, pygame.Rect(0, 0, PANEL_WIDTH, height), self.fonts)
        self.refresh(fit=True)

    def resize(self):
        """Jendela diubah ukurannya: peta melebar/menyempit, panel tetap di kiri dengan lebar yang sama."""
        self.screen = pygame.display.get_surface()
        width, height = self.screen.get_size()
        self.map_rect = pygame.Rect(PANEL_WIDTH, 0, width - PANEL_WIDTH, height)
        self.view.resize(self.map_rect)
        self.layer.resize(self.map_rect)
        self.panel.rect = pygame.Rect(0, 0, PANEL_WIDTH, height)

    def toggle_fullscreen(self):
        """Layar penuh / kembali ke jendela biasa (tombol F)."""
        if self.fullscreen:
            self.window.set_windowed()
        else:
            self.window.set_fullscreen(desktop=True)
        self.fullscreen = not self.fullscreen
        self.resize()

    def zoom(self, factor):
        """Tombol zoom di peta: perbesar/perkecil dari tengah peta."""
        self.view.zoom_at(self.map_rect.center, factor)
        self.zoomed_at = pygame.time.get_ticks()

    def recenter(self):
        """Tombol di peta: kembali menampilkan seluruh rute."""
        self.view.reset()
        self.layer.dirty = True

    def show_message(self, message):
        """Tampilkan satu kalimat di tengah layar (dipakai saat memuat data)."""
        self.screen.fill(COLORS["background"])
        text(self.screen, self.fonts["title"], message, self.screen.get_rect().center, anchor="center")
        pygame.display.flip()

    # --- Stop: awal, stop di tengah, akhir ---
    def stop_from(self, place):
        """Tempat hasil pencarian -> stop (titiknya ditempel jadi node di jalan terdekat)."""
        return self.planner.make_stop(place.name, place.kind, place.point)

    def route_stops(self):
        """Stop yang dipakai rute, berurutan (rute muter berakhir lagi di titik awal). Kosong kalau masih ada kotak yang belum diisi."""
        stops = self.slots[:-1] + ([self.slots[0]] if self.loop else [self.slots[-1]])
        return [] if any(stop is None for stop in stops) else stops

    def marked_stops(self):
        """(stop, tanda) untuk semua kotak yang sudah terisi, dipakai menggambar A/1/2/B di peta walau rute belum lengkap."""
        marks = stop_marks(len(self.slots), self.loop)
        last = len(self.slots) - 1
        return [(stop, mark) for i, (stop, mark) in enumerate(zip(self.slots, marks)) if stop is not None and not (self.loop and i == last)]

    def missing_message(self):
        """Kalimat yang menyebut kotak mana yang masih kosong."""
        if self.slots[0] is None:
            return "Isi kotak \"Mulai dari mana?\" dulu."
        if not self.loop and self.slots[-1] is None:
            return "Isi kotak \"Mau ke mana?\" dulu."
        return "Isi tempat singgah yang masih kosong, atau hapus barisnya."

    def clear_slot(self, index):
        """Kosongkan titik awal atau akhir (tombol x di kotaknya)."""
        self.slots[index] = None
        self.active = index
        self.min_message = None
        self.changed(fit=True)

    def set_active(self, index):
        """Pilih baris yang akan diisi oleh hasil pencarian berikutnya."""
        if not (self.loop and index == len(self.slots) - 1):
            self.active = index

    def add_stop(self):
        """Tambah baris stop kosong sebelum titik akhir, lalu langsung siap diisi lewat pencarian."""
        self.slots.insert(len(self.slots) - 1, None)
        self.active = len(self.slots) - 2
        self.panel.focus_row(self.active)

    def remove_stop(self, index):
        """Hapus satu stop di tengah rute."""
        del self.slots[index]
        self.active = min(self.active, len(self.slots) - 1)
        self.changed(fit=True)

    def move_stop(self, index, step):
        """Geser urutan stop di tengah rute (step -1 = naik, +1 = turun)."""
        other = index + step
        if 0 < other < len(self.slots) - 1:
            self.slots[index], self.slots[other] = self.slots[other], self.slots[index]
            self.changed()

    def toggle_loop(self):
        """Rute muter: nyala = rute kembali ke titik awal setelah semua stop."""
        self.loop = not self.loop
        if self.loop and self.active == len(self.slots) - 1:
            self.active = 0
        self.changed(fit=True)

    # --- Pencarian ---
    def placeholder(self, index):
        """Teks petunjuk untuk kotak isian kosong: dari mana, lewat mana, atau ke mana."""
        if index == 0:
            return "Mulai dari mana?"
        return "Mau ke mana?" if index == len(self.slots) - 1 else "Mau mampir ke mana?"

    def search_hint(self):
        """Teks petunjuk di kotak yang sedang diketik."""
        return "Ketik nama, atau klik di peta..."

    def on_search(self, query):
        """Setiap ketikan berubah: cari ulang di data lokal (kotak kosong = tidak ada hasil)."""
        self.results = self.places.search(query) if query.strip() else []
        self.search_note = None

    def submit_search(self, query):
        """Enter: pilih hasil teratas, atau cari online kalau di data lokal tidak ada."""
        if self.results:
            self.choose_result(0)
            return
        if len(query.strip()) < config.SEARCH_MIN_CHARS:
            return
        self.search_note = "Mencari lewat internet..."
        self.draw()  # tampilkan tulisan ini dulu, karena pencarian internet bisa makan waktu beberapa detik
        place, reason = self.places.search_online(query)
        if place is None:
            self.search_note = reason
            return
        self.place_at_active(place)

    def choose_result(self, index):
        """Klik hasil pencarian: tempat itu mengisi baris yang sedang aktif."""
        self.place_at_active(self.results[index])

    def place_at_active(self, place):
        """Isi baris aktif dengan tempat ini, kosongkan pencarian, lalu pindah ke baris kosong berikutnya (kalau ada)."""
        self.slots[self.active] = self.stop_from(place)
        empty = [i for i, stop in enumerate(self.slots) if stop is None]
        self.active = empty[0] if empty else self.active
        self.panel.search.focused, self.panel.search.value = False, ""
        if empty:
            self.panel.focus_row(self.active)
        self.min_message = None
        self.changed(fit=True)

    def result_detail(self, place):
        """Keterangan di kanan hasil pencarian: jenis tempat dan jaraknya (garis lurus) dari titik awal."""
        start = self.slots[0]
        if start is None or start.name == place.name:
            return place.kind
        return f"{place.kind}, {distance_text(start.point.distance(place.point))} dari {start.name}"

    # --- Perhitungan ulang saat input berubah ---
    def changed(self, fit=False):
        """Tandai bahwa hasil harus dihitung ulang. Hitungannya dijalankan setelah layar "Menghitung..." tergambar."""
        self.pending = {"fit": fit or (self.pending or {}).get("fit", False)}

    def refresh(self, fit=False):
        """Hitung ulang zona, rute terpendek vs anti-haus (dan alternatifnya), dan tabel hasil."""
        self.pending = None
        stops = self.route_stops()
        if not stops:  # ada kotak yang masih kosong: belum ada zona dan rute
            self.scene = self.planner.empty_scene()
            self.comparison, self.needs_input = Comparison(None, [], self.missing_message()), True
        else:
            self.scene = self.planner.build_scene(stops, self.tolerance, self.closed, self.zone_mode)
            if len({stop.node for stop in stops}) < 2:
                self.comparison = Comparison(None, [], "Rute kembali ke awal butuh minimal satu tempat singgah." if self.loop else "Pilih dua tempat yang berbeda.")
                self.needs_input = True
            else:
                self.comparison = self.planner.compare(self.scene, stops)
                self.needs_input = False
        self.choice = 0
        self.update_stats()
        shown = [stop.point for stop, _ in self.marked_stops()]
        if fit and shown:
            min_x, min_y, max_x, max_y = shapely.MultiPoint(shown).bounds
            self.view.fit((min_x - VIEW_PADDING_M, min_y - VIEW_PADDING_M, max_x + VIEW_PADDING_M, max_y + VIEW_PADDING_M))
        self.layer.dirty = True
        self.reset_runner()

    def update_stats(self):
        """Angka tabel hasil untuk rute terpendek dan rute anti-haus yang sedang dipilih."""
        points, comparison = self.scene.points, self.comparison
        planned = self.planned()
        self.stats = {
            "Baseline": self.planner.stats(comparison.baseline.line, points) if comparison.baseline else None,
            "Anti-haus": self.planner.stats(planned.line, points, with_drinks=True) if comparison.options else None,
        }

    def planned(self):
        """Rute anti-haus yang sedang dipilih (Rute 1/2/3), atau None kalau tidak ada."""
        options = self.comparison.options
        return options[self.choice] if options else None

    def choose_option(self, index):
        """Pilih salah satu rute anti-haus (Rute 1 = terpendek, sisanya alternatif)."""
        self.choice = index
        self.update_stats()
        self.reset_runner()

    def change_tolerance(self, direction):
        """Naik/turunkan toleransi satu langkah (direction = +1 atau -1), dalam batas pencarian."""
        limits = config.TOLERANCE_SEARCH_M
        self.tolerance = min(max(self.tolerance + direction * config.TOLERANCE_STEP_M, limits.start), limits[-1])
        self.min_message = None
        self.changed()

    def find_minimum_tolerance(self):
        """Cari toleransi terkecil yang membuat rute anti-haus ada, lalu terapkan."""
        stops = self.route_stops()
        if len(stops) < 2:
            return
        self.show_busy()
        found = self.planner.minimum_tolerance(stops, self.closed, self.zone_mode)
        if found is None:
            self.min_message = f"Sampai {meters(config.TOLERANCE_SEARCH_M[-1])} pun belum ada rute aman minum."
            return
        self.min_message = f"Jarak terkecil yang masih bisa: {meters(found)} (sudah dipakai)."
        self.tolerance = found
        self.changed()

    def set_zone_mode(self, mode):
        """Pilih cara ukur jarak ke tempat minum: Radius (garis lurus, buffer) atau Lewat jalan."""
        if mode != self.zone_mode:
            self.zone_mode = mode
            self.min_message = None
            self.changed()

    def advice(self):
        """Penjelasan saat rute aman minum tidak ada: apa masalahnya dan apa yang bisa dilakukan pengguna."""
        if self.needs_input:
            return self.comparison.status
        return f"{self.comparison.status} Perbesar jaraknya dengan tombol +, atau cari jarak terkecil yang masih bisa."

    def trail_note(self):
        """Keterangan singkat asal angka "Jalur larimu"."""
        if self.arrived:
            return "Kamu sudah sampai."
        if self.reroute is None:
            return "Belum ada jalan aman dari posisimu."
        if self.reroute.via_outside:
            return "Kembali ke area aman dulu (garis kuning)."
        return "Ikuti garis kuning ke tujuan berikutnya."

    def toggle_point(self, name):
        """Tutup titik hidrasi kalau sedang buka, atau buka kalau sedang tutup (skenario proposal)."""
        self.closed ^= {name}
        self.min_message = None
        self.changed()

    def open_all(self):
        """Buka kembali semua titik hidrasi."""
        self.closed.clear()
        self.min_message = None
        self.changed()

    # --- Pelari ---
    def reset_runner(self):
        """Kembalikan pelari ke titik awal dan hapus jejaknya."""
        stops = self.route_stops()
        self.calculated, self.nearest, self.hit = False, [], None
        if not stops:  # rute belum lengkap: belum ada pelari
            self.runner, self.simulating = None, False
            self.trail, self.arrived, self.reroute, self.trail_stats = [], False, None, None
            return
        self.runner = Runner(self.data.network, stops[0].node)
        self.trail, self.arrived, self.reroute = self.runner.trail(), False, None
        self.next_stop = 1  # indeks stop berikutnya yang dituju pelari
        self.tracked_at = self.runner.position
        self.aim()
        self.update_trail()

    def aim(self):
        """Siapkan jarak dari tiap persimpangan aman ke stop berikutnya (dipakai rute ulang)."""
        stops = self.route_stops()
        target = stops[self.next_stop].node if self.next_stop < len(stops) else stops[-1].node
        self.to_target = self.planner.paths_to_target(self.scene, target)

    def track_runner(self):
        """Catat jejak pelari tiap TRAIL_STEP_M meter, dan cek apakah ia sudah sampai di stop berikutnya."""
        position = self.runner.position
        if self.arrived or math.dist(position, self.tracked_at) < TRAIL_STEP_M:
            return
        self.tracked_at = position
        self.trail = self.runner.trail()
        stops = self.route_stops()
        if math.dist(position, self.data.network.xy(stops[self.next_stop].node)) <= ARRIVE_M:
            self.next_stop += 1
            self.arrived = self.next_stop >= len(stops)
            if not self.arrived:
                self.aim()
        self.update_trail()

    def update_trail(self):
        """Cek apakah pelari keluar rute anjuran. Kalau ya, buat rute baru dari posisinya dan hitung statistiknya.

        Rute baru menuju stop berikutnya, lalu melanjutkan potongan rute anjuran yang tersisa.
        """
        plan = self.planned() or self.comparison.baseline
        self.reroute, self.trail_stats = None, None
        if plan is None or len(self.trail) < 2:
            return
        samples = shapely.points(shapely.get_coordinates(shapely.segmentize(LineString(self.trail), TRAIL_STEP_M)))
        if shapely.distance(samples, plan.line).max() <= OFF_ROUTE_M:
            return
        line = self.trail
        if not self.arrived:
            runner = self.runner
            self.reroute = self.planner.reroute(self.scene, self.to_target, runner.u, runner.v, runner.s)
            if self.reroute is not None:
                rest = [list(leg.coords) for leg in plan.legs[self.next_stop:]]
                line = join(self.trail, list(self.reroute.line.coords), *rest)
        self.trail_stats = self.planner.stats(LineString(line), self.scene.points)

    def start_simulation(self):
        """Mulai simulasi lari: pelari muncul di titik A dan bisa digerakkan dengan W/A/S/D."""
        if self.runner is None:
            return
        self.simulating = True
        self.reset_runner()

    def stop_simulation(self):
        """Selesai simulasi: pelari, jejak, dan daftar tempat minum terdekat disembunyikan."""
        self.simulating = False
        self.reset_runner()

    def calculate(self):
        """Tombol Hitung: daftar titik hidrasi terdekat lewat jalan dari posisi pelari."""
        if self.runner is None:
            return
        self.calculated = True
        runner = self.runner
        open_points = self.data.points[~self.data.points["name"].isin(self.closed)]
        self.nearest = self.planner.nearest_hydrations(open_points, runner.u, runner.v, runner.s)
        self.hit = 0 if self.nearest else None
        self.simulating = True

    def point_at(self, pos):
        """Nama titik hidrasi yang ada di bawah posisi mouse `pos`, atau None."""
        if not self.map_rect.collidepoint(pos) or self.view.scale < 0.05:
            return None
        visible = self.data.points.iloc[self.data.points.sindex.query(self.view.visible_box())]
        for name, geom in zip(visible["name"], visible.geometry):
            x, y = self.view.to_screen(geom.x, geom.y)
            if (x - pos[0]) ** 2 + (y - pos[1]) ** 2 <= POINT_PICK_PX ** 2:
                return name
        return None

    # --- Input ---
    def handle(self, event):
        """Terima satu event pygame. False kalau program harus berhenti."""
        if event.type == pygame.QUIT:
            return False
        if event.type == pygame.VIDEORESIZE:
            self.resize()
            return True
        if self.panel.search.handle(event):
            return True
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
        """Tombol keyboard: H hitung, R reset pelari, 0 kembali ke rute, / cari, F1 bantuan, Esc keluar."""
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
            self.layer.dirty = True
        elif key == pygame.K_SLASH:
            self.panel.focus_row(self.active)
        elif key == pygame.K_F1:
            self.panel.show_help()
        elif key == pygame.K_f:
            self.toggle_fullscreen()
        return True

    def on_press(self, pos):
        """Mouse ditekan: diteruskan ke panel, atau mulai geser peta. Kalau sebuah kotak sedang diisi, klik di peta memilih titik."""
        if self.panel.help_open:
            self.panel.help_open = False
            return
        filling = self.panel.search.focused
        if not self.panel.click(pos) and self.map_rect.collidepoint(pos):
            self.panel.search.focused = filling  # klik atau geser di peta tidak menutup kotak yang sedang diisi
            self.drag = {"start": pos, "moved": False, "pick": filling}

    def on_drag(self, event):
        """Geser peta mengikuti mouse (setelah bergerak lebih dari DRAG_MIN_PX)."""
        if not self.drag["moved"] and math.dist(event.pos, self.drag["start"]) < DRAG_MIN_PX:
            return
        self.drag["moved"] = True
        self.view.pan(*event.rel)  # peta dasar cukup dipindah, tidak digambar ulang (lihat MapLayer)

    def on_release(self, pos):
        """Mouse dilepas tanpa menggeser: memilih titik (kalau sedang mengisi kotak), atau menutup/membuka titik hidrasi yang diklik."""
        drag, self.drag = self.drag, None
        if drag and not drag["moved"]:
            if drag["pick"]:
                self.pick_point(pos)
            elif (name := self.point_at(pos)):
                self.toggle_point(name)

    def pick_point(self, pos):
        """Klik di peta saat mengisi kotak: titik itu jadi isi kotaknya. Mengklik ikon toko memilih toko itu."""
        name = self.point_at(pos)
        if name:
            row = self.data.points[self.data.points["name"] == name].iloc[0]
            place = Place(name, row["kind"], row.geometry)
        else:
            place = self.places.at_point(Point(*self.view.to_world(*pos)))
        if place is None:
            self.min_message = "Titik itu di luar Surabaya, belum ada data jalannya."
            return
        self.place_at_active(place)

    def on_wheel(self, notches):
        """Scroll mouse di atas peta: zoom in/out."""
        mouse = pygame.mouse.get_pos()
        if self.map_rect.collidepoint(mouse):
            self.view.zoom_at(mouse, ZOOM_PER_NOTCH ** notches)
            self.zoomed_at = pygame.time.get_ticks()

    # --- Update dan gambar ---
    def update(self, dt):
        """Dipanggil tiap frame: gerakkan pelari sesuai tombol W/A/S/D (kecuali sedang mengetik di pencarian)."""
        if self.panel.search.focused or self.runner is None:
            return
        pressed = pygame.key.get_pressed()
        dx = sum(vector[0] for key, vector in MOVE_KEYS.items() if pressed[key])
        dy = sum(vector[1] for key, vector in MOVE_KEYS.items() if pressed[key])
        if dx or dy:
            if not self.simulating:  # menekan W/A/S/D langsung memulai simulasi
                self.start_simulation()
            self.runner.move(unit(dx, dy), RUNNER_SPEED_MPS * dt)
            self.track_runner()
            self.follow_runner()

    def follow_runner(self):
        """Geser peta kalau pelari mendekati tepi layar, supaya tetap terlihat."""
        x, y = self.view.to_screen(*self.runner.position)
        if not self.map_rect.inflate(-2 * FOLLOW_MARGIN_PX, -2 * FOLLOW_MARGIN_PX).collidepoint(x, y):
            self.view.pan(self.map_rect.centerx - x, self.map_rect.centery - y)

    def draw(self):
        """Gambar satu frame: peta dasar, rute, titik, stop, pelari, tooltip, lalu panel."""
        view, comparison, layer = self.view, self.comparison, self.layer
        settled = pygame.time.get_ticks() - self.zoomed_at > ZOOM_SETTLE_MS
        if layer.dirty or (layer.zooming(view) and settled):
            layer.render(view, self.data, self.scene, self.fonts["small"])
        mouse = pygame.mouse.get_pos()
        self.screen.set_clip(self.map_rect)
        if not layer.blit(self.screen, view):  # sudah digeser terlalu jauh: gambar ulang
            layer.render(view, self.data, self.scene, self.fonts["small"])
            layer.blit(self.screen, view)
        if comparison.baseline is not None:
            draw_route(self.screen, view, comparison.baseline.line, COLORS["baseline"], view.width(8, 5))
        if comparison.options:  # hanya rute yang dipilih; alternatif lain dipilih lewat panel
            draw_route(self.screen, view, self.planned().line, COLORS["safe"], view.width(4, 2.5))
        hit = None
        if self.simulating:
            if self.reroute is not None:
                draw_route(self.screen, view, self.reroute.line, COLORS["reroute"], view.width(4, 2.5))
            if self.trail_stats is not None:
                draw_route(self.screen, view, LineString(self.trail), COLORS["trail"], view.width(3, 1.5), dashed=True)
            hit = self.nearest[self.hit] if self.hit is not None else None
            if hit is not None and hit.path is not None:
                draw_route(self.screen, view, hit.path, COLORS["hydration_path"], view.width(3, 1.5))
        draw_points(self.screen, view, self.data.points, self.closed, self.fonts["small"], hit.name if hit else None)
        draw_stops(self.screen, view, self.marked_stops(), self.fonts["small"], self.fonts["bold"])
        if self.simulating:
            draw_runner(self.screen, view, self.runner.position)
        draw_scale_bar(self.screen, view, self.fonts["small"])
        self.draw_tooltip(mouse)
        self.draw_pick_banner(mouse)
        if self.pending is not None:
            self.draw_busy()
        self.screen.set_clip(None)
        self.panel.draw(self.screen, mouse)
        pygame.display.flip()

    def draw_pick_banner(self, mouse):
        """Saat sebuah kotak sedang diisi: tulisan di atas peta dan kursor silang, tanda bahwa klik di peta memilih titik."""
        picking = self.panel.search.focused
        crosshair = picking and self.map_rect.collidepoint(mouse) and not self.panel.help_open
        wanted = pygame.SYSTEM_CURSOR_CROSSHAIR if crosshair else pygame.SYSTEM_CURSOR_ARROW
        if wanted != self.cursor:
            pygame.mouse.set_cursor(wanted)
            self.cursor = wanted
        if not picking:
            return
        font, value = self.fonts["bold"], f"Klik di peta untuk memilih {self.slot_name(self.active)}"
        rect = pygame.Rect((0, 0), text_size(font, value))
        rect.midtop = (self.map_rect.centerx, self.map_rect.y + 18)
        pygame.draw.rect(self.screen, COLORS["text"], rect.inflate(32, 18), border_radius=18)
        text(self.screen, font, value, rect.topleft, COLORS["white"])

    def slot_name(self, index):
        """Sebutan sebuah kotak untuk pengguna: titik mulai (A), tempat singgah, atau tujuan (B)."""
        if index == 0:
            return "titik mulai (A)"
        return "tujuan (B)" if index == len(self.slots) - 1 else f"tempat singgah {index}"

    def draw_busy(self):
        """Kotak "Menghitung rute..." di tengah peta, tampil selama hitungan berjalan."""
        font, value = self.fonts["bold"], "Menghitung rute..."
        rect = pygame.Rect((0, 0), text_size(font, value))
        rect.center = self.map_rect.center
        pygame.draw.rect(self.screen, COLORS["text"], rect.inflate(32, 20), border_radius=8)
        text(self.screen, font, value, rect.topleft, COLORS["white"])

    def show_busy(self):
        """Gambar kotak "Menghitung..." sekarang juga (untuk hitungan yang langsung dijalankan, misal toleransi minimum)."""
        self.draw_busy()
        pygame.display.flip()

    def draw_tooltip(self, mouse):
        """Kotak kecil berisi nama, jenis, dan status buka/tutup saat mouse di atas titik hidrasi."""
        name = self.point_at(mouse)
        if name is None:
            return
        kind = self.data.points.set_index("name").at[name, "kind"]
        action = "klik untuk buka lagi" if name in self.closed else "klik untuk tandai tutup"
        font, value = self.fonts["small"], f"{name} ({kind}), {action}"
        rect = pygame.Rect((mouse[0] + 14, mouse[1] - 24), text_size(font, value))
        pygame.draw.rect(self.screen, COLORS["text"], rect.inflate(12, 8), border_radius=4)
        text(self.screen, font, value, rect.topleft, COLORS["white"])

    def run(self):
        """Loop utama: baca input, update, gambar, lalu hitung ulang kalau ada perubahan. Ulangi 60 kali per detik."""
        clock = pygame.time.Clock()
        running = True
        while running:
            dt = clock.tick(60) / 1000
            for event in pygame.event.get():
                running = running and self.handle(event)
            self.update(dt)
            self.draw()
            if self.pending is not None:
                self.refresh(**self.pending)
        pygame.quit()

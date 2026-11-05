"""Panel kiri: isian rute (dari, lewat, ke), jarak maksimal ke tempat minum, ringkasan hasil, daftar tempat minum,
simulasi lari, kontrol peta, dan layar cara pakai. Semua teks memakai bahasa sehari-hari, bukan istilah teknis."""
import pygame

from . import config
from .render import COLORS, draw_icon, draw_map_legend, draw_marker, draw_polyline, stop_marks, text
from .widgets import BORDER, HOVER, Button, TextInput

ACTIVE = (224, 238, 248)
PAD = 24
ROW_PX = 42
FIELD_H = 36
RESULT_PX = 44
LIST_PX = 26
HELP_STEPS = [
    ("Tentukan rute", "Klik kotak \"Dari\" dan \"Ke\", ketik nama tempat (kampus, mal, taman, atau nama jalan), lalu pilih hasilnya. Mau mampir dulu? Klik \"Tambah tempat singgah\"."),
    ("Atur jarak ke tempat minum", "Pilih seberapa jauh kamu boleh berada dari minimarket atau kedai minuman. Makin kecil, makin aman, tapi rutenya bisa lebih panjang."),
    ("Ikuti rute biru", "Garis biru selalu lewat jalan yang dekat tempat minum, garis oranye adalah rute tercepat sebagai pembanding. Toko tutup? Klik ikonnya di peta. Mau mencoba berlari? Klik \"Coba lari (simulasi)\"."),
]
HOW_IT_WORKS = ("Cara kerjanya: setiap tempat minum diberi lingkaran sejauh jarak pilihanmu (buffer), semua lingkaran digabung "
                "(union), lalu hanya jalan yang seluruhnya di dalam gabungan itu yang boleh dilewati (within). Rute terpendek "
                "di jalan-jalan itu dicari dengan algoritma Dijkstra.")
SIMULATION_HINT = "Gerakkan titik ungu dengan tombol W A S D. Tekan R untuk mulai ulang dari titik A."
ZONE_NAMES = {"Radius": "Garis lurus", "Lewat jalan": "Lewat jalan"}
ZONE_HINTS = {
    "Radius": "Jarak udara dari toko (lingkaran). Cepat dihitung, tapi jalan di seberang sungai atau pagar bisa dianggap dekat.",
    "Lewat jalan": "Jarak berjalan kaki menyusuri jalan sampai toko. Lebih realistis, biasanya butuh jarak lebih besar.",
}
DIM = (120, 128, 132)  # pengali warna untuk meredupkan layar di belakang kartu cara pakai


def meters(value):
    """Format angka jadi teks meter, misal 1250 -> "1.250 m". None -> "-"."""
    return "-" if value is None else f"{value:,.0f} m".replace(",", ".")


def kilometers(value):
    """Format jarak jadi km dengan satu desimal, misal 1250 -> "1,3 km"."""
    return f"{value / 1000:.1f} km".replace(".", ",")


def distance_text(value):
    """Jarak yang enak dibaca: di bawah 1 km dalam meter, di atasnya dalam km."""
    return meters(value) if value < 1000 else kilometers(value)


def wrap(font, value, width):
    """Pecah teks panjang jadi beberapa baris yang masing-masing muat dalam `width` piksel."""
    lines = [""]
    for word in value.split():
        candidate = f"{lines[-1]} {word}".strip()
        if font.size(candidate)[0] <= width or not lines[-1]:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


def fit(font, value, width):
    """Potong teks dengan "..." kalau lebih lebar dari `width` piksel."""
    if font.size(value)[0] <= width:
        return value
    while value and font.size(value + "...")[0] > width:
        value = value[:-1]
    return value + "..."


def paragraph(surface, font, value, pos, width, color=COLORS["text"], line_px=None):
    """Tulis teks beberapa baris (dipecah otomatis). Hasilnya posisi y di bawah baris terakhir."""
    x, y = pos
    step = line_px or font.get_linesize()
    for line in wrap(font, value, width):
        text(surface, font, line, (x, y), color)
        y += step
    return y


# --- Panel ---
class Panel:
    """Panel kiri. Posisi isinya dihitung ulang tiap frame (layout), karena jumlah stop dan ukuran jendela bisa berubah."""

    def __init__(self, app, rect, fonts):
        self.app, self.rect, self.fonts = app, rect, fonts
        self.help_open = True
        self.search = TextInput(pygame.Rect(0, 0, 10, FIELD_H), app.search_hint, app.on_search, app.submit_search)
        self.layout()

    def show_help(self):
        """Buka layar cara pakai."""
        self.help_open = True

    def focus_row(self, index):
        """Klik kotak isian sebuah baris: baris itu aktif dan siap diketik (langsung muncul tempat favorit)."""
        self.app.set_active(index)
        self.search.focused = True
        self.search.set("")

    # --- Tata letak ---
    def layout(self):
        """Hitung posisi semua bagian panel dan tombol peta berdasarkan kondisi aplikasi sekarang."""
        app = self.app
        self.x, self.width = self.rect.x + PAD, self.rect.w - 2 * PAD
        x, right = self.x, self.x + self.width
        self.buttons, self.rows, self.nearest_rows = [], [], []
        self.buttons.append(Button(pygame.Rect(right - 32, 20, 32, 32), "?", self.show_help))

        # 1. Dari, lewat, ke
        self.route_y = 96
        y = self.route_y + 32
        last = len(app.slots) - 1
        for i in range(len(app.slots)):
            middle = 0 < i < last
            field = pygame.Rect(x + 34, y, self.width - 34 - (96 if middle else 0), FIELD_H)
            self.rows.append((i, (x + 12, y + FIELD_H // 2), field))
            if middle:
                for j, (icon, action) in enumerate((("up", lambda i=i: app.move_stop(i, -1)),
                                                    ("down", lambda i=i: app.move_stop(i, 1)),
                                                    ("close", lambda i=i: app.remove_stop(i)))):
                    self.buttons.append(Button(pygame.Rect(field.right + 6 + j * 30, y + 4, 28, 28), "", action, icon=icon))
            y += ROW_PX
        if self.search.focused:
            self.search.rect = next(field for i, _, field in self.rows if i == app.active)
        body = self.fonts["body"]
        add_w, loop_w = body.size("Tambah tempat singgah")[0] + 34, body.size("Kembali ke awal")[0] + 34
        self.buttons += [
            Button(pygame.Rect(x + 26, y, add_w, 30), "Tambah tempat singgah", app.add_stop,
                   lambda: last - 1 < config.MAX_STOPS, icon="plus", style="link"),
            Button(pygame.Rect(right - loop_w, y, loop_w, 30), "Kembali ke awal", app.toggle_loop,
                   icon=lambda: "check_on" if app.loop else "check_off", style="link"),
        ]

        # 2. Jarak maksimal ke tempat minum
        self.limit_y = y + 50
        self.control_y = self.limit_y + 32
        self.buttons += [
            Button(pygame.Rect(x, self.control_y, 36, 36), "", lambda: app.change_tolerance(-1), icon="minus"),
            Button(pygame.Rect(x + 132, self.control_y, 36, 36), "", lambda: app.change_tolerance(1), icon="plus"),
            Button(pygame.Rect(right - 176, self.control_y + 3, 176, 30), "Cari jarak terkecil", app.find_minimum_tolerance, style="link"),
        ]

        # 3. Hasil
        self.result_y = self.control_y + 36 + 34 + (20 if app.min_message else 0)
        options = app.comparison.options
        if options:
            chips_y = self.result_y + 52 + len(wrap(self.fonts["small"], self.comparison_note(), self.width - 28)) * 18 + 12
            if len(options) > 1:
                for i, option in enumerate(options):
                    self.buttons.append(Button(pygame.Rect(x + 96 + i * 98, chips_y, 92, 30), kilometers(option.line.length),
                                               lambda i=i: app.choose_option(i)))
                chips_y += 40
            self.result_h = chips_y - self.result_y
        else:
            lines = len(wrap(self.fonts["small"], app.advice(), self.width - 32))
            self.result_h = 52 + lines * 18 + (0 if app.needs_input else 46)
            if not app.needs_input:
                self.buttons.append(Button(pygame.Rect(x + 16, self.result_y + self.result_h - 48, 220, 34), "Cari jarak terkecil",
                                           app.find_minimum_tolerance, style="primary"))

        # Bagian bawah: pengaturan ukur jarak, dan tempat yang ditandai tutup
        self.footer_y = self.rect.bottom - (92 if app.closed else 56)
        segment = 100
        for i, mode in enumerate(config.ZONE_MODES):
            self.buttons.append(Button(pygame.Rect(right - (2 - i) * segment, self.footer_y + 14, segment, 30), ZONE_NAMES[mode],
                                       lambda mode=mode: app.set_zone_mode(mode), style="segment"))
        if app.closed:
            self.buttons.append(Button(pygame.Rect(right - 100, self.footer_y + 52, 100, 30), "Buka semua", app.open_all, style="link"))

        # 4. Tempat minum yang dilewati, atau simulasi lari
        self.list_y = self.result_y + self.result_h + 22
        if app.simulating:
            self.buttons.append(Button(pygame.Rect(right - 80, self.list_y - 4, 80, 28), "Selesai", app.stop_simulation, style="link"))
            calc_y = self.list_y + 30 + len(wrap(self.fonts["small"], SIMULATION_HINT, self.width)) * 18 + 6
            self.buttons.append(Button(pygame.Rect(x, calc_y, self.width, 34), "Cari tempat minum terdekat (H)", app.calculate, style="primary"))
            self.nearest_y = calc_y + 44
            room = max((self.footer_y - 8 - self.nearest_y) // LIST_PX, 0)
            for i in range(min(len(app.nearest), room)):
                self.nearest_rows.append((i, pygame.Rect(x, self.nearest_y + i * LIST_PX, self.width, LIST_PX)))
        else:
            self.simulate_y = self.footer_y - 50
            self.buttons.append(Button(pygame.Rect(x, self.simulate_y, self.width, 36), "Coba lari (simulasi)", app.start_simulation))

        # Tombol di peta: zoom dan kembali ke rute
        area = app.map_rect
        controls = (("plus", lambda: app.zoom(1.4)), ("minus", lambda: app.zoom(1 / 1.4)), ("center", app.recenter))
        for j, (icon, action) in enumerate(controls):
            self.buttons.append(Button(pygame.Rect(area.right - 52, area.y + 16 + j * 42, 36, 36), "", action, icon=icon))

    def comparison_note(self):
        """Satu kalimat pembanding: rute tercepat lebih pendek, tapi bisa jauh dari tempat minum."""
        stats, fastest = self.app.stats.get("Anti-haus"), self.app.stats.get("Baseline")
        if stats is None or fastest is None:
            return ""
        note = f"Rute tercepat {kilometers(fastest.length_m)}, tapi bisa {meters(fastest.farthest_m)} dari tempat minum."
        extra = stats.length_m - fastest.length_m
        return note + (f" Rute aman {distance_text(extra)} lebih panjang." if extra > 1 else "")

    # --- Klik ---
    def results(self):
        """Hasil pencarian yang sedang tampil (hanya saat sebuah kotak sedang diketik)."""
        return self.app.results if self.search.focused else []

    def result_rows(self):
        """Posisi tiap baris hasil pencarian, tepat di bawah kotak yang sedang diketik."""
        field = self.search.rect
        top = field.bottom + 4
        return [(i, pygame.Rect(field.x, top + i * RESULT_PX, self.x + self.width - field.x, RESULT_PX)) for i in range(len(self.results()))]

    def click(self, pos):
        """Proses klik di panel atau tombol peta. True kalau klik dipakai, False kalau diteruskan ke peta."""
        app = self.app
        for i, row in self.result_rows():
            if row.collidepoint(pos):
                app.choose_result(i)
                return True
        if self.search.focused and self.search.rect.collidepoint(pos):
            return True
        self.search.focused = False
        self.layout()
        for button in self.buttons:
            if button.hit(pos):
                button.action()
                return True
        for i, _, field in self.rows:
            if field.collidepoint(pos) and not (app.loop and i == len(app.slots) - 1):
                self.focus_row(i)
                return True
        for i, row in self.nearest_rows:
            if row.collidepoint(pos):
                app.hit = i
                return True
        return self.rect.collidepoint(pos)

    # --- Gambar ---
    def draw(self, surface, mouse):
        """Gambar panel kiri, tombol peta, legenda, hasil pencarian, dan layar cara pakai."""
        self.layout()
        fonts, x = self.fonts, self.x
        pygame.draw.rect(surface, COLORS["white"], self.rect)
        pygame.draw.line(surface, COLORS["line"], self.rect.topright, self.rect.bottomright)
        text(surface, fonts["title"], "Rute Lari Anti-Haus", (x, 20))
        text(surface, fonts["small"], "Rute lari yang selalu dekat tempat beli minum.", (x, 54), COLORS["muted"])

        self.draw_route(surface, mouse)
        self.draw_limit(surface)
        self.draw_result(surface)
        clip = surface.get_clip()
        surface.set_clip(pygame.Rect(self.rect.x, self.list_y - 12, self.rect.w, max(self.footer_y - self.list_y + 8, 0)))
        if self.app.simulating:
            self.draw_simulation(surface, mouse)
        else:
            self.draw_drinks(surface)
        surface.set_clip(clip)
        self.draw_footer(surface)
        for button in self.buttons:
            self.draw_button(surface, button, mouse)
        draw_map_legend(surface, self.app.map_rect, fonts["small"])
        self.draw_zone_hint(surface, mouse)
        if self.search.focused:
            self.search.draw(surface, fonts["body"])
            self.draw_results(surface, mouse)
        if self.help_open:
            self.draw_help(surface)

    def draw_button(self, surface, button, mouse):
        """Gambar tombol. Gaya "segment" (pilihan) digambar di sini karena bergantung pada pilihan aktif."""
        fonts = self.fonts
        if button.style == "segment":
            selected = ZONE_NAMES[self.app.zone_mode] == button.text()
            fill = COLORS["safe"] if selected else (HOVER if button.rect.collidepoint(mouse) else COLORS["white"])
            pygame.draw.rect(surface, fill, button.rect, border_radius=6)
            pygame.draw.rect(surface, COLORS["safe"] if selected else BORDER, button.rect, 1, border_radius=6)
            text(surface, fonts["small"], button.text(), button.rect.center, COLORS["white"] if selected else COLORS["text"], anchor="center")
            return
        button.draw(surface, fonts["body"], mouse)
        planned = self.app.planned()
        if planned is not None and button.style == "ghost" and button.text() == kilometers(planned.line.length):
            pygame.draw.rect(surface, COLORS["safe"], button.rect, 2, border_radius=8)

    def draw_zone_hint(self, surface, mouse):
        """Keterangan kecil di atas tombol "Garis lurus" / "Lewat jalan" saat mouse diarahkan ke sana."""
        for button in self.buttons:
            if button.style == "segment" and button.rect.collidepoint(mouse):
                mode = next(mode for mode, name in ZONE_NAMES.items() if name == button.text())
                lines = wrap(self.fonts["small"], ZONE_HINTS[mode], 260)
                box = pygame.Rect(0, 0, 284, 16 + len(lines) * 18)
                box.bottomright = (self.x + self.width, button.rect.y - 8)
                pygame.draw.rect(surface, COLORS["text"], box, border_radius=8)
                paragraph(surface, self.fonts["small"], ZONE_HINTS[mode], (box.x + 12, box.y + 8), 260, COLORS["white"], line_px=18)

    def draw_route(self, surface, mouse):
        """Bagian rute: penanda A/1/2/B tersambung garis titik-titik, dan kotak isian tiap tempat."""
        app, fonts = self.app, self.fonts
        text(surface, fonts["section"], "Mau lari dari mana ke mana?", (self.x, self.route_y))
        marks = stop_marks(len(app.slots), app.loop)
        centers = [center for _, center, _ in self.rows]
        for (ax, ay), (_, by) in zip(centers, centers[1:]):
            for dot_y in range(int(ay) + 14, int(by) - 12, 6):
                pygame.draw.circle(surface, COLORS["muted"], (ax, dot_y), 1)
        last = len(app.slots) - 1
        for i, center, field in self.rows:
            draw_marker(surface, center, marks[i], fonts["small"], radius=11)
            if self.search.focused and i == app.active:
                continue
            looped = app.loop and i == last
            hover = field.collidepoint(mouse) and not looped
            pygame.draw.rect(surface, COLORS["surface"] if looped else HOVER if hover else COLORS["white"], field, border_radius=8)
            pygame.draw.rect(surface, BORDER, field, 1, border_radius=8)
            stop = app.slots[i]
            if looped:
                label, color = f"Kembali ke {app.slots[0].name}", COLORS["muted"]
            elif stop is None:
                label, color = self.app.placeholder(i), COLORS["muted"]
            else:
                label, color = stop.name, COLORS["text"]
            text(surface, fonts["body"], fit(fonts["body"], label, field.w - 24), (field.x + 12, field.centery), color, anchor="midleft")

    def draw_limit(self, surface):
        """Bagian jarak maksimal ke tempat minum (toleransi)."""
        app, fonts, x = self.app, self.fonts, self.x
        text(surface, fonts["section"], "Seberapa jauh boleh dari tempat minum?", (x, self.limit_y))
        text(surface, fonts["big_value"], meters(app.tolerance), (x + 84, self.control_y + 18), COLORS["text"], anchor="center")
        if app.min_message:
            text(surface, fonts["small"], fit(fonts["small"], app.min_message, self.width), (x, self.control_y + 44), COLORS["muted"])

    def draw_result(self, surface):
        """Ringkasan hasil: panjang rute aman minum (angka besar), lalu satu kalimat pembanding dengan rute tercepat."""
        app, fonts, x, y = self.app, self.fonts, self.x, self.result_y
        pygame.draw.line(surface, COLORS["line"], (x, y - 16), (x + self.width, y - 16))
        stats = app.stats.get("Anti-haus")
        if stats is None:
            box = pygame.Rect(x, y, self.width, self.result_h)
            pygame.draw.rect(surface, COLORS["warning"], box, border_radius=10)
            text(surface, fonts["bold"], "Belum ada rute" if app.needs_input else "Belum ada rute aman minum", (x + 16, y + 14))
            paragraph(surface, fonts["small"], app.advice(), (x + 16, y + 40), self.width - 32, COLORS["text"], line_px=18)
            return
        number = text(surface, fonts["big"], kilometers(stats.length_m), (x, y - 6), COLORS["safe"])
        text(surface, fonts["bold"], "Rute aman minum", (number.right + 14, number.centery - 10), anchor="midleft")
        text(surface, fonts["small"], f"paling jauh {meters(stats.farthest_m)} dari tempat minum", (number.right + 14, number.centery + 11),
             COLORS["muted"], anchor="midleft")
        note_y = y + 52
        draw_polyline(surface, [(x, note_y + 9), (x + 18, note_y + 9)], COLORS["baseline"], 4)
        paragraph(surface, fonts["small"], self.comparison_note(), (x + 28, note_y), self.width - 28, COLORS["text"], line_px=18)
        if len(app.comparison.options) > 1:
            chip = next(b for b in self.buttons if b.style == "ghost" and b.text() == kilometers(app.comparison.options[0].line.length))
            text(surface, fonts["small"], "Pilihan rute", (x, chip.rect.centery), COLORS["muted"], anchor="midleft")

    def draw_drinks(self, surface):
        """Tempat minum yang dilewati rute aman (jarak dari titik mulai), dan jarak terpanjang tanpa tempat minum."""
        app, fonts, x, y = self.app, self.fonts, self.x, self.list_y
        pygame.draw.line(surface, COLORS["line"], (x, y - 12), (x + self.width, y - 12))
        text(surface, fonts["section"], "Tempat minum yang kamu lewati", (x, y))
        stats = app.stats.get("Anti-haus")
        if stats is None:
            paragraph(surface, fonts["small"], "Muncul setelah rute aman minum ditemukan.", (x, y + 28), self.width, COLORS["muted"])
            return
        top, bottom = y + 30, self.simulate_y - 30
        if not stats.drinks:
            paragraph(surface, fonts["small"], f"Tidak ada toko tepat di pinggir rute (sejauh {config.ON_ROUTE_M} m), tapi semua jalannya tetap dalam jarak pilihanmu.",
                      (x, top), self.width, COLORS["muted"], line_px=18)
        room = max((bottom - top) // LIST_PX, 1)
        shown = room if len(stats.drinks) <= room else room - 1  # sisakan satu baris untuk "dan n tempat lainnya"
        for i, drink in enumerate(stats.drinks[:shown]):
            row_y = top + i * LIST_PX
            text(surface, fonts["bold"], kilometers(drink.along_m), (x, row_y))
            draw_icon(surface, drink.kind, (x + 76, row_y + 10), 8)
            text(surface, fonts["body"], fit(fonts["body"], drink.name, self.width - 96), (x + 92, row_y))
        if len(stats.drinks) > shown:
            text(surface, fonts["small"], f"dan {len(stats.drinks) - shown} tempat lainnya", (x + 92, top + shown * LIST_PX), COLORS["muted"])
        text(surface, fonts["small"], f"Jarak terpanjang tanpa tempat minum: {kilometers(stats.longest_dry_m)}", (x, bottom + 4), COLORS["muted"])

    def draw_simulation(self, surface, mouse):
        """Simulasi lari: cara menggerakkan pelari, jalur larimu, dan daftar tempat minum terdekat dari posisinya."""
        app, fonts, x, y = self.app, self.fonts, self.x, self.list_y
        pygame.draw.line(surface, COLORS["line"], (x, y - 12), (x + self.width, y - 12))
        text(surface, fonts["section"], "Simulasi lari", (x, y))
        paragraph(surface, fonts["small"], SIMULATION_HINT, (x, y + 30), self.width, COLORS["muted"], line_px=18)
        if app.trail_stats is not None:
            pygame.draw.circle(surface, COLORS["trail"], (x + 6, self.nearest_y - 2 - 9), 5)
        if not app.calculated:
            if app.trail_stats is not None:
                text(surface, fonts["small"], fit(fonts["small"], f"Jalur larimu {kilometers(app.trail_stats.length_m)}. {app.trail_note()}", self.width - 18),
                     (x + 18, self.nearest_y - 20), COLORS["text"])
            return
        if not app.nearest:
            text(surface, fonts["body"], f"Tidak ada tempat minum buka dalam {kilometers(config.NEAREST_SEARCH_M)}.", (x, self.nearest_y))
            return
        for i, row in self.nearest_rows:
            hydration = app.nearest[i]
            if i == app.hit:
                pygame.draw.rect(surface, ACTIVE, row, border_radius=6)
            elif row.collidepoint(mouse):
                pygame.draw.rect(surface, HOVER, row, border_radius=6)
            draw_icon(surface, hydration.kind, (row.x + 14, row.centery), 8)
            text(surface, fonts["body"], fit(fonts["body"], hydration.name, row.w - 120), (row.x + 32, row.centery), anchor="midleft")
            text(surface, fonts["bold"], f"{meters(hydration.distance_m)} lagi", (row.right - 8, row.centery), anchor="midright")

    def draw_footer(self, surface):
        """Bagian bawah: cara mengukur jarak, dan tempat minum yang sedang ditandai tutup."""
        app, fonts, x = self.app, self.fonts, self.x
        pygame.draw.line(surface, COLORS["line"], (x, self.footer_y), (x + self.width, self.footer_y))
        text(surface, fonts["small"], "Ukur jarak ke tempat minum", (x, self.footer_y + 29), COLORS["muted"], anchor="midleft")
        if app.closed:
            text(surface, fonts["small"], f"{len(app.closed)} tempat minum ditandai tutup", (x, self.footer_y + 67), COLORS["muted"], anchor="midleft")

    def draw_results(self, surface, mouse):
        """Daftar hasil pencarian (nama, lalu jenis dan jarak dari titik mulai), di atas isi panel lainnya."""
        app, fonts = self.app, self.fonts
        rows = self.result_rows()
        field = self.search.rect
        if not rows:
            if len(self.search.value) >= config.SEARCH_MIN_CHARS:
                box = pygame.Rect(field.x, field.bottom + 4, self.x + self.width - field.x, RESULT_PX)
                pygame.draw.rect(surface, COLORS["white"], box, border_radius=8)
                pygame.draw.rect(surface, BORDER, box, 1, border_radius=8)
                text(surface, fonts["small"], "Tidak ada di peta. Tekan Enter untuk cari lewat internet.", (box.x + 12, box.centery), COLORS["muted"], anchor="midleft")
            return
        area = rows[0][1].unionall([row for _, row in rows])
        pygame.draw.rect(surface, COLORS["white"], area.inflate(0, 8), border_radius=8)
        pygame.draw.rect(surface, BORDER, area.inflate(0, 8), 1, border_radius=8)
        if not self.search.value:
            text(surface, fonts["small"], "Tempat favorit", (field.right - 8, field.centery), COLORS["muted"], anchor="midright")
        for i, row in rows:
            place = app.results[i]
            if row.collidepoint(mouse):
                pygame.draw.rect(surface, ACTIVE, row)
            text(surface, fonts["body"], fit(fonts["body"], place.name, row.w - 24), (row.x + 12, row.y + 4))
            text(surface, fonts["small"], app.result_detail(place), (row.x + 12, row.y + 24), COLORS["muted"])

    def draw_help(self, surface):
        """Layar cara pakai: tiga langkah bernomor, penjelasan singkat cara kerjanya, dan tombol Mulai."""
        fonts = self.fonts
        area = surface.get_rect()
        surface.fill(DIM, special_flags=pygame.BLEND_RGB_MULT)  # redupkan layar di belakang kartu (tanpa transparansi)
        card = pygame.Rect(0, 0, 620, 0)
        inner = card.w - 112
        heights = [sum(len(wrap(font, value, inner)) for font, value in ((fonts["bold"], title), (fonts["body"], body))) for title, body in HELP_STEPS]
        card.h = 150 + sum(h * 22 + 18 for h in heights) + len(wrap(fonts["small"], HOW_IT_WORKS, card.w - 64)) * 18 + 70
        card.center = area.center
        pygame.draw.rect(surface, COLORS["white"], card, border_radius=14)
        text(surface, fonts["title"], "Selamat datang", (card.x + 32, card.y + 28))
        paragraph(surface, fonts["body"], "Buat rute lari yang tidak pernah terlalu jauh dari tempat beli minum.", (card.x + 32, card.y + 62), card.w - 64, COLORS["muted"])
        y = card.y + 108
        for i, (title, body) in enumerate(HELP_STEPS, 1):
            pygame.draw.circle(surface, COLORS["safe"], (card.x + 48, y + 11), 15)
            text(surface, fonts["bold"], str(i), (card.x + 48, y + 11), COLORS["white"], anchor="center")
            y = paragraph(surface, fonts["bold"], title, (card.x + 80, y), inner, line_px=22)
            y = paragraph(surface, fonts["body"], body, (card.x + 80, y), inner, COLORS["text"], line_px=22) + 18
        pygame.draw.line(surface, COLORS["line"], (card.x + 32, y), (card.right - 32, y))
        y = paragraph(surface, fonts["small"], HOW_IT_WORKS, (card.x + 32, y + 14), card.w - 64, COLORS["muted"], line_px=18)
        start = pygame.Rect(card.right - 32 - 140, card.bottom - 56, 140, 36)
        pygame.draw.rect(surface, COLORS["safe"], start, border_radius=8)
        text(surface, fonts["bold"], "Mulai", start.center, COLORS["white"], anchor="center")
        text(surface, fonts["small"], "Buka lagi kapan saja lewat tombol ? di kiri atas.", (card.x + 32, start.centery), COLORS["muted"], anchor="midleft")

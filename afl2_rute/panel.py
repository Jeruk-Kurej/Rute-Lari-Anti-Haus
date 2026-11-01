"""Panel kanan: kartu input, tabel hasil, skenario, demo pelari, legenda, dan bantuan."""
import pygame

from .render import COLORS, ROAD_STYLES, draw_icon, draw_polyline, text
from .widgets import Button, Dropdown

CARD = (244, 246, 248)
ACCENT = (30, 142, 90)
LEGEND = [
    ("zone", "zone", "Zona buffer"),
    ("building", "building", "Bangunan"),
    ("line", "safe_road", "Jalan dalam zona"),
    ("line", "road", "Jalan luar zona"),
    *(("road", name, name) for name in ROAD_STYLES),
    ("line", "baseline", "Rute terpendek"),
    ("line", "safe", "Rute anti-haus"),
    ("dash", "trail", "Jejak pelari"),
    ("line", "reroute", "Rute baru"),
    ("line", "hydration_path", "Ke titik hidrasi"),
    ("icon", "Minimarket", "Minimarket"),
    ("icon", "Supermarket", "Supermarket"),
    ("icon", "Kedai minuman", "Kedai minuman"),
    ("icon", "closed", "Titik ditutup"),
]
LEGEND_ROW_PX = 18
HELP_STEPS = [
    "Pilih titik awal dan titik akhir di kartu \"1. Atur rute\".",
    "Atur toleransi: jarak maksimal rute ke titik hidrasi terdekat. Kalau rute anti-haus tidak ada, klik \"Cari toleransi minimum\".",
    "Bandingkan rute oranye (terpendek) dengan rute hijau (anti-haus) di peta. Kartu \"2. Hasil\" menampilkan panjang, selisih, dan jarak terjauh ke titik hidrasi.",
    "Skenario: klik sebuah titik hidrasi di peta untuk menutupnya (misal tokonya tutup). Klik lagi untuk membukanya.",
    "Demo pelari: gerakkan titik biru dengan W/A/S/D, tekan H atau tombol Hitung untuk jarak lewat jalan ke titik hidrasi terdekat, R untuk reset.",
    "Kalau pelari keluar dari rute anjuran, jejaknya (magenta putus-putus) dan rute baru dari posisinya (kuning) muncul, lalu ikut dibandingkan di tabel Hasil.",
    "Tambahan: tombol \"Zona\" mengganti cara ukur toleransi, Radius (buffer) atau Lewat jalan.",
    "Peta: scroll untuk zoom, drag untuk geser, 0 untuk reset. Nama toko dan jalan muncul saat di-zoom. Legenda ada di pojok kanan bawah peta.",
]


def meters(value):
    """Format angka jadi teks meter, misal 1250 -> "1.250 m". None -> "-"."""
    return "-" if value is None else f"{value:,.0f} m".replace(",", ".")


def signed(value):
    """Seperti meters(), tapi dengan tanda + atau -, untuk selisih panjang."""
    return "-" if value is None else ("+" if value >= 0 else "−") + meters(abs(value))


def trail_note(app):
    """Catatan di bawah tabel hasil yang menjelaskan asal rute pelari."""
    if app.arrived:
        return "Rute pelari = jejak sampai titik akhir."
    if app.reroute is None:
        return "Tidak ada rute anti-haus dari posisi pelari."
    if app.reroute.via_outside:
        return "Rute pelari = jejak + kembali ke zona + rute baru."
    return "Rute pelari = jejak + rute baru (kuning)."


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


# --- Panel samping: kartu bernomor sesuai alur proposal ---
class Panel:
    """Panel kanan: kartu bernomor sesuai alur proposal (atur rute, hasil, skenario, demo pelari, tambahan)."""

    def __init__(self, app, rect, fonts):
        """Susun posisi semua dropdown dan tombol di panel."""
        self.app, self.rect, self.fonts = app, rect, fonts
        self.help_open, self.legend_open = True, False
        self.x, self.width = rect.x + 20, rect.w - 40
        self.ix, self.iw = self.x + 12, self.width - 24
        right, field_x, field_w = self.ix + self.iw, self.ix + 90, self.iw - 90
        self.dropdowns = [
            Dropdown(pygame.Rect(field_x, 104, field_w, 28), lambda: app.names, lambda: app.start, lambda n: app.select("start", n)),
            Dropdown(pygame.Rect(field_x, 138, field_w, 28), lambda: app.names, lambda: app.end, lambda n: app.select("end", n)),
        ]
        area = app.map_rect
        self.buttons = [
            Button(pygame.Rect(field_x, 172, 30, 28), "-", lambda: app.change_tolerance(-1)),
            Button(pygame.Rect(right - 30, 172, 30, 28), "+", lambda: app.change_tolerance(1)),
            Button(pygame.Rect(self.ix, 208, self.iw, 28), "Cari toleransi minimum", app.find_minimum_tolerance),
            Button(pygame.Rect(right - 150, 530, 150, 26), "Buka kembali semua", app.open_all, lambda: bool(app.closed)),
            Button(pygame.Rect(self.ix, 610, self.iw, 30), "Hitung jarak ke titik hidrasi (H)", app.calculate),
            Button(pygame.Rect(self.ix + 96, 706, self.iw - 96, 28), lambda: f"Zona: {app.zone_mode}", app.toggle_zone_mode),
            Button(pygame.Rect(self.x + self.width - 84, 18, 84, 26), "? Bantuan", self.show_help),
            Button(pygame.Rect(area.right - 136, area.bottom - 44, 120, 28), self.legend_label, self.toggle_legend),
        ]

    def show_help(self):
        """Buka layar bantuan."""
        self.help_open = True

    def toggle_legend(self):
        """Buka/tutup kotak legenda di peta."""
        self.legend_open = not self.legend_open

    def legend_label(self):
        """Teks tombol legenda: "Legenda" atau "Tutup legenda"."""
        return "Tutup legenda" if self.legend_open else "Legenda"

    def click(self, pos):
        """Proses klik di panel. True kalau klik dipakai panel, False kalau harus diteruskan ke peta."""
        opened = next((d for d in self.dropdowns if d.open), None)
        for dropdown in self.dropdowns:
            dropdown.open = False
        if opened:
            item = opened.item_at(pos)
            if item is not None:
                opened.on_select(item)
                return True
            if opened.rect.collidepoint(pos):
                return True
        for dropdown in self.dropdowns:
            if dropdown.rect.collidepoint(pos):
                dropdown.open = True
                return True
        for button in self.buttons:
            if button.hit(pos):
                button.action()
                return True
        return self.legend_open and self.legend_rect().collidepoint(pos)

    # --- Gambar ---
    def card(self, surface, y, h, title, accent=False):
        """Gambar satu kartu (kotak abu-abu muda) dengan judul. `accent` menambah garis hijau di kiri."""
        rect = pygame.Rect(self.x, y, self.width, h)
        pygame.draw.rect(surface, CARD, rect, border_radius=8)
        if accent:
            pygame.draw.rect(surface, ACCENT, (rect.x, rect.y + 8, 4, rect.h - 16), border_radius=2)
        if title:
            text(surface, self.fonts["bold"], title, (self.ix, y + 10))

    def draw(self, surface, mouse):
        """Gambar seluruh panel kanan, termasuk legenda dan layar bantuan kalau sedang terbuka."""
        fonts = self.fonts
        pygame.draw.rect(surface, COLORS["white"], self.rect)
        pygame.draw.line(surface, (220, 222, 226), self.rect.topleft, self.rect.bottomleft)
        text(surface, fonts["title"], "Rute Lari Anti-Haus", (self.x, 16))
        text(surface, fonts["small"], "Citraland Surabaya · data OSM + Google Maps", (self.x, 42), COLORS["muted"])

        self.draw_route_card(surface, 66)
        self.draw_result_card(surface, 270)
        self.draw_scenario_card(surface, 474)
        self.draw_runner_card(surface, 574)
        self.card(surface, 698, 44, None)
        text(surface, fonts["body"], "Tambahan", (self.ix, 720), COLORS["muted"], anchor="midleft")

        for button in self.buttons:
            button.draw(surface, fonts["body"], mouse)
        for dropdown in self.dropdowns:
            dropdown.draw_box(surface, fonts["body"], mouse)
        if self.legend_open:
            self.draw_legend(surface)
        for dropdown in self.dropdowns:
            if dropdown.open:
                dropdown.draw_list(surface, fonts["body"], mouse)
        if self.help_open:
            self.draw_help(surface)

    def draw_route_card(self, surface, y):
        """Kartu 1: titik awal, titik akhir, dan toleransi."""
        app, fonts = self.app, self.fonts
        self.card(surface, y, 196, "1. Atur rute", accent=True)
        for row_y, label in ((y + 52, "Titik awal"), (y + 86, "Titik akhir"), (y + 120, "Toleransi")):
            text(surface, fonts["body"], label, (self.ix, row_y), anchor="midleft")
        minus, plus = self.buttons[0].rect, self.buttons[1].rect
        text(surface, fonts["bold"], meters(app.tolerance), ((minus.right + plus.x) / 2, y + 120), anchor="center")
        if app.min_message:
            text(surface, fonts["small"], app.min_message, (self.ix, y + 176), COLORS["muted"])

    def draw_result_card(self, surface, y):
        """Kartu 2: tabel panjang, selisih, dan jarak terjauh ke titik hidrasi untuk tiap rute."""
        app, fonts, ix = self.app, self.fonts, self.ix
        self.card(surface, y, 196, "2. Hasil: terpendek vs anti-haus", accent=True)
        found = app.comparison.safe is not None
        for i, line in enumerate(wrap(fonts["body"], app.comparison.status, self.iw)):
            text(surface, fonts["body"], line, (ix, y + 34 + i * 18), COLORS["safe"] if found else COLORS["Minimarket"])

        columns = (ix, ix + 88, ix + 162, ix + 236)
        for column, header in zip(columns, ("Rute", "Panjang", "Selisih", "Terjauh ke hidrasi")):
            text(surface, fonts["small"], header, (column, y + 76), COLORS["muted"])
        rows = list(app.stats.items())
        if app.trail_stats is not None:
            rows.append(("Rute pelari", app.trail_stats))
        base = app.stats["Baseline"]["panjang_m"]
        for i, (label, stats) in enumerate(rows):
            row_y = y + 94 + i * 20
            no_diff = label == "Baseline" or (label == "Rute pelari" and not app.arrived and app.reroute is None)
            font = fonts["bold"] if label == "Anti-haus" else fonts["body"]
            text(surface, font, label, (columns[0], row_y))
            text(surface, font, meters(stats["panjang_m"]), (columns[1], row_y))
            text(surface, font, signed(None if no_diff else stats["panjang_m"] - base), (columns[2], row_y))
            text(surface, font, meters(stats["jarak_terjauh_m"]), (columns[3], row_y))

        notes = [] if found else ["Naikkan toleransi, atau klik \"Cari toleransi minimum\"."]
        if app.trail_stats is not None:
            notes.append(trail_note(app))
        for i, note in enumerate(notes):
            text(surface, fonts["small"], note, (ix, y + 98 + len(rows) * 20 + i * 16), COLORS["muted"])

    def draw_scenario_card(self, surface, y):
        """Kartu 3: berapa titik hidrasi yang sedang ditutup."""
        app, fonts = self.app, self.fonts
        self.card(surface, y, 92, "3. Skenario: tutup titik hidrasi")
        text(surface, fonts["small"], "Klik titik hidrasi di peta untuk menutup / membukanya.", (self.ix, y + 34), COLORS["muted"])
        text(surface, fonts["body"], f"Ditutup: {len(app.closed)} dari {len(app.data.points)} titik", (self.ix, y + 69), anchor="midleft")

    def draw_runner_card(self, surface, y):
        """Kartu 4: hasil tombol Hitung (titik hidrasi terdekat dari pelari)."""
        app, fonts = self.app, self.fonts
        self.card(surface, y, 116, "4. Demo pelari")
        text(surface, fonts["small"], "W/A/S/D gerak · R reset", (self.ix + self.iw, y + 12), COLORS["muted"], anchor="topright")
        if not app.calculated:
            text(surface, fonts["small"], "Tekan tombol di atas untuk jarak ke titik hidrasi terdekat.", (self.ix, y + 76), COLORS["muted"])
            return
        if app.hit is None:
            text(surface, fonts["body"], "Tidak ada titik hidrasi yang buka.", (self.ix, y + 74))
            return
        text(surface, fonts["body"], f"Terdekat: {app.hit.name}", (self.ix, y + 74))
        text(surface, fonts["bold"], f"Jarak lewat jalan: {meters(app.hit.distance_m)}", (self.ix, y + 92))

    def legend_rect(self):
        """Posisi dan ukuran kotak legenda di pojok kanan bawah peta."""
        area = self.app.map_rect
        rows = -(-len(LEGEND) // 2)
        rect = pygame.Rect(0, 0, 300, 44 + rows * LEGEND_ROW_PX)
        rect.bottomright = (area.right - 16, area.bottom - 52)
        return rect

    def draw_legend(self, surface):
        """Gambar kotak legenda: arti warna, garis, dan ikon di peta."""
        fonts, box = self.fonts, self.legend_rect()
        pygame.draw.rect(surface, COLORS["white"], box, border_radius=8)
        pygame.draw.rect(surface, (205, 210, 216), box, 1, border_radius=8)
        text(surface, fonts["bold"], "Legenda", (box.x + 12, box.y + 10))
        rows = -(-len(LEGEND) // 2)
        for i, (shape, key, label) in enumerate(LEGEND):
            item_x, item_y = box.x + 12 + (i // rows) * 146, box.y + 42 + (i % rows) * LEGEND_ROW_PX
            sample = [(item_x, item_y), (item_x + 18, item_y)]
            if shape == "zone":
                pygame.draw.rect(surface, (205, 225, 246), (item_x, item_y - 5, 18, 10))
            elif shape == "building":
                pygame.draw.rect(surface, COLORS[key], (item_x, item_y - 5, 18, 10))
            elif shape == "road":
                min_px, _, dashed = ROAD_STYLES[key]
                draw_polyline(surface, sample, COLORS["safe_road"], min_px, dashed)
            elif shape == "dash":
                draw_polyline(surface, sample, COLORS[key], 3, dashed=True)
            elif shape == "line":
                draw_polyline(surface, sample, COLORS[key], 4)
            else:
                draw_icon(surface, key, (item_x + 9, item_y), 7)
            text(surface, fonts["small"], label, (item_x + 26, item_y), anchor="midleft")

    def draw_help(self, surface):
        """Gambar layar "Cara pakai" di atas peta."""
        fonts = self.fonts
        area = self.app.map_rect
        card = pygame.Rect(0, 0, 560, 0)
        steps = [wrap(fonts["body"], f"{i}. {step}", card.w - 48) for i, step in enumerate(HELP_STEPS, 1)]
        card.h = 120 + sum(len(lines) * 20 + 10 for lines in steps)
        card.center = area.center
        shade = pygame.Surface(area.size, pygame.SRCALPHA)
        shade.fill((27, 31, 35, 120))
        surface.blit(shade, area.topleft)
        pygame.draw.rect(surface, COLORS["white"], card, border_radius=10)
        text(surface, fonts["title"], "Cara pakai", (card.x + 24, card.y + 22))
        y = card.y + 64
        for lines in steps:
            for line in lines:
                text(surface, fonts["body"], line, (card.x + 24, y))
                y += 20
            y += 10
        text(surface, fonts["small"], "Klik atau tekan tombol apa saja untuk menutup. Buka lagi lewat tombol \"? Bantuan\".", (card.x + 24, card.bottom - 30), COLORS["muted"])

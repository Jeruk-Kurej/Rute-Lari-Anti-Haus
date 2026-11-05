"""Memuat font. Di macOS dipakai Avenir Next (dengan ketebalan yang tepat), di komputer lain font sistem biasa."""
from pathlib import Path

import pygame
import pygame.freetype

AVENIR = Path("/System/Library/Fonts/Avenir Next.ttc")
FACES = {"regular": 7, "medium": 5, "demi": 2}  # nomor gaya di dalam berkas Avenir Next.ttc
FALLBACK = "Segoe UI,Helvetica Neue,Arial"
STYLES = {  # nama gaya -> (ketebalan, ukuran)
    "small": ("medium", 14),
    "body": ("regular", 16),
    "bold": ("demi", 16),
    "section": ("demi", 17),
    "title": ("demi", 24),
    "big_value": ("demi", 20),
    "big": ("demi", 38),
}


class Face:
    """Satu font dari berkas berisi banyak gaya (.ttc). Cara pakainya sama dengan pygame.font.Font."""

    def __init__(self, path, index, size):
        self.font = pygame.freetype.Font(str(path), size, font_index=index)
        self.font.pad = True  # tinggi teks selalu sama, jadi teks sejajar walau hurufnya berbeda

    def render(self, value, antialias, color):
        return self.font.render(value, color)[0]

    def size(self, value, rotation=0):
        self.font.pad = not rotation  # freetype tidak bisa memberi padding pada teks miring
        return self.font.get_rect(value, rotation=round(rotation)).size

    def draw(self, surface, value, rect, color, rotation=0):
        """Tulis teks langsung ke `surface` di kotak `rect` (tanpa gambar perantara transparan).

        Cara ini dipakai karena di jendela macOS, gambar teks transparan yang ditempel di atas peta
        bisa tampil dengan latar hitam.
        """
        self.font.pad = not rotation
        self.font.render_to(surface, rect.topleft, value, color, rotation=round(rotation))
        self.font.pad = True

    def get_linesize(self):
        return self.font.get_sized_height()


def load_fonts():
    """Semua font yang dipakai program, dengan nama gaya sebagai kunci (lihat STYLES)."""
    if AVENIR.exists():
        pygame.freetype.init()
        return {name: Face(AVENIR, FACES[weight], size) for name, (weight, size) in STYLES.items()}
    return {name: pygame.font.SysFont(FALLBACK, size, bold=weight == "demi") for name, (weight, size) in STYLES.items()}

"""Komponen antarmuka dasar: tombol (teks atau ikon) dan kotak ketik."""
from dataclasses import dataclass
from typing import Callable

import pygame

from .render import COLORS, text

BORDER = (196, 206, 203)
HOVER = (230, 240, 246)
FOCUS = COLORS["safe"]
DISABLED = (176, 184, 187)
CARET_BLINK_MS = 500


def draw_glyph(surface, name, center, color, size=6):
    """Gambar ikon kecil dengan garis (tanpa font, jadi tampil sama di semua komputer)."""
    x, y = center
    if name == "plus":
        pygame.draw.line(surface, color, (x - size, y), (x + size, y), 2)
        pygame.draw.line(surface, color, (x, y - size), (x, y + size), 2)
    elif name == "minus":
        pygame.draw.line(surface, color, (x - size, y), (x + size, y), 2)
    elif name == "close":
        pygame.draw.line(surface, color, (x - size * 0.7, y - size * 0.7), (x + size * 0.7, y + size * 0.7), 2)
        pygame.draw.line(surface, color, (x - size * 0.7, y + size * 0.7), (x + size * 0.7, y - size * 0.7), 2)
    elif name in ("up", "down"):
        sign = -1 if name == "up" else 1
        tip, wing = y + sign * size * 0.35, y - sign * size * 0.35
        pygame.draw.lines(surface, color, False, [(x - size * 0.7, wing), (x, tip), (x + size * 0.7, wing)], 2)
    elif name == "center":
        pygame.draw.circle(surface, color, (x, y), size, 2)
        pygame.draw.circle(surface, color, (x, y), 2)
    elif name in ("check_on", "check_off"):
        box = pygame.Rect(0, 0, 14, 14)
        box.center = (x, y)
        if name == "check_on":
            pygame.draw.rect(surface, color, box, border_radius=3)
            pygame.draw.lines(surface, COLORS["white"], False, [(x - 4, y), (x - 1, y + 3), (x + 4, y - 3)], 2)
        else:
            pygame.draw.rect(surface, color, box, 2, border_radius=3)


@dataclass
class Button:
    """Tombol. `label` teks tetap atau fungsi (kalau teksnya berubah), `icon` nama ikon dari draw_glyph.

    `style`: "ghost" (kotak putih bergaris), "primary" (biru penuh, untuk aksi utama), atau "link" (teks biru saja).
    `enabled` mengatur aktif/nonaktif.
    """

    rect: pygame.Rect
    label: str | Callable[[], str]
    action: Callable[[], None]
    enabled: Callable[[], bool] = lambda: True
    icon: str | Callable[[], str] | None = None
    style: str = "ghost"

    def hit(self, pos):
        """True kalau tombol aktif dan posisi `pos` ada di dalamnya."""
        return self.enabled() and self.rect.collidepoint(pos)

    def text(self):
        """Teks tombol saat ini."""
        return self.label() if callable(self.label) else self.label

    def draw(self, surface, font, mouse):
        """Gambar tombol sesuai gayanya (berubah warna saat mouse di atasnya)."""
        active, hover = self.enabled(), self.rect.collidepoint(mouse)
        if self.style == "primary":
            fill = COLORS["safe"] if active else DISABLED
            pygame.draw.rect(surface, tuple(max(c - 20, 0) for c in fill) if hover and active else fill, self.rect, border_radius=8)
            ink = COLORS["white"]
        elif self.style == "link":
            if hover and active:
                pygame.draw.rect(surface, HOVER, self.rect, border_radius=6)
            ink = COLORS["safe"] if active else DISABLED
        else:
            pygame.draw.rect(surface, HOVER if hover and active else COLORS["white"], self.rect, border_radius=8)
            pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=8)
            ink = COLORS["text"] if active else DISABLED
        label = self.text()
        icon = self.icon() if callable(self.icon) else self.icon
        if not label:
            draw_glyph(surface, icon, self.rect.center, ink)
            return
        if self.style == "link":
            x = self.rect.x + 8
            if icon:
                draw_glyph(surface, icon, (x + 5, self.rect.centery), ink, 5)
                x += 18
            text(surface, font, label, (x, self.rect.centery), ink, anchor="midleft")
            return
        text(surface, font, label, self.rect.center, ink, anchor="center")


@dataclass
class TextInput:
    """Kotak ketik satu baris. Saat aktif (focused), semua ketikan masuk ke sini, bukan ke tombol pintas program."""

    rect: pygame.Rect
    placeholder: Callable[[], str]
    on_change: Callable[[str], None]
    on_submit: Callable[[str], None]
    value: str = ""
    focused: bool = False

    def set(self, value):
        """Ganti isi kotak, lalu beri tahu pemiliknya."""
        self.value = value
        self.on_change(value)

    def handle(self, event):
        """Proses satu event keyboard. True kalau event dipakai kotak ini."""
        if not self.focused:
            return False
        if event.type == pygame.TEXTINPUT:
            self.set(self.value + event.text)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.set(self.value[:-1])
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.on_submit(self.value)
            elif event.key == pygame.K_ESCAPE:
                self.focused = False
        return event.type in (pygame.TEXTINPUT, pygame.KEYDOWN)

    def draw(self, surface, font):
        """Gambar kotak aktif, isinya (atau teks petunjuk kalau kosong), dan kursor berkedip."""
        pygame.draw.rect(surface, COLORS["white"], self.rect, border_radius=8)
        pygame.draw.rect(surface, FOCUS, self.rect, 2, border_radius=8)
        room = self.rect.w - 24
        shown = self.value
        while shown and font.size(shown)[0] > room:  # teks panjang: tampilkan bagian akhirnya saja
            shown = shown[1:]
        x, y = self.rect.x + 12, self.rect.centery
        if shown:
            end = text(surface, font, shown, (x, y), anchor="midleft").right
        else:
            text(surface, font, self.placeholder(), (x, y), COLORS["muted"], anchor="midleft")
            end = x
        if pygame.time.get_ticks() // CARET_BLINK_MS % 2 == 0:
            pygame.draw.line(surface, COLORS["text"], (end + 1, y - 9), (end + 1, y + 9), 2)

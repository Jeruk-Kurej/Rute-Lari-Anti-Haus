from dataclasses import dataclass
from typing import Callable

import pygame

from .render import COLORS, text

ITEM_HEIGHT = 26
BORDER = (186, 192, 199)
HOVER = (226, 236, 248)


@dataclass
class Button:
    rect: pygame.Rect
    label: str | Callable[[], str]
    action: Callable[[], None]
    enabled: Callable[[], bool] = lambda: True

    def hit(self, pos):
        return self.enabled() and self.rect.collidepoint(pos)

    def draw(self, surface, font, mouse):
        active = self.enabled()
        fill = HOVER if active and self.rect.collidepoint(mouse) else COLORS["white"]
        pygame.draw.rect(surface, fill, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=6)
        label = self.label() if callable(self.label) else self.label
        text(surface, font, label, self.rect.center, COLORS["text"] if active else (170, 175, 180), anchor="center")


@dataclass
class Dropdown:
    rect: pygame.Rect
    options: Callable[[], list]
    value: Callable[[], str]
    on_select: Callable[[str], None]
    open: bool = False

    def list_rect(self):
        return pygame.Rect(self.rect.x, self.rect.bottom + 2, self.rect.w, ITEM_HEIGHT * len(self.options()))

    def item_at(self, pos):
        area = self.list_rect()
        if not area.collidepoint(pos):
            return None
        return self.options()[(pos[1] - area.y) // ITEM_HEIGHT]

    def draw_box(self, surface, font, mouse):
        fill = HOVER if self.rect.collidepoint(mouse) else COLORS["white"]
        pygame.draw.rect(surface, fill, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, 1, border_radius=6)
        text(surface, font, self.value(), (self.rect.x + 10, self.rect.centery), anchor="midleft")
        x, y = self.rect.right - 16, self.rect.centery
        pygame.draw.polygon(surface, COLORS["muted"], [(x - 5, y - 2), (x + 5, y - 2), (x, y + 4)])

    def draw_list(self, surface, font, mouse):
        area = self.list_rect()
        pygame.draw.rect(surface, COLORS["white"], area)
        for i, name in enumerate(self.options()):
            item = pygame.Rect(area.x, area.y + i * ITEM_HEIGHT, area.w, ITEM_HEIGHT)
            if item.collidepoint(mouse):
                pygame.draw.rect(surface, (222, 235, 250), item)
            text(surface, font, name, (item.x + 10, item.centery), anchor="midleft")
        pygame.draw.rect(surface, BORDER, area, 1)

"""Position de la souris dans la fenêtre en cours de dessin (application ou overlay)."""
import pygame

provider = None


def get():
    if provider:
        return provider()
    return pygame.mouse.get_pos()

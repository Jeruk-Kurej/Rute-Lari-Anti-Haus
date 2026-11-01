"""Pintu masuk program: muat data, lalu jalankan aplikasi."""
from .data import load_dataset
from .game import App


def main():
    """Muat dataset lalu jalankan jendela aplikasi."""
    App(load_dataset()).run()


if __name__ == "__main__":
    main()

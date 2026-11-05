"""Pintu masuk program: buka jendela, muat data, lalu jalankan aplikasi."""
from .data import load_dataset
from .game import App


def main():
    """Buka aplikasi. Data dimuat di dalam App supaya layar "Memuat..." bisa tampil lebih dulu."""
    App(load_dataset).run()


if __name__ == "__main__":
    main()

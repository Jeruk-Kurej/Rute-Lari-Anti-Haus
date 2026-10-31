from .data import load_dataset
from .game import App


def main():
    App(load_dataset()).run()


if __name__ == "__main__":
    main()

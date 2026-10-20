import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    try:
        from gui import run
    except Exception as e:
        print("Не удалось запустить интерфейс:", e)
        sys.exit(1)
    run()


if __name__ == "__main__":
    main()

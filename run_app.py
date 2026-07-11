"""패키징(exe) 엔트리포인트 — python -m app.studio 와 동일."""
from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    from app.studio import main

    main()

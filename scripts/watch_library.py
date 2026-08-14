"""Vigila las subcarpetas de -bakala y registra cuándo quedan procesadas.

El proceso de biblioteca MUEVE los archivos (borra el origen), así que una
subcarpeta está "terminada" cuando ya no contiene ningún archivo de audio.
Escribe el estado en log/library_watch.log cada vez que algo cambia.
"""

import time
from pathlib import Path

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a",
    ".mp4", ".aac", ".wma", ".ape", ".alac",
}

SOURCE = Path("/run/media/radi/SI-Nena!!!/MÚSICA/-bakala")
LOG = Path("/home/radi/Proyectos/Github/gestorListasReproduccion/log/library_watch.log")
POLL_SECONDS = 60


def remaining_audio(directory: Path) -> int:
    return sum(
        1
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def snapshot() -> dict[str, int]:
    if not SOURCE.exists():
        return {}
    return {
        d.name: remaining_audio(d)
        for d in sorted(SOURCE.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    }


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, int] | None = None
    done: set[str] = set()
    while True:
        current = snapshot()
        with LOG.open("a") as fh:
            for name, count in current.items():
                if count == 0:
                    if name not in done:
                        done.add(name)
                        fh.write(f"[{time.strftime('%H:%M:%S')}] TERMINADA: {name}\n")
                else:
                    if previous is not None and previous.get(name, 0) > 0 and count != previous[name]:
                        fh.write(
                            f"[{time.strftime('%H:%M:%S')}] {name}: "
                            f"{previous[name]} -> {count} restantes\n"
                        )
            done_names = ", ".join(sorted(done))
            remaining = ", ".join(
                f"{n} ({c})" for n, c in sorted(current.items()) if c > 0
            )
            fh.write(
                f"[{time.strftime('%H:%M:%S')}] -- terminadas: [{done_names}] "
                f"| en curso: [{remaining}]\n"
            )
        previous = current
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

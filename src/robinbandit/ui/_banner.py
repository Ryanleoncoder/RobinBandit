"""Banner Unicode do CLI, sem dependências de runtime."""

import os
import sys


_COLORS = {
    "cream": "\x1b[38;2;238;227;210m",
    "green": "\x1b[38;2;93;121;96m",
    "gold": "\x1b[38;2;224;175;68m",
}
_RESET = "\x1b[0m"

# Símbolo reduzido para uma grade Braille de 30 x 12 caracteres. As cores são
# agrupadas por região para evitar uma sequência ANSI em cada caractere.
_LOGO_SEGMENTS = (
    ((None, "       "), ("cream", "⡏⠉⠉⠉⠉⠉⠉⠉⠉⠉⠒⠢⣀")),
    ((None, "       "), ("cream", "⡇            ⠑⢄")),
    ((None, "       "), ("cream", "⡇   ⡠⢄⣀        ⠑⢄")),
    ((None, "       "), ("cream", "⢱   ⢇  ⠉⠑⠒⠤⢄⣀    ⠑⢄")),
    (
        (None, "   "),
        ("green", "⣀⣀⣀⣀"),
        ("cream", "⠈⢆  ⠘⡄   "),
        ("gold", "⣤⣤"),
        ("cream", "  ⠉⠒⠢⠤⡀ ⠑⢄"),
    ),
    (
        (None, "   "),
        ("green", "⣿⣿⣿⣿⣷⡄"),
        ("cream", "⠑⢄ ⠈⠢⣀ "),
        ("gold", "⠈⠿"),
        ("cream", "    ⢀⠔⠁  ⢸"),
    ),
    (
        ("green", "⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣄"),
        ("cream", "⠑⢄  ⠑⢄   ⢀⠔⠁   ⢀⠜"),
    ),
    (
        ("green", "⠿⠿⠿⠿⠿⠿⠿⠿⠿⠿⠿⠷"),
        ("cream", " ⠑⢄  ⠑⠢⠔⠁   ⢀⠔⠁"),
    ),
    (
        (None, "    "),
        ("green", "⣶⣶⣶⣶⣶⣶⣶⣶⣶⣶⣄"),
        ("cream", "⠑⢄      ⢔⠁"),
    ),
    (
        (None, "    "),
        ("green", "⠛⠛⠛⠛⠛⠛⠛⠛⢿⠿⠿⠷"),
        ("cream", "⢄⠑⢄     ⠑⢄"),
    ),
    ((None, "             "), ("cream", "⠑⢄  ⠑⢄⠑⢄     ⠑⢄")),
    ((None, "               "), ("cream", "⠑⠒⠒⠒⠃ ⠑⢄⣀⣀⣀⣀⣀⣑⣄")),
)


def _render_logo(*, color: bool) -> str:
    lines = []
    for segments in _LOGO_SEGMENTS:
        parts = []
        active_color = None
        for shade, text in segments:
            if color and shade != active_color:
                parts.append(_COLORS.get(shade, _RESET))
                active_color = shade
            parts.append(text)
        if color and active_color is not None:
            parts.append(_RESET)
        lines.append("".join(parts))
    return "\n".join(lines)


def _supports_braille(stream) -> bool:
    # UTF-8 garante apenas que o caractere pode ser enviado. O Console Host
    # antigo do Windows ainda pode desenhá-lo como um quadrado se a fonte não
    # tiver Braille. O Windows Terminal inclui Cascadia Mono com esses glifos.
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        return False

    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "⣿".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _enable_windows_vt(stream) -> bool:
    if os.name != "nt":
        return True
    if (
        os.environ.get("WT_SESSION")
        or os.environ.get("ANSICON")
        or os.environ.get("ConEmuANSI") == "ON"
    ):
        return True

    try:
        import ctypes
        import msvcrt

        handle = ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno()))
        mode = ctypes.c_uint()
        kernel32 = ctypes.windll.kernel32
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


def _supports_color(stream) -> bool:
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    return _enable_windows_vt(stream)


def _write_banner(stream=None, *, enabled: bool = True, color: bool = True) -> None:
    if stream is None:
        stream = sys.stdout
    is_tty = getattr(stream, "isatty", lambda: False)
    if not enabled or not is_tty() or not _supports_braille(stream):
        return

    use_color = color and _supports_color(stream)
    stream.write(_render_logo(color=use_color))
    stream.write("\n\n")

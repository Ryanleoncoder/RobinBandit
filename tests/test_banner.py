import io
import sys

# A linha de comando mora em `cli.py`; `__main__` so a chama.
from robinbandit import cli
from robinbandit.ui import _banner


class _TTY:
    def __init__(self, encoding="utf-8"):
        self.encoding = encoding
        self._value = ""

    def isatty(self):
        return True

    def write(self, text):
        self._value += text
        return len(text)

    def getvalue(self):
        return self._value


def test_logo_is_compact_and_has_no_wordmark():
    logo = _banner._render_logo(color=False)

    assert len(logo.splitlines()) == 12
    assert max(map(len, logo.splitlines())) <= 30
    assert "ROBINBANDIT" not in logo
    assert "\x1b[" not in logo


def test_banner_uses_grouped_truecolor_in_a_tty(monkeypatch):
    stream = _TTY()
    monkeypatch.setenv("WT_SESSION", "test-session")
    monkeypatch.setattr(_banner, "_supports_color", lambda _: True)

    _banner._write_banner(stream)

    output = stream.getvalue()
    assert "\x1b[38;2;238;227;210m" in output
    assert "\x1b[38;2;93;121;96m" in output
    assert "\x1b[38;2;224;175;68m" in output
    assert output.count("\x1b[") < 40
    assert output.endswith("\x1b[0m\n\n")


def test_banner_is_plain_when_color_is_disabled(monkeypatch):
    stream = _TTY()
    monkeypatch.setenv("WT_SESSION", "test-session")

    _banner._write_banner(stream, color=False)

    assert "⡏" in stream.getvalue()
    assert "\x1b[" not in stream.getvalue()


def test_banner_respects_no_color(monkeypatch):
    stream = _TTY()
    monkeypatch.setenv("WT_SESSION", "test-session")
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setattr(_banner, "_enable_windows_vt", lambda _: True)

    _banner._write_banner(stream)

    assert "⡏" in stream.getvalue()
    assert "\x1b[" not in stream.getvalue()


def test_banner_does_not_pollute_redirected_or_incompatible_output(monkeypatch):
    redirected = io.StringIO()
    incompatible = _TTY(encoding="cp1252")
    monkeypatch.setenv("WT_SESSION", "test-session")

    _banner._write_banner(redirected)
    _banner._write_banner(incompatible)

    assert redirected.getvalue() == ""
    assert incompatible.getvalue() == ""


def test_banner_skips_the_legacy_windows_console(monkeypatch):
    stream = _TTY()
    monkeypatch.setattr(_banner.os, "name", "nt")
    monkeypatch.delenv("WT_SESSION", raising=False)

    _banner._write_banner(stream, color=False)

    assert stream.getvalue() == ""


def test_cli_forwards_banner_options(monkeypatch, tmp_path, capsys):
    dump = tmp_path / "state.json"
    dump.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "_write_banner", lambda **options: calls.append(options))
    monkeypatch.setattr(
        sys,
        "argv",
        ["robinbandit", str(dump), "--no-banner", "--no-color"],
    )

    cli.main()

    assert calls == [{"enabled": False, "color": False}]
    assert capsys.readouterr().out == "dump sem provedores\n"

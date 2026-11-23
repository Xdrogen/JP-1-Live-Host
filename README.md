# JP-1 Live Host

> Unofficial third-party companion tool for the JAMJUM JP-1. Not affiliated
> with, endorsed by, or distributed by JAMJUM / Zhuhai Kuwee Technology Co., Ltd.
> "JAMJUM" and "JP-1" are trademarks of their respective owner.

A small Windows live host for the JP-1 pad controller: 3 banks x 16 pads,
8 MIDI knobs, transport controls, preset save/load, velocity-sensitive trigger,
and a lightweight launch screen.

## Build (Windows)

- Python 3.13 + PySide6 + PyInstaller
- `jamjum.spec` -> `pyinstaller --noconfirm --clean jamjum.spec`
- `launcher.cs` -> compiled with .NET Framework `csc.exe` (`/target:winexe`)
- `setup.iss` -> Inno Setup, produces `JP-1 Live Host Setup.exe`

## MIDI map

| Control | CC / Note |
|---|---|
| DIV / SWING / GATE / TEMPO | CC 46 / 47 / 48 / 49 |
| DELAY / VOLUME / FILTER / REVERB | CC 50 / 51 / 52 / 53 |
| Play / Pause / Stop | CC 22 / 23 / 24 |
| Pads | 3 banks x 16 triggers |

## DAW mapping

Work in progress — see issues for current status and known limitations.

## Screenshots / Known issues

TODO: add main UI, icon and launch screen captures; list known limitations.

## License

MIT. See [LICENSE](LICENSE).

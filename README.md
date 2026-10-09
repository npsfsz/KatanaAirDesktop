# Katana Air Desktop

An experimental Windows tone editor for the original **BOSS KATANA-AIR**, using Bluetooth MIDI. The interface runs locally in your browser. No account or internet connection is needed during use.

## Features

- Edit the current amplifier tone, booster, Mod, FX, two delays, reverb, EQ, noise gate, tone level/key, and cabinet/global EQ.
- See **BST/MOD**, **DELAY/FX**, and **REVERB** panel readouts with combined knob positions, effect names, and LED colours.
- Receive automatic updates from physical knobs and channel changes. Amplifier and panel controls update frequently; the full effects state is read approximately every two seconds, and global EQ/cabinet settings every five seconds.
- Verify edits by reading the value back from the amp. Failed verification triggers an attempted restoration and an error message.
- Retry dropped connections automatically. Background reads and edits share a lock; live updates preserve slider dragging.

Preset management, import/export, signal-chain rearrangement, colour-slot assignments, and tuner are outside this preview's scope.

## Run from source

Requires **Windows, Python 3.12, and Bluetooth LE**.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install bleak==3.0.2
.\.venv\Scripts\python.exe source\app.py
```

1. Turn on the amp and pair **KATANA-AIR MIDI** in Windows Bluetooth settings.
2. Close mobile tone editors and other desktop amp editors.
3. Choose the amp and click **Connect**.
4. Use the Amplifier page for panel readouts and choose an effect section to edit its parameters. Edits apply when a slider is released or an option is selected.
5. Use **Quit editor** to disconnect and stop the application. Closing the browser tab alone leaves it running.

Cabinet and global EQ settings apply across tones.

## Build a portable Windows executable

From the repository root, using a Windows Python 3.12 installation:

```powershell
.\source\build.ps1 -Python python
```

The script creates an isolated build environment, installs the pinned build dependencies, runs the offline tests, and produces `Katana-Air-Desktop.exe` in the repository root. The executable opens the interface in your default browser and does not require Python to be installed on the destination computer. Build environments and binaries are excluded from Git.

## Test

```powershell
.\.venv\Scripts\python.exe source\test_protocol.py
```

The tests do not connect to hardware or change amp settings. They cover checksums, base-128 addresses, BLE timestamps and packet boundaries, stable snapshots during reads, complete response tracking, synchronization between edits and live reads, and notification cleanup before disconnecting. GitHub Actions runs these checks on Windows.

## Limitations and troubleshooting

This is a preview, not complete mobile-app parity. Parameter definitions and effect layouts are adapted from AIR FxFloorBoard. Some inherited addresses needed correction, and not every effect label or range has been independently validated. A successful readback confirms that the requested value was returned; it does not prove the semantic meaning of every inherited parameter. Inherited pedal FX and foot-volume controls are omitted.

If the amp stops replying, close other editors, disconnect, and reconnect. A power cycle may be needed if the Windows Bluetooth session becomes stuck. A setting absent from the amp's response is unavailable, and an unknown current value cannot be edited. Failed restoration is reported explicitly.

## Privacy

Device names, Bluetooth addresses, and live settings are discovered at runtime and held in memory. The application has no telemetry, cloud service, or preset database. Its HTTP server binds only to `127.0.0.1`, and write requests require a randomly generated credential for that application session.

This repository contains generic source and parameter definitions. It excludes personal device identifiers, tone captures, connection logs, local diagnostic reports, credentials, and compiled binaries that could contain local build paths. Diagnostic files generated outside normal operation should be reviewed before sharing.

## Licence and attribution

Distributed under **GPL-3.0-or-later**. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Parameter definitions and effect layouts are adapted from [AIR FxFloorBoard](https://sourceforge.net/projects/air-fxfloorboard/), by Colin Willcocks and Uco Mesdag. The extracted upstream map is included in `source/upstream-midi.xml`. This is an independent project and is not a BOSS/Roland product.

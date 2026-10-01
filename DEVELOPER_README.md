# Mycelia WebCMS v0.8.0 – Entwicklerpaket

Dieses Paket enthält den vollständigen Quellstand zum Neubauen und Testen des WebCMS, des Mycelia Security SDK und des nativen MyceliaDB-Servers.

Lizenz: GNU General Public License Version 3, siehe `LICENSE`.

## Voraussetzungen

- Windows 10 oder 11 x64
- Python 3.12 x64 mit `py`-Launcher
- Visual Studio 2022 mit „Desktopentwicklung mit C++“
- CMake aus Visual Studio oder im `PATH`
- installierte OpenCL-Laufzeit und kompatibler GPU-Treiber für historische MCMS1/MCMS2-Daten
- optional MSYS2/MinGW g++ für den historischen v0.7.0-Recovery-Kandidaten

Qt6 ist nur für das optionale MyceliaDB-Studio nötig. Der Datenbankserver und das WebCMS lassen sich ohne Qt6 bauen.

## Frischer Build

Nach dem Entpacken in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\start.ps1
```

`install.ps1` baut beide nativen Komponenten, legt `.venv` und die lokalen Datenverzeichnisse an, installiert die Python-Abhängigkeiten und erzeugt beim ersten Lauf über `tools/setup.py` eine neue `.env` mit installationsspezifischen Schlüsseln.

## Einzelne Komponenten bauen

```powershell
.\build_security_sdk.ps1
.\build_native_db.ps1
```

Historischer Recovery-Build, nur bei Bedarf:

```powershell
.\build_recovery_v070.ps1
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Absichtlich enthaltene Binärabhängigkeiten

Obwohl dies ein Entwicklerpaket ist, enthält es wenige zwingende Binärabhängigkeiten:

- `third_party/prebuilt/CC_OpenCl.dll`: unveränderlicher, per SHA-256 gepinnter Kompatibilitätsanker zum Lesen historischer MCMS1/MCMS2-Daten.
- `third_party/prebuilt/mycelia_gpu_envelope.dll`: ausgelieferte GPU-Bridge.
- OpenCL-Importbibliotheken und Laufzeitdateien in den SDK-Verzeichnissen, die für die vorgesehenen Build-/Recovery-Wege benötigt werden.

Die produktive Security-DLL wird nicht aus einem fremden laufenden System übernommen. `install.ps1` verifiziert und installiert die gepinnte Paketdatei.

## Absichtlich nicht enthalten

- `.env` und sämtliche Schlüssel oder Passworthashes
- Datenbank-Snapshots, Backups, Audit- und Nutzerdaten
- `.venv` und installierte Python-Pakete
- gebaute MyceliaDB-Runtime
- CMake-/MSBuild-Caches und erzeugte Objektdateien
- Test-, Python- und Editor-Caches
- lokale Screenshots, PDFs und nicht eingebundene Arbeitsdateien

## Dokumentation

Der Einstieg ist `docs/TECHNISCHE_DOKUMENTATION.md`. Die Datenbank ist ausführlich in `docs/MYCELIADB_ARCHITEKTUR.md`, die Kryptografie in `docs/SECURITY_SDK.md` beschrieben. `docs/HERKUNFT_NATIVE_KOMPONENTEN.md` erklärt die Entwicklung aus CC_OpenCl_Enterprise, Mycelia-Security-SDK und der früheren MyceliaDB-Plattform, ohne deren historische Seed-, Direct-Ingest- oder VRAM-Aussagen mit dem heutigen gehärteten v0.8.0-Ist-Stand zu vermischen.

## Sicherheitsregel

Niemals einen echten produktiven `.env`- oder `data`-Ordner in ein Entwicklerpaket kopieren. Ein neues Team erzeugt eigene lokale Schlüssel. Historische Backups dürfen nur zusammen mit einem autorisierten Schlüsseltransfer und über einen getrennten, kontrollierten Recovery-Prozess übergeben werden.

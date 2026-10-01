# Mycelia WebCMS v0.8.0 – Developer Source Release

Veröffentlicht: 1. Oktober 2026

## Überblick

Mycelia WebCMS v0.8.0 ist eine SQL-freie Content-, Commerce- und Community-Plattform. Fachobjekte werden ausschließlich als native MyceliaDB-Nodes persistiert. Sensible Payloads werden vor der Speicherung durch die Mycelia-Security-Schicht verschlüsselt und authentifiziert.

Dieses Release enthält den vollständigen, neu kompilierbaren Entwicklerstand für Windows x64.

## Enthaltene Plattformbereiche

- CMS-Seiten und sicherer Richtext
- Benutzerkonten, Argon2id und Datenschutz-Center
- Multi-Shop und globaler Marktplatz
- Produkte, Bestellungen, Blog und Double-Opt-in-Newsletter
- globale und shopbezogene Foren und Knowledge Base
- Creator-Profile und Mitgliederbereiche
- Downloads, Dokumente und Support-Tickets
- Community-Feed
- gemeinsamer verschlüsselter Media-Layer

## MyceliaDB

- alleinige Persistenz ohne SQL oder SQLite
- manuelle Anwendungs-Nodes und Links
- natives V2-Snapshotformat
- `ERASE_NODE` für echte Löschung manueller Nodes
- authentifiziertes Loopback-Steuerprotokoll
- Dokumentingestion und abgeleiteter Resonanzgraph
- atomarer Snapshot-Austausch und CMS-seitiger Snapshot-HMAC

## Security

- MCMS3 als aktuelles Schreibformat
- zufällige Nonces und 256-Bit-Record-Keys
- HMAC-SHA256-Domain-Separation
- Authentifizierung vor Entschlüsselung
- Bindung verschlüsselter Payloads an die vollständige Node-ID
- namespaced Blindindizes für Gleichheitssuchen
- MCMS1-/MCMS2-Lesekompatibilität für Recovery
- gepinnte historische Security-Runtime mit SHA-256-Vertrag
- CSRF, Sessionablauf, Rate Limits, Host-Allowlist und restriktive Header
- Bilddekodierung, Re-Encoding, Integritätsprüfung und autorisierte Medienausgabe

## Technologische Herkunft

Die Dokumentation ordnet drei verwandte öffentliche Projekte ein:

- `kruemmel-python/CC_OpenCl_Enterprise`
- `kruemmel-python/Mycelia-Security-SDK`
- `kruemmel-python/CMS-MyceliaDB-Enterprise`

Sie trennt historische GPU-, Seed-, Direct-Ingest- und VRAM-Mechanismen ausdrücklich vom aktuellen v0.8.0-Ist-Stand.

## Build

Voraussetzungen:

- Windows 10/11 x64
- Python 3.12 x64
- Visual Studio 2022 mit Desktopentwicklung für C++
- OpenCL-fähige Laufzeit für historische MCMS1-/MCMS2-Pfade
- optional MSYS2/MinGW für den v0.7.0-Recovery-Kandidaten

Installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
.\start.ps1
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

## Verifikation

- beide nativen Komponenten wurden aus einer frischen Entpackung des Entwicklerpakets erfolgreich neu kompiliert
- 64 vorhandene Python-Tests bestanden vor der Veröffentlichung
- das Paket enthält keine `.env`, Datenbank-Snapshots, Backups, Nutzerdaten oder lokale virtuelle Umgebung
- ein dateiinternes `PACKAGE_MANIFEST_SHA256.txt` listet die Hashes der Paketdateien
- die separate `.zip.sha256`-Datei authentifiziert den veröffentlichten ZIP-Download gegen Übertragungsfehler und unbeabsichtigte Änderung

## Bekannte Grenzen

- keine mehrbefehlige ACID-Transaktion in MyceliaDB
- CMS-Suchen verwenden derzeit häufig Präfixscan plus Blindindexvergleich
- die Engine serialisiert Befehle über einen zentralen Mutex
- die aktuelle Resonanzdiffusion läuft CPU-seitig; die GPU-Bridge ist kein allgemeiner Query-Beschleuniger
- MCMS1/MCMS2 können von historischer Runtime-/OpenCL-Kompatibilität abhängen
- automatisierte Online-Rotation des CMS-Master-Keys ist noch nicht implementiert

## Lizenz

Dieses Release wird unter der GNU General Public License Version 3 veröffentlicht. Maßgeblich ist die Datei `LICENSE`.

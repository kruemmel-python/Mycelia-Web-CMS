# Mycelia WebCMS – MCMS2 Recovery und MCMS3 Migration

## Ziel

MCMS1/MCMS2 bleiben ausschließlich als Legacy-Lesepfad erhalten. Neue Datensätze werden ab diesem Stand als **MCMS3** geschrieben.

MCMS3 verwendet für die eigentliche Record-Verschlüsselung keinen GPU-/OpenCL-Stream mehr. Der Stream wird ausschließlich aus HMAC-SHA256, dem 256-Bit-Master-Key, einer zufälligen 16-Byte-Nonce und der Record-ID abgeleitet. Damit bleibt die Entschlüsselung unabhängig von GPU-Modell, OpenCL-Treiber, Compiler und Floating-Point-Verhalten.

## Sicherheitsregeln

1. Recovery verändert im Probe-Modus keinerlei Daten.
2. Eine Migration startet nur nach expliziter Eingabe `MIGRATE`.
3. Wenn auch nur ein authentifizierter Legacy-Datensatz nicht entschlüsselt werden kann, wird **nichts migriert**.
4. Vor dem ersten Schreibzugriff erzeugt die Migration automatisch ein historisches natives MyceliaDB-Backup inklusive HMAC-Sidecar.
5. Jeder neu geschriebene MCMS3-Datensatz wird sofort aus der DB zurückgelesen und erneut entschlüsselt.
6. Erst nach vollständigem Erfolg wird `cms-live.mycdb` neu geschrieben.
7. Recovery-Reports enthalten keine Klartexte.

## Historischer v0.7.0 Recovery-Kandidat

`build_recovery_v070.ps1` baut die historische Security-SDK-Quelle mit dem ursprünglichen MinGW/MSYS2-Buildprofil (`-O3 -march=native -ffast-math ...`). Die erzeugte DLL landet ausschließlich unter:

`recovery_runtimes\v070_mingw\CC_OpenCl.dll`

Die produktive `vendor\CC_OpenCl.dll` wird dadurch nicht verändert.

## Vorgehen

CMS zuerst mit `Ctrl+C` beenden.

### 1. Nur prüfen

```powershell
.\recover_mcms2.ps1
```

Der Probe-Modus:

- startet eine isolierte MyceliaDB,
- lädt den authentifizierten `cms-live.mycdb`,
- baut bei Bedarf den historischen v0.7.0-Recovery-Kandidaten,
- testet alle verfügbaren Recovery-Runtimes und alle erkannten GPU-Indizes,
- prüft, ob der Klartext valides UTF-8/JSON ergibt,
- erzeugt einen Report unter `data\recovery\`,
- verändert keinen Datenbankwert.

### 2. Nur wenn Probe vollständig erfolgreich ist: migrieren

```powershell
.\recover_mcms2.ps1 -Migrate
```

Dann exakt eingeben:

```text
MIGRATE
```

Die Migration ist fail-closed. Solange nicht alle Legacy-Datensätze lesbar sind, wird kein Datensatz verändert.

## Nach erfolgreicher Migration

Normal starten:

```powershell
.\start.ps1
```

Alle neu angelegten oder geänderten CMS-Datensätze werden automatisch im MCMS3-Format gespeichert.

## Recovery-Runtime aus einer noch älteren Installation ergänzen

Falls eine historische `CC_OpenCl.dll` aus einem alten, tatsächlich funktionierenden Projektordner vorhanden ist, kann sie als zusätzlicher Kandidat abgelegt werden, z. B.:

`recovery_runtimes\mein_alter_stand\CC_OpenCl.dll`

`recover_mcms2.ps1` findet alle `CC_OpenCl.dll` unter `recovery_runtimes` automatisch. Eine produktive DLL wird dabei nie ersetzt.

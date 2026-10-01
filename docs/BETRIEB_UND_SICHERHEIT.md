# Betrieb, Backup, Recovery und Sicherheitsgrenzen

## 1. Installation

Der vorgesehene Einstieg ist:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Die Installation:

1. verlangt Python 3.12 x64,
2. prüft sicherheitsrelevante native Quellen und die gepinnte Runtime,
3. baut und verifiziert Security SDK und MyceliaDB,
4. erzeugt eine lokale virtuelle Python-Umgebung,
5. installiert Flask, Waitress, Argon2 und Pillow,
6. erzeugt bzw. härtet `.env`,
7. legt Backup- und Auditverzeichnisse an,
8. beschränkt Windows-ACLs auf aktuellen Benutzer, SYSTEM und Administratoren.

Schlägt ein sicherheitsrelevanter Schritt fehl, wird die Installation abgebrochen.

## 2. Startsequenz

```powershell
.\start.ps1
```

Die Startreihenfolge ist Teil des Sicherheitsmodells:

1. Runtime-Marker, DB-Executable, virtuelle Umgebung und `.env` prüfen.
2. Konfiguration in den Prozess laden.
3. zufälligen DB-Token mit 32 Zufallsbytes erzeugen.
4. `MYCELIA_DB_STORAGE_ROOT` auf das kontrollierte Backupverzeichnis setzen.
5. sicherstellen, dass Port 4555 nicht bereits belegt ist.
6. die eigene native DB starten.
7. Banner, `AUTH`, `PING` und V2-Capabilities prüfen.
8. erst danach Flask/Waitress starten.
9. beim Ende des Webprozesses auch die gestartete DB beenden.

Eine bereits laufende fremde DB wird nicht wiederverwendet, selbst wenn sie auf Loopback lauscht.

## 3. Konfigurationsregeln

Wesentliche Werte:

- `MYCELIA_CMS_MASTER_KEY`: exakt 32 Byte als Hex.
- Session-Schlüssel: mindestens 48 Zeichen.
- DB-Host: Loopback.
- normaler CMS-Host: ebenfalls Loopback, sofern kein bewusst konfigurierter Reverse Proxy verwendet wird.
- öffentliche Basis-URL: HTTPS, außer bei Loopback-Entwicklung.
- DB-Pool: 1 bis 16 Verbindungen, Standard 4.
- Trusted Proxy Hops: 0 bis 2.
- SMTP: STARTTLS oder implizites SSL.

Geheimnisse gehören nicht in Versionsverwaltung, Screenshots oder Diagnoseausgaben.

## 4. Web-Sicherheitskontrollen

### Sessions

Flask-Sessions sind signiert. Administrative und Benutzeranmeldungen speichern zusätzlich Authentifizierungszeitpunkte; abgelaufene Sitzungen werden bei geschützten Zugriffen nicht akzeptiert.

### CSRF

Alle unsicheren Methoden benötigen einen zufälligen Session-CSRF-Token. Formwert bzw. `X-CSRF-Token` werden konstantzeitnah verglichen. GET, HEAD und OPTIONS verändern keinen Zustand.

### Host und Proxy

Host-Allowlisting verhindert Host-Header-Missbrauch. Weiterleitungsheader werden nicht pauschal vertraut. ProxyFix darf nur entsprechend der expliziten Anzahl eigener Proxy-Hops aktiviert werden.

### Rate Limits

Ein thread-sicherer In-Process-Limiter schützt sensible Kontrollpunkte wie Login. Clientidentität basiert nicht direkt auf einem ungeprüften `X-Forwarded-For`-Header. Internetweites DDoS-Filtering bleibt Aufgabe eines vorgeschalteten Reverse Proxys/WAF.

### Inhalte und Medien

Richtext wird als validiertes strukturiertes AST gespeichert, nicht als frei ausführbares Benutzer-HTML. Bilder werden wirklich dekodiert, begrenzt, EXIF-orientiert, von Metadaten befreit und als kanonisches JPEG neu kodiert. Die zentrale Medienroute prüft vor Ausgabe erneut die Berechtigung am Elternobjekt und sendet `private, no-store` sowie `nosniff`.

## 5. Backupmodell

### 5.1 Live-Checkpoint

Nach fachlichen Schreiboperationen ruft der Backupmanager `SAVE_DB` auf und hält `cms-live.mycdb` aktuell. Daneben existiert eine HMAC-Sidecar-Datei.

Beim nächsten Start wird ein vorhandener Live-Checkpoint nur geladen, wenn die Sidecar vorhanden und gültig ist. Ein manipulierter Snapshot führt zum Abbruch statt zu einem stillen Restore.

### 5.2 Manuelle historische Backups

Historische Dateien folgen:

```text
mycelia-cms-YYYYMMDDTHHMMSSZ.mycdb
```

Namen und Pfade werden validiert und auf das konfigurierte Verzeichnis begrenzt. Restore-Ziele dürfen nicht durch freie Pfadangaben außerhalb dieses Bereichs gewählt werden.

### 5.3 HMAC der Snapshotdatei

Der Backup-Authentifizierungsschlüssel wird vom CMS-Master-Key abgeleitet:

```text
backup_auth_key = HMAC-SHA256(master_key,
                              "mycelia-cms/native-backup-auth/v1")
```

Der Datei-HMAC umfasst Dateiname und Dateiinhalt in Chunks. Der Vergleich nutzt eine konstante Vergleichsfunktion.

Die Sidecar schützt Integrität und Zuordnung, nicht die Vertraulichkeit aller Snapshotmetadaten.

## 6. Restore

Vor einem Restore:

1. Zielname gegen das erlaubte Muster prüfen.
2. Pfad auf das Backupverzeichnis begrenzen.
3. Sidecar laden.
4. erwarteten HMAC neu berechnen.
5. bei jeder Abweichung abbrechen.
6. erst danach `LOAD_DB` ausführen.

Nach erfolgreichem Laden rekonstruiert MyceliaDB abgeleitete Dokumentgraphen und stellt manuelle CMS-Nodes wieder her.

## 7. MCMS-Recovery

Recovery ist nicht dasselbe wie normaler Betrieb. Sie dient dazu, historische Ciphertexte mit der damals kompatiblen Runtime zu prüfen und anschließend in MCMS3 zu überführen.

Ein belastbarer Recovery-Probe muss für echte Kandidaten gleichzeitig nachweisen:

- Paket wird als MCMS1 oder MCMS2 erkannt,
- HMAC ist mit Master-Key und ursprünglicher Record-ID gültig,
- historische Streamruntime liefert entschlüsselbare Bytes,
- Ergebnis ist gültiges UTF-8,
- Ergebnis ist ein gültiges JSON-Objekt mit plausiblen Feldern.

Nur „DLL ließ sich laden“ oder „Ausgabe hat druckbare Zeichen“ ist kein Durchbruch.

Die Recovery-Werkzeuge ersetzen keine produktive DLL. Das verhindert, dass ein Experiment die Lesbarkeit des Livebestands verändert.

## 8. Datenschutzabläufe

Der persönliche Export aggregiert Daten aus Konto, Shop, Bestellungen, Creator, Mitgliedschaften, Tickets, Forum, Knowledge, Community, Medien und – bei Shopbesitz – Metadaten eigener Downloads/Dokumente.

Beim Hard Delete werden zugehörige manuelle Nodes mit `ERASE_NODE` entfernt. Wo ein Thread Inhalte anderer Personen enthält, kann das Elternobjekt anonymisiert werden, statt fremde Beiträge mitzulöschen. Persönliche Ticketkonversationen werden vollständig bereinigt. Historische normale Backups werden in den vorgesehenen Löschpfaden ebenfalls berücksichtigt.

Ein Auditwert für die Gegenstelle wird als Blindindex gespeichert, nicht als rohe IP-Adresse in benutzerorientierten Ereignissen.

## 9. Monitoring und Diagnose

Sinnvolle Prüfungen ohne Nutzdatenlogging:

- Prozess lebt und bindet nur an erwartete Adresse,
- DB-`PING` und Capabilitystring,
- Anzahl verfügbarer Poolverbindungen,
- Dauer von Präfixscan, GET, Snapshot und Restore,
- Anzahl Nodes pro Präfix,
- HMAC-Status des Live-Checkpoints,
- Alter des letzten erfolgreichen Checkpoints,
- Fehlerzähler getrennt nach Protokoll, Auth, HMAC und JSON-Schema,
- freier Speicherplatz im Backupbereich.

Nicht loggen:

- Master-Key, Session-Key oder DB-Token,
- Klartext-Payloads,
- Passwort- oder Bestätigungstoken,
- vollständige Ciphertexte ohne Diagnosegrund,
- rohe personenbezogene Adressen.

## 10. Performance ohne Sicherheitsabbau

Sichere Optimierungsreihenfolge:

1. langlebige gepoolte DB-Verbindungen beibehalten,
2. gepuffertes Socket-I/O und explizites Flush verwenden,
3. Anzahl Einzel-GETs messen,
4. serverseitige Blindindex-/Property-Indizes ergänzen,
5. `GET_MANY`/Batch-Protokoll einführen,
6. Checkpointhäufigkeit und -kosten messen, ohne Haltbarkeit still zu reduzieren,
7. MCMS3-Byteoperationen vektorisieren/optimieren,
8. erst danach Parallelität des Engine-Locks umbauen.

Sicherheit darf nicht zugunsten von Geschwindigkeit durch Abschalten von HMAC, CSRF, Berechtigungsprüfung, Snapshotprüfung oder Eingabevalidierung reduziert werden.

## 11. Störfälle

### DB startet nicht

- Portbelegung prüfen.
- Runtime-Marker und Executable prüfen.
- sicherstellen, dass Start über `start.ps1` erfolgt, damit Token und Storage Root gesetzt werden.
- Capabilityantwort prüfen.

### Daten nach Schlüsseländerung unlesbar

- Anwendung stoppen.
- neuen Schlüssel nicht weiter verwenden.
- gesicherte alte `.env` bzw. autorisierte Key-Kopie wiederherstellen.
- Recovery nur an Kopien durchführen.
- keine Snapshots überschreiben.

### Snapshot-HMAC ungültig

- nicht laden.
- Original und Sidecar unverändert sichern.
- Dateiname, Paarbildung und mögliche Teilkopie prüfen.
- letzten verifizierten Snapshot auswählen.

### Legacy-Daten schlagen fehl

- Paketversion und originale Record-ID bestimmen.
- gepinnte historische Runtime verwenden.
- Architektur/OpenCL prüfen.
- Recovery-Probe gegen Backupkopie laufen lassen.
- erst nach erfolgreichem JSON-Nachweis migrieren.

## 12. Deployment hinter Reverse Proxy

Für öffentlichen Betrieb:

- WebCMS intern an Loopback binden,
- TLS am eigenen Reverse Proxy terminieren,
- nur die notwendigen Proxy-Header setzen,
- exakt passende Proxy-Hop-Anzahl konfigurieren,
- DB-Port niemals weiterleiten,
- HSTS erst aktivieren, wenn HTTPS dauerhaft korrekt ist,
- Backup- und `.env`-Verzeichnisse nicht als statische Dateien exponieren.

## 13. Recovery-Ziele

Für einen belastbaren Betrieb sollten getrennt festgelegt werden:

- **RPO:** maximal tolerierter Datenverlust seit dem letzten gültigen Checkpoint.
- **RTO:** maximal tolerierte Wiederanlaufzeit inklusive HMAC-Prüfung und Graphrekonstruktion.
- Aufbewahrungszeit historischer Backups.
- Offline-/Offsite-Kopie des Master-Keys mit strengem Zugriff.
- regelmäßig getesteter Restore auf einer isolierten Instanz.

Ein ungeprüftes Backup ist nur eine Datei, kein nachgewiesener Wiederherstellungsplan.

# Mycelia Security SDK und kryptografische Datenhülle

Die native Bibliothek besitzt eine längere Vorgeschichte als allgemeine OpenCL-Compute-Schicht. [Herkunft der nativen Komponenten](HERKUNFT_NATIVE_KOMPONENTEN.md) dokumentiert diese Entwicklung und grenzt historische Direct-Ingest-/VRAM-Mechanismen vom aktuellen MCMS3-WebCMS ab.

## 0. Herkunft und Sicherheitsentwicklung

Die ursprüngliche Schnittstelle stammt aus dem eigenständigen Projekt [Mycelia-Security-SDK](https://github.com/kruemmel-python/Mycelia-Security-SDK). Es stellte GPU-Kontext, 64-Bit-Seed und offsetfähige In-place-Streamverarbeitung über eine C-API für C/C++, Python und C# bereit. Vault und Chat waren frühe Demonstratoren dieses Modells.

WebCMS v0.8.0 verwendet eine gehärtete Weiterentwicklung, nicht unverändert das historische Sicherheitsprotokoll. Der alte `myc_set_seed`-Pfad bleibt für MCMS1-Lesen erhalten. `myc_set_key_256` und ein zusätzlicher HMAC-SHA256-Stream schützen MCMS2. Neue Pakete verwenden MCMS3 und sind nicht mehr von der GPU-Reproduzierbarkeit abhängig.

Die kryptografische Sicherheit des aktuellen Schreibpfads wird nicht mit Geheimhaltung der DLL oder „Chaos“ begründet. Sie beruht auf einem 256-Bit-Master-Key, zufälligen Nonces, HMAC-SHA256-Key-Derivation, getrennten Schlüsselzwecken, Record-ID-Bindung und Authentifizierung vor Entschlüsselung. Die native Herkunft erklärt die API und Legacy-Kompatibilität; die folgenden Abschnitte spezifizieren den aktuellen Schutzvertrag.

## 1. Aufgabe der Security-Schicht

Das Security SDK schützt Fachobjekte, bevor sie MyceliaDB erreichen. Es erfüllt vier getrennte Aufgaben:

1. **Vertraulichkeit:** Inhalte sind ohne Master-Key nicht lesbar.
2. **Integrität und Authentizität:** Veränderungen oder ein falscher Schlüssel werden erkannt.
3. **Datensatzbindung:** Ein Paket ist an seine konkrete Node-ID gebunden.
4. **Suchbarkeit ausgewählter Gleichheitsmerkmale:** Blindindizes ermöglichen Vergleiche, ohne den Klartext zu speichern.

Die Schicht besteht aus zwei Teilen:

- `cms/security.py`: Paketformat, Key-Derivation, HMAC-Prüfung, MCMS3-Stream, Blindindizes und sichere Nutzung der nativen API.
- native DLL aus `third_party/Mycelia-Security-SDK_v2_secure`: OpenCL-Kontext sowie historische MCMS1-/MCMS2-Streamverarbeitung.

Neue Schreibvorgänge verwenden **MCMS3**. Die native GPU-abhängige Verarbeitung bleibt notwendig, um bestehende MCMS1- und MCMS2-Daten lesen und migrieren zu können.

## 2. Schlüsselmaterial

### 2.1 CMS-Master-Key

`MYCELIA_CMS_MASTER_KEY` muss genau 32 Byte, hexadezimal kodiert, enthalten. Er ist die Wurzel für:

- datensatzspezifische Verschlüsselungsschlüssel,
- datensatzspezifische Authentifizierungsschlüssel,
- Blindindizes,
- Snapshot-HMAC-Schlüssel.

Der Master-Key wird nicht direkt als Stream wiederverwendet. Alle Anwendungen erhalten durch HMAC-basierte Domain Separation voneinander getrennte Schlüsselräume.

### 2.2 Ableitungsfunktion

Die Python-Schicht verwendet sinngemäß:

```text
derive(purpose, nonce, record_id) =
    HMAC-SHA256(master_key,
                purpose || 0x00 || nonce || 0x00 || UTF8(record_id))
```

`purpose` unterscheidet beispielsweise MCMS3-Verschlüsselung von MCMS3-Authentifizierung. `nonce` trennt zwei Verschlüsselungen desselben Datensatzes. `record_id` bindet das Ergebnis an den Ziel-Node.

Domain Separation verhindert, dass derselbe abgeleitete Schlüssel versehentlich für mehrere kryptografische Rollen verwendet wird.

### 2.3 Lebensdauer im Prozess

Der Master-Key liegt während des Betriebs notwendigerweise im Speicher des CMS-Prozesses. Die Implementierung hält ihn in einem veränderbaren Bytearray und überschreibt dieses beim Schließen. Temporäre native Puffer werden ebenfalls soweit möglich genullt.

Das ist eine Best-Effort-Maßnahme. Python, Betriebssystem, Crashdumps und Speicherabbilder können Kopien erzeugen, deren vollständige Löschung die Anwendung nicht garantieren kann. Prozessschutz, ACLs, kein Debugzugriff durch fremde Benutzer und gegebenenfalls Betriebssystem-Credential-Schutz bleiben erforderlich.

## 3. Einheitliches MCMS-Paketformat

Das gespeicherte Token ist Base64url-kodiert und enthält vor der Kodierung:

```text
+----------------+----------------+----------------------+----------------+
| Version 5 Byte | Nonce 16 Byte  | Ciphertext variabel | HMAC 32 Byte   |
+----------------+----------------+----------------------+----------------+
```

Versionsmarker sind `MCMS1`, `MCMS2` und `MCMS3`. Base64url wurde gewählt, damit der Wert ohne Leerzeichen und Steuerzeichen durch das zeilenbasierte DB-Protokoll transportiert werden kann.

Der Authentifizierungstag deckt den Paketkopf, den Ciphertext und zusätzlich die Record-ID ab. Die genaue Key-Domain ist versionsspezifisch (`auth`, `auth2`, `auth3`).

## 4. MCMS3 – aktueller Schreibpfad

### 4.1 Verschlüsselungsablauf

Für jedes neue oder geänderte Fachobjekt:

1. Objekt als kompaktes UTF-8-JSON serialisieren.
2. 16 Byte kryptografisch zufälliges Nonce erzeugen.
3. 256-Bit-Record-Key mit Purpose `enc3`, Nonce und Record-ID ableiten.
4. HMAC-SHA256-Counterstream erzeugen.
5. Klartext und Stream byteweise XOR-verknüpfen.
6. separaten 256-Bit-Tag-Key mit Purpose `auth3` ableiten.
7. HMAC-SHA256 über Version, Nonce, Ciphertext und Record-ID berechnen.
8. Paket zusammensetzen und Base64url-kodieren.

Der Stream wird blockweise sinngemäß gebildet:

```text
block_i = HMAC-SHA256(record_key,
                     "MYCELIA-MCMS3-STREAM\0" || uint64_be(i))
```

Die Blöcke werden aneinandergehängt und auf die Nutzdatenlänge gekürzt.

### 4.2 Warum MCMS3 CPU-seitig arbeitet

Historische GPU-Streams konnten von exakter OpenCL-Runtime, GPU-Verhalten und Compilerartefakt abhängen. Das erschwert langfristige Wiederherstellung. MCMS3 verwendet deshalb einen vollständig spezifizierten HMAC-SHA256-Counterstream im Python-Prozess. Für denselben Key, dieselbe Record-ID und dasselbe Nonce ist er plattformunabhängig reproduzierbar.

Die Sicherheit wird dadurch nicht verringert. Entscheidend sind:

- 256-Bit-Master-Key,
- zufälliges Nonce,
- getrennte Record-Keys,
- unverwechselbare Stream-Domain,
- Encrypt-then-MAC-artige Prüfung vor Entschlüsselung.

Die GPU ist keine Voraussetzung für starke Verschlüsselung.

### 4.3 Entschlüsselung

1. Base64url strikt dekodieren.
2. Mindestlänge und Versionsmarker prüfen.
3. Nonce, Ciphertext und Tag trennen.
4. erwarteten HMAC mit `auth3` und Record-ID berechnen.
5. Tags mit `hmac.compare_digest` vergleichen.
6. Bei Abweichung sofort abbrechen; kein Klartext wird ausgewertet.
7. `enc3`-Record-Key und Counterstream ableiten.
8. XOR zur Rückgewinnung des Klartexts.
9. UTF-8 und JSON parsen.
10. ausschließlich ein JSON-Objekt akzeptieren.

Der Ablauf „authentifizieren, dann entschlüsseln“ verhindert, dass manipulierte Ciphertexte in nachgelagerte Parser gelangen.

## 5. MCMS2 – kompatibler GPU-Lesepfad

MCMS2 verwendet ebenfalls einen vollen 256-Bit-Record-Key. Dieser wird mit Purpose `enc2` aus Master-Key, Nonce und Record-ID abgeleitet und über `myc_set_key_256` an den nativen Kontext übergeben.

Der native Core verarbeitet Daten in Blöcken von 65.536 Byte:

1. Für den Blockindex wird per HMAC mit Domain `MYCELIA-GPU-BLOCK-V2` ein Block-Seed abgeleitet.
2. Der deterministische SubQG-/OpenCL-Zustand wird auf diesen Blockzustand gesetzt.
3. Ein Simulationsschritt erzeugt einen GPU-Kanal im Key-Cache.
4. Float-Bitmuster werden in Streambytes transformiert.
5. Zusätzlich wird ein HMAC-SHA256-Maskenstream mit Domain `MYCELIA-MASK-V2` eingemischt.
6. Ergebnis und Daten werden XOR-verknüpft.

Der zusätzliche HMAC-Maskenstream stellt sicher, dass die Vertraulichkeit nicht allein von einem auf 64 Bit verdichteten GPU-Seed abhängt. Die Paketintegrität wird außerhalb davon mit dem getrennten `auth2`-Key geprüft.

MCMS2 wird vom aktuellen Code nicht mehr für neue Pakete verwendet. Sein Wert ist Recovery und Migration vorhandener Datensätze.

## 6. MCMS1 – historischer Legacy-Pfad

MCMS1 stammt aus dem älteren Seed-Modell. Die Python-Schicht leitet mit Purpose `seed` Material ab und interpretiert daraus einen 64-Bit-Little-Endian-Seed. Dieser wird über `myc_set_seed` in den nativen Legacy-Kontext gesetzt.

Die Capability des nativen SDK kennzeichnet diesen Pfad ausdrücklich als `legacy_seed=decrypt-only`. Neue Daten dürfen nicht in MCMS1 geschrieben werden. Das Format bleibt lesbar, damit vorhandene Daten nicht allein durch ein Versionsupdate verloren gehen.

Gerade bei MCMS1/2 ist die historische Binärkompatibilität wichtig. Ein syntaktisch kompatibler Neubau kann einen anderen Stream erzeugen. Deshalb wird die bekannte vorgebaute `CC_OpenCl.dll` als Persistenzvertrag behandelt und per SHA-256-Fingerprint festgehalten.

## 7. Native Security-SDK-API

Die C-API stellt einen undurchsichtigen Kontext bereit. Relevante Funktionen:

| Funktion | Bedeutung |
|---|---|
| `myc_init` | globale Initialisierung/OpenCL-Erkennung |
| `myc_get_device_count` | verfügbare Geräte zählen |
| `myc_create_context` | Kontext für ein GPU-Gerät anlegen |
| `myc_destroy_context` | Kontext und sensibles Material freigeben |
| `myc_set_seed` | historischen 64-Bit-Seed setzen |
| `myc_set_key_256` | vollständigen 256-Bit-Schlüssel setzen |
| `myc_process_buffer` | Buffer ab Streamoffset symmetrisch XOR-verarbeiten |
| `myc_get_security_capabilities` | ABI-/Sicherheitsfähigkeiten melden |
| `myc_get_last_error` | letzte native Fehlerbeschreibung liefern |

Der Context hält unter anderem GPU-Index, Seed, 256-Bit-Key, Initialisierungsstatus und einen Key-Cache mit 256 × 256 Floatwerten. Beim Zerstören werden Key-Cache und Master-Key explizit überschrieben.

Die erwartete Capability enthält mindestens:

```text
mycelia-security-v2 key256=1 hmac_sha256_stream=1 legacy_seed=decrypt-only
```

Fehlt eine notwendige Fähigkeit, startet die Anwendung nicht stillschweigend mit einem schwächeren Verfahren.

## 8. Thread-Sicherheit

Der native Kontext besitzt veränderlichen Streamzustand. Die Python-Hülle schützt Set-Key/Set-Seed und Bufferverarbeitung deshalb mit einem Lock. Zwei Requests können denselben Kontext nicht gleichzeitig auf unterschiedliche Record-Keys umstellen.

MCMS3 benötigt diesen nativen kritischen Abschnitt nicht. Das reduziert die Abhängigkeit von GPU und globalem Kontext und ist neben optimierter XOR-Verarbeitung ein wichtiger Leistungsgrund für den aktuellen Pfad.

## 9. Blindindizes

### 9.1 Bildung

Ein suchbarer Wert wird zunächst normalisiert:

- führende und folgende Leerzeichen entfernen,
- interne Whitespacefolgen zusammenfassen,
- Unicode-/Stringdarstellung in Kleinschreibung per `casefold` überführen.

Danach:

```text
blind_index(namespace, value) =
    HEX(HMAC-SHA256(master_key,
                    "idx\0" || namespace || "\0" || normalized_value))
```

Das Resultat ist ein 64-stelliger Hexwert.

### 9.2 Warum Namespaces wichtig sind

Dieselbe E-Mail-Adresse erhält in `user-email` einen anderen Index als in `newsletter-email:<shop-id>`. Dadurch kann ein Beobachter nicht ohne Weiteres Gleichheit über fachlich getrennte Bereiche korrelieren.

Namespaces enthalten teilweise die Shop-ID. So ist ein Produktslug nur innerhalb seines Shops eindeutig und korrelierbar.

### 9.3 Eigenschaften und Leckage

Blindindizes ermöglichen exakte Gleichheitssuche, aber keine Bereichsabfrage oder Volltextsuche. Sie verbergen den Wert gegenüber einem Angreifer ohne Schlüssel, offenbaren jedoch:

- ob zwei Werte im gleichen Namespace gleich sind,
- wie häufig ein Index vorkommt,
- wann ein Index nach einer Mutation gleich bleibt oder wechselt.

Bei sehr kleinen möglichen Werteräumen schützt der geheime HMAC-Key gegen Offline-Wörterbuchtests, solange er geheim bleibt. Wird der Master-Key kompromittiert, können Kandidatenwerte berechnet werden. Blindindizes sind daher Suchkompromiss, keine perfekte Metadatenverbergung.

## 10. Record-Bindung und Replay

Da Record-ID in Schlüsselableitung und Tag eingeht, schlägt dieses Szenario fehl:

1. Angreifer kopiert `data` von Node A nach Node B.
2. Anwendung lädt das Paket mit Record-ID B.
3. Der erwartete HMAC unterscheidet sich.
4. Entschlüsselung wird abgebrochen.

Ein älterer gültiger Ciphertext desselben Nodes kann kryptografisch weiterhin gültig sein. MCMS allein bietet keinen monotonen Versionszähler gegen Same-Record-Rollback. Schutz gegen das Zurückspielen kompletter alter Zustände kommt aus kontrolliertem Backupzugriff, HMAC-authentifizierten Snapshots und Betriebsprozessen. Für strikten Anti-Rollback wären externe monotone Zustände oder signierte Versionketten nötig.

## 11. Passwortschutz ist getrennt

Benutzer- und Adminpasswörter werden nicht reversibel mit MCMS verschlüsselt, sondern als Argon2id-Hash geprüft. Das ist die richtige Trennung:

- Passwörter müssen verifiziert, nicht wiederhergestellt werden.
- Fachinformationen wie E-Mail, Adresse oder Bestelldaten müssen entschlüsselt werden können.

Der Passwort-Hash kann selbst innerhalb des verschlüsselten Benutzerobjekts liegen, bleibt aber ein Argon2id-Hash.

## 12. Fehlerverhalten

Typische harte Fehler sind:

- ungültiges Base64url,
- unbekannte MCMS-Version,
- zu kurzes Paket,
- HMAC-Abweichung,
- falsche Record-ID,
- falscher Master-Key,
- ungültiges UTF-8,
- JSON ist kein Objekt,
- fehlende native Capability für MCMS1/2,
- OpenCL-/Gerätefehler im Legacy-Pfad.

Diese Fehler dürfen nicht in „leerer Datensatz“ umgedeutet werden, weil das Korruption oder einen Schlüsselkonflikt verschleiern würde.

## 13. Build- und Laufzeitvertrag

`build_security_sdk.ps1` baut den Security Core mit MSVC, Optimierung, x64-Runtime und OpenCL 1.2. Anschließend werden ABI und Capability geprüft.

Der Build ersetzt absichtlich nicht automatisch die historisch gepinnte Persistenzruntime. Für alte GPU-basierte Ciphertexte ist nicht nur die Funktionssignatur, sondern der exakt reproduzierte Stream relevant. Der bekannte Hash der ausgelieferten Runtime dient deshalb als Kompatibilitätsanker.

Recovery-Werkzeuge müssen Compiler, DLL, GPU/OpenCL-Laufzeit, Master-Key, Record-ID und Paketversion gemeinsam betrachten. Ein erfolgreicher DLL-Load beweist noch nicht, dass ein historischer Ciphertext korrekt entschlüsselt wird; entscheidend ist gültiger HMAC plus gültiges JSON für echte Datensätze.

## 14. Bedrohungsmodell

### Geschützt gegen

- Lesen gestohlener `data`-Properties oder Snapshots ohne Master-Key,
- unbemerkte Änderung des Ciphertexts,
- Verschieben eines Ciphertexts auf eine andere Node-ID,
- Klartextspeicherung suchbarer E-Mail-/Slug-/Owner-Beziehungen,
- stilles Downgrade auf fehlende native Sicherheitsfähigkeiten.

### Nicht allein geschützt gegen

- vollständige Kompromittierung des laufenden CMS-Prozesses,
- Diebstahl von `.env` und Snapshot durch denselben privilegierten Benutzer,
- Traffic-Inspektion durch einen ausreichend privilegierten lokalen Prozess,
- Metadatenanalyse von Node-IDs, Typen, Counts und Blindindexgleichheit,
- XSS/Autorisierungsfehler in der Webschicht,
- Rollback auf einen älteren, damals gültigen Gesamtzustand,
- Verlust des einzigen Master-Keys.

## 15. Schlüsselrotation und Migration

Der aktuelle Code besitzt keinen vollständig automatischen Online-Key-Rotationsbefehl. Eine sichere Rotation benötigt:

1. verifiziertes Backup,
2. alten und neuen Master-Key in einem kontrollierten Migrationsprozess,
3. Entschlüsselung jedes Objekts mit alter Record-ID,
4. Neuberechnung aller Blindindizes mit dem neuen Key,
5. MCMS3-Neuverschlüsselung,
6. neuen nativen Snapshot und neue Sidecar,
7. vollständige Stichproben-/Integritätsprüfung,
8. erst danach kontrolliertes Entfernen alter Schlüsselkopien.

Nur `MYCELIA_CMS_MASTER_KEY` in `.env` auszutauschen macht bestehende Daten unlesbar und ist keine Rotation.

## 16. Kernaussage

Die Security-Schicht ist mehr als ein Aufruf einer GPU-DLL. Das aktuelle Sicherheitsprotokoll wird durch versionierte Pakete, datensatzspezifische HMAC-Ableitungen, Authentifizierung vor Entschlüsselung, Record-Bindung und namespaced Blindindizes gebildet. MCMS3 macht neue Daten unabhängig von historischer GPU-Reproduzierbarkeit; das native SDK bleibt als streng geprüfte Kompatibilitätsschicht für MCMS1 und MCMS2 erhalten.

Die technologische Herkunft liegt im [Mycelia-Security-SDK](https://github.com/kruemmel-python/Mycelia-Security-SDK). Die heute beanspruchten Sicherheitseigenschaften werden jedoch ausschließlich aus dem im v0.8.0-Paket enthaltenen Code, seinen Schlüssellängen, HMAC-Prüfungen, Build-Pins und Tests abgeleitet – nicht aus Marketingformulierungen oder der Annahme, dass ein Angreifer die DLL nicht besitzt.

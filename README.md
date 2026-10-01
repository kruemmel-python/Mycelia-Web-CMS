# Mycelia WebCMS v0.8.0 Security Core Hardened

Lizenz: [GNU General Public License Version 3](LICENSE)

Mycelia WebCMS v0.8.0 ist eine integrierte Content-, Commerce- und Community-Plattform auf **MyceliaDB Enterprise** und dem **Mycelia Security SDK**. Es gibt keine zweite SQL-/SQLite-Persistenzschicht. Fachobjekte werden als native MyceliaDB-Nodes gespeichert; sensible Nutzdaten liegen als verschlüsselter Payload in der Datenbank und werden über Blindindizes selektiert.

Technologische Herkunft: [CC_OpenCl_Enterprise](https://github.com/kruemmel-python/CC_OpenCl_Enterprise) stellt die allgemeine OpenCL-Compute-Linie dar, [Mycelia-Security-SDK](https://github.com/kruemmel-python/Mycelia-Security-SDK) die historische Kryptografie- und Streaming-API und [CMS-MyceliaDB-Enterprise](https://github.com/kruemmel-python/CMS-MyceliaDB-Enterprise) die frühere SQL-freie Plattformlinie. Das heutige v0.8.0 übernimmt daraus ausgewählte Prinzipien und Legacy-Kompatibilität, besitzt aber einen eigenen gehärteten MCMS3-Schreibpfad.

## Ausführliche technische Dokumentation

Die README ist die kompakte Projektübersicht. Die vollständige, aus dem Python- und C++-Quellcode abgeleitete Dokumentation befindet sich hier:

- [Technische Gesamtdokumentation](docs/TECHNISCHE_DOKUMENTATION.md)
- [MyceliaDB: Architektur, Resonanzgraph, Protokoll und Snapshotformat](docs/MYCELIADB_ARCHITEKTUR.md)
- [Security SDK: MCMS1/2/3, Schlüsselableitung und Blindindizes](docs/SECURITY_SDK.md)
- [Herkunft der nativen Komponenten und GPU-Architekturentwicklung](docs/HERKUNFT_NATIVE_KOMPONENTEN.md)
- [Betrieb, Backup, Recovery und Sicherheitsgrenzen](docs/BETRIEB_UND_SICHERHEIT.md)
- [Fachmodule, Node-Namensräume und Datenflüsse](docs/DATENMODELL_UND_MODULE.md)

## Plattformmodule

### CMS
- globale Seiten
- Entwurf / veröffentlicht
- sichere Plaintext-Inhalte ohne frei ausführbares HTML
- Admin-Dashboard, Backup und Restore

### Benutzerkonten und Datenschutz
- Selbstregistrierung und Login
- Argon2id-Passwörter
- Profil und Passwortänderung
- persönlicher JSON-Datenexport
- natives Hard Delete über `ERASE_NODE`
- Bereinigung normaler historischer CMS-Backups bei Kontolöschung

### Multi-Shop und Marktplatz
- ein Shop pro Konto
- Produkte: physisch, digital, Dienstleistung
- Bestellungen und Verkäuferstatus
- globaler Marktplatz über alle aktiven Shops
- Zahlungshinweise ohne fest verdrahteten externen Payment-Provider

### Blog und Newsletter
- eigener Shop-Blog
- Double-Opt-In-Newsletter
- STARTTLS oder SSL
- keine Tracking-Pixel
- Hard Delete bei Abmeldung

### Forum
- globales Forum
- zusätzlich eigenes Forum je Shop
- Themen und Antworten als getrennte MyceliaDB-Nodes
- registrierte Benutzer können globale oder shopbezogene Themen und Antworten erstellen

### Knowledge Base
- globale Knowledge Base für registrierte Benutzer
- shopbezogene Knowledge Base für Shopbesitzer
- Entwurf / veröffentlicht
- verschlüsselte Artikel-Payloads

### Creator-Plattform
- ein Creator-Profil je Benutzerkonto
- öffentliche Creator-Seite
- Creator-Beiträge
- öffentliche oder mitgliederbeschränkte Beiträge

### Mitgliederbereich
- freiwillige Mitgliedschaft je Shop
- Join/Leave als native Membership-Nodes
- Mitgliederinhalte können für Downloads, Dokumente und Creator-Beiträge verwendet werden
- Shopbetreiber sieht die Mitglieder seines Shops

### Downloadportal
- Downloadbereich je Shop
- Dateien werden **nicht als fremde Dateipfade** gespeichert, sondern als verschlüsselter Mycelia-Payload
- aktuell maximal 700.000 Byte pro Datei
- Sichtbarkeit öffentlich oder nur Mitglieder
- Downloadantworten werden immer als `application/octet-stream` + `attachment`, `nosniff`, restriktiver CSP und `private, no-store` ausgeliefert

### Ticketing
- Kunden können Support-Tickets je Shop eröffnen
- Shopbetreiber sieht Shop-Tickets
- getrennte Nachrichten-Nodes
- Status: `open`, `waiting_customer`, `waiting_shop`, `closed`
- Zugriff nur für Ticketkunde oder Shopbesitzer

### Dokumentenportal
- Dokumente je Shop
- Sichtbarkeit: `public`, `members`, `private`
- Entwurf / veröffentlicht
- Plaintext-Inhalt im verschlüsselten Payload

### Community
- globaler Feed
- Beiträge und Kommentare als getrennte Nodes
- nur angemeldete Benutzer schreiben
- öffentliche Lesbarkeit


## Einheitlicher sicherer Media-Layer

Bilder sind plattformweit integriert, ohne ein offen beschreibbares Upload-Verzeichnis einzufuehren. Der gemeinsame `SecureMediaRepository` verwendet denselben gehaerteten Bildpfad wie die Produktgalerie: JPEG/PNG/WebP werden wirklich dekodiert, Pixel-/Dimensions-/Byte-Limits geprueft, EXIF-Orientierung angewendet, Metadaten entfernt und als kanonisches JPEG neu kodiert. Anschliessend liegen die Bytes Base64-kodiert im verschluesselten `media:image:*` MyceliaDB-Payload.

Unterstuetzte Bildbereiche:
- globale CMS-Seiten (bis 3)
- Shop-Logo und Shop-Banner (je 1)
- Shop-Blog (bis 3 pro Beitrag)
- Creator-Avatar (1) und Creator-Beitraege (bis 3)
- Forum-Antworten inklusive Startbeitrag (bis 3)
- Knowledge-Artikel (bis 3)
- Community-Posts (bis 3) und Kommentare (1)
- Support-Ticket-Nachrichten/Screenshots (bis 3)
- Dokumentenportal (bis 3)
- Produkte behalten ihre sichere Galerie mit bis zu 3 Bildern

Die zentrale Medienroute `/media/content/<id>.jpg` prueft vor jeder Ausgabe den Parent-Datensatz und dessen Sichtbarkeit. Mitglieder-, private Dokument- und Ticketbilder sind dadurch nicht nur durch eine schwer erratbare ID geschuetzt, sondern durch dieselben fachlichen Zugriffsregeln wie ihr Elternobjekt. Alle Antworten werden `private, no-store` ausgeliefert.

Newsletter-E-Mails nutzen bewusst keine eingebetteten Inhaltsbilder. E-Mail-Clients und externe Ressourcen bilden eine eigene Privacy-/Tracking-Grenze und werden nicht mit dem internen CMS-Medienmodell vermischt. Downloadportal-Dateien bleiben eigenstaendige verschluesselte Downloadobjekte und werden nicht doppelt als Bilder gespeichert.

Der Datenschutzexport enthaelt die dem Benutzer gehoerenden verschluesselten Media-Fachobjekte inklusive `content_b64`. Beim Konto-Hard-Delete werden alle eigenen `media:image:*` Nodes nativ entfernt. Werden komplette Ticketthreads geloescht, werden auch Bilder der zugehoerigen Nachrichten entfernt, damit keine verwaisten Media-Nodes bestehen bleiben.

## Sicherheitsarchitektur

```text
Browser
  |
  v
WebCMS / Flask / Waitress
  |-- Session / CSRF / Rate Limits / Host Allowlist / CSP
  |
  +--> Mycelia Security Layer / Security SDK v2
  |       |
  |       +--> MCMS3 + 256-Bit Record-Key + HMAC-SHA256 Stream
  |       +--> MCMS1/2 GPU-Lesepfad + Record-HMAC + Blindindizes
  |
  +--> Secure MyceliaDB Control Protocol
          |
          +--> Loopback only
          +--> per-start 256-bit Capability Token
          +--> AUTH + PING + Capability Prüfung
          |
          v
      MyceliaDB Enterprise V2
          |
          +--> Graph-/Resonanzengine, optionale GPU-Bridge
          +--> native SAVE_DB / LOAD_DB
          +--> ERASE_NODE für manuelle Nodes
```

### Mycelia Security SDK v2
Die native Kompatibilitätsschicht nutzt:
- `myc_init`
- `myc_get_device_count`
- `myc_create_context`
- `myc_set_key_256` zum Lesen bestehender `MCMS2`-Datensätze
- `myc_set_seed` ausschließlich zum Lesen bestehender `MCMS1`-Datensätze
- `myc_process_buffer`
- `myc_get_security_capabilities`
- `myc_destroy_context`

Neue Datensätze werden als `MCMS3` geschrieben: ein plattformunabhängiger, CPU-seitiger HMAC-SHA256-Counterstream mit 256-Bit-Record-Key, zufälligem Nonce, getrenntem Record-HMAC und Bindung an die Node-ID. `MCMS2` und `MCMS1` bleiben als streng geprüfte Lesepfade für vorhandene Daten erhalten. Die native Runtime startet fail-closed, wenn die für diese historischen Pfade erforderlichen Capabilities fehlen. Suchbeziehungen werden über namespaced Blindindizes hergestellt.

### MyceliaDB Control Protocol
Der Client verwendet einen kleinen thread-sicheren Pool langlebiger, bereits authentifizierter Loopback-Verbindungen (`MYCELIA_DB_POOL_SIZE`, Standard 4). CR, LF und NUL sind in Protokollparametern und vollständigen Befehlen verboten. Dadurch kann ein Anwendungswert keine zweite Steuerprotokollzeile erzeugen. Defekte oder stale Poolverbindungen werden verworfen; möglicherweise bereits ausgeführte Schreibbefehle werden nach einem Verbindungsfehler nicht automatisch wiederholt.

### MyceliaDB
Das CMS verlangt eine Runtime mit:

```text
snapshot=V2 manual_nodes=1 erase_node=1
```

Ohne diese Capability startet das System nicht. Native Persistenz erfolgt ausschließlich über `.mycdb`.

MyceliaDB enthält zwei klar getrennte Ebenen: Das CMS nutzt manuelle Nodes als operativen, verschlüsselten Anwendungsgraphen. Zusätzlich kann die Engine importierte Dokumente in Segmente, Terme, Entitäten und semantische Felder zerlegen und über gewichtete Resonanzbeziehungen durchsuchen. Die ausführliche Beschreibung steht in [docs/MYCELIADB_ARCHITEKTUR.md](docs/MYCELIADB_ARCHITEKTUR.md).

## Node-Namensräume

```text
cms:page:*
acct:user:*
shop:store:*
shop:product:*
shop:product-image:*
shop:blog:*
media:image:*
shop:order:*
shop:newsletter:sub:*
shop:newsletter:campaign:*

platform:creator:profile:*
platform:creator:post:*
platform:member:*
platform:download:*
platform:ticket:*
platform:ticketmsg:*
platform:kb:*
platform:forum:topic:*
platform:forum:reply:*
platform:doc:*
platform:community:post:*
platform:community:comment:*
```

## Datenschutz
Der Benutzerexport umfasst zusätzlich zu Konto/Shop/Bestellungen auch Creator-Profil, Creator-Beiträge, Mitgliedschaften, eigene Tickets, Forum-Beiträge, Knowledge-Artikel, Community-Inhalte und – bei Shopbesitzern – Metadaten der eigenen Downloads und Dokumente.

Beim Kontolöschen werden die zugeordneten Plattform-Nodes ebenfalls nativ gelöscht. Bei Konversationen mit Inhalten anderer Benutzer wird der Elternbeitrag bei Bedarf anonymisiert, statt fremde Beiträge still mitzulöschen. Persönliche Ticketkonversationen werden vollständig entfernt, damit keine verwaisten Nachrichten an einem gelöschten Ticket zurückbleiben.

## Installation

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Danach:

```powershell
.\start.ps1
```

CMS:

```text
http://127.0.0.1:8088/cms
```

Benutzerbereich:

```text
http://127.0.0.1:8088/account
```

Marktplatz / Plattform:

```text
http://127.0.0.1:8088/marketplace
http://127.0.0.1:8088/forum
http://127.0.0.1:8088/knowledge
http://127.0.0.1:8088/creators
http://127.0.0.1:8088/community
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Der Stand enthält Tests für:
- DB-Protokoll
- native Backup-Integrität
- `ERASE_NODE` Capability
- Template-Härtung und CSRF
- Benutzer / Shop / Produkt / Blog / Newsletter
- Creator / Membership / Download / Ticket / Knowledge / Forum / Dokumente / Community
- Datenschutzexport und Plattform-Hard-Delete
- CR/LF/NUL Protocol Injection und Connection-Pool-Wiederverwendung
- MCMS3-Paketformat sowie MCMS1/2-Kompatibilität / Record-Bindung
- Fail-Closed Download-Sichtbarkeit sowie geschlossene Forum-/Ticketzustände

## Aktuelle Produktgrenzen
- ein Shop pro Benutzerkonto
- Dateien im integrierten Downloadportal bis 700 KB
- sichere Plattformbilder: Upload max. 280 KB pro Bild, max. 1600x1600 Ausgabe, JPEG/PNG/WebP als Eingang
- kein fest integrierter Payment-Provider
- Newsletterversand synchron und auf bestehende Sicherheitsgrenzen des Mailmoduls beschränkt
- öffentlicher Betrieb nur hinter TLS-Reverse-Proxy; MyceliaDB wird nicht extern freigegeben
- Inhalte bleiben Plaintext-Fachinhalt innerhalb verschlüsselter Payloads; kein frei ausführbarer User-Code


## Produktbilder / Galerie

Jedes Produkt kann bis zu drei Bilder besitzen. Uploads werden nicht anhand von Dateiendung oder Browser-MIME vertraut. Das CMS dekodiert JPEG/PNG/WebP mit Pillow, begrenzt Bytegroesse, Pixelzahl und Abmessungen, wendet EXIF-Orientierung an, entfernt Metadaten und kodiert das Bild als kanonisches JPEG neu. Die Bildbytes werden Base64-kodiert innerhalb eines eigenen `shop:product-image:*`-Datensatzes durch das Mycelia Security SDK verschluesselt und nativ in MyceliaDB persistiert. Es gibt kein oeffentlich beschreibbares `static/uploads`-Verzeichnis.

Bilder werden nur ueber `/media/products/<id>.jpg` ausgegeben. Die Route prueft Produktzuordnung und Sichtbarkeit; inaktive Produkte sind nur fuer ihren Besitzer als Vorschau sichtbar. Produktloeschung und Konto-Hard-Delete entfernen die zugehoerigen Media-Nodes.

Der persoenliche Datenschutzexport enthaelt fuer eigene Produktbilder sowohl Metadaten als auch `content_b64`, damit hochgeladene Inhalte vollstaendig exportierbar bleiben.


## MYCELIA RICHTEXT V1

Textformatierung wird nicht als Benutzer-HTML gespeichert. Formatierbare Felder verwenden ein strukturiertes, serverseitig validiertes AST-Schema `MYCELIA_RICHTEXT` Version 1. Der Browsereditor serialisiert ausschließlich erlaubte Blöcke und Marks; der Server normalisiert und validiert die Struktur erneut, bevor sie verschlüsselt in MyceliaDB gespeichert wird.

Profile:
- `compact`: Absatz, Zitat, Listen, Codeblock, Fett/Kursiv/Unterstrichen/Durchgestrichen/Inline-Code, sichere Links.
- `standard`: zusätzlich H2/H3, feste Größen/Farbtöne, Ausrichtung und Trennlinie.
- `document`: zusätzlich Tabellen und serverkontrollierte Button-Links.

Links sind auf relative interne Pfade und HTTPS beschränkt. Freies CSS, freie Farben, JavaScript-URLs, `data:`, `file:`, `blob:`, `<script>`, `<iframe>`, Roh-HTML und Inline-Eventhandler sind nicht Bestandteil des Schemas. Fremde Zwischenablageinhalte werden nur als `text/plain` übernommen. Newsletter bleiben bewusst Plaintext.


## v0.8.0 – Identity, Inventory & Authority Hardening

- Datenschutz-Hard-Delete löscht keine administrativen historischen Backups mehr; globales Purge ist ausschließlich Admin+CSRF+Bestätigung.
- Neue Konten entstehen erst nach E-Mail-Challenge. Profil-E-Mail-Wechsel werden erst nach Challenge wirksam.
- Newsletterdaten werden einem Account ausschließlich über eine explizite, verifizierte `account_id` zugeordnet; E-Mail-Stringgleichheit ist kein Besitznachweis.
- `pending` Bestellungen reservieren/vermindern keinen Bestand. Bestand wird atomar bei `pending -> paid` gebucht und bei erlaubter Stornierung zurückgegeben. Eine harte Status-Transition-Tabelle verhindert Rücksprünge.
- Expliziter Reverse-Proxy-Trust über `MYCELIA_CMS_TRUSTED_PROXY_HOPS` (0..2); Standard 0.
- Registrierung zählt erfolgreiche Vorgänge zum Abuse-Budget. Login hat getrennte IP- und Zielkonto-Budgets; Erfolg setzt nur das Zielkonto-Budget zurück.

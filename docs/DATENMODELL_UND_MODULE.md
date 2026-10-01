# Fachmodule, Node-Namensräume und Datenflüsse

## 1. Gemeinsames Repository-Muster

Fast alle Fachobjekte folgen demselben Speichervertrag:

```text
<kontrolliertes Präfix><32-stellige UUID>
    kind       = öffentlicher technischer Typ
    *_idx      = HMAC-basierte Gleichheitsindizes
    data       = authentifiziertes MCMS3-Paket des vollständigen Objekts
```

Die Python-Dataclasses definieren die erwartete Form des entschlüsselten JSON. Repositories sind verantwortlich für:

- ID- und Eingabevalidierung,
- Normalisierung,
- fachliche Eindeutigkeit,
- Erzeugung der Blindindizes,
- Verschlüsselung mit der vollständigen Node-ID,
- Lesen und Typkonstruktion,
- Autorisierungsnahe Auswahl,
- Checkpoint nach Mutationen.

Die DB kennt nicht die fachliche Bedeutung von `Product`, `ForumTopic` oder `SupportTicket`. Sie speichert Nodes. Die Bedeutung liegt in Namensraum, `kind`, verschlüsseltem Schema und Repositorycode.

## 2. Namensräume

| Präfix | Fachobjekt |
|---|---|
| `cms:page:` | globale CMS-Seite |
| `media:image:` | gemeinsames sicheres Bildobjekt |
| `acct:user:` | Benutzerkonto |
| `acct:pending-registration:` | ausstehende Registrierung |
| `acct:pending-email:` | ausstehende E-Mail-Änderung |
| `shop:store:` | Shop |
| `shop:product:` | Produkt |
| `shop:product-image:` | ältere/spezifische Produktgalerie |
| `shop:blog:` | Shop-Blogbeitrag |
| `shop:order:` | Bestellung |
| `shop:newsletter:sub:` | Newsletter-Abonnement |
| `shop:newsletter:campaign:` | Kampagne |
| `platform:creator:profile:` | Creator-Profil |
| `platform:creator:post:` | Creator-Beitrag |
| `platform:member:` | Shop-Mitgliedschaft |
| `platform:download:` | Downloadobjekt |
| `platform:ticket:` | Support-Ticket |
| `platform:ticketmsg:` | Ticketnachricht |
| `platform:kb:` | Knowledge-Artikel |
| `platform:forum:topic:` | Forumsthema |
| `platform:forum:reply:` | Forumantwort |
| `platform:doc:` | Shop-Dokument |
| `platform:community:post:` | Community-Beitrag |
| `platform:community:comment:` | Community-Kommentar |

Präfixe sind Teil des Schemas. Änderungen daran benötigen Migration, weil Record-ID in die Kryptografie eingeht.

## 3. Konten und Identität

Ein Benutzerkonto enthält Identitäts-, Kontakt-, Status- und Passwort-Hash-Informationen im verschlüsselten Objekt. Öffentlich vergleichbar sind nur erforderliche Blindindizes wie:

- `username_idx`,
- `email_idx`.

Registrierungs- und E-Mail-Bestätigungstoken werden ebenfalls nicht als Klartextindex abgelegt. Die Suche verwendet `token_idx`. Passwörter werden mit Argon2id gehasht.

Die Konto-ID ist die stabile interne Identität für Ownership und Autorisierung. Anzeigenamen ersetzen diese Referenz nicht.

## 4. Shop, Produkte und Bestellungen

### Shop

Ein Shop ist über `owner_idx` mit seinem Besitzer und über `slug_idx` mit seiner öffentlichen URL verbunden. Aktivstatus und weitere Details liegen im verschlüsselten Objekt.

### Produkt

Produkte tragen Blindindizes für Shop, Owner und shop-spezifischen Slug. Produktart kann physisch, digital oder Dienstleistung sein. Bilder liegen als getrennte verschlüsselte Nodes, damit Zugriff, Reihenfolge und Löschung unabhängig kontrolliert werden können.

### Bestellung

Bestellungen referenzieren Shop, Käufer und Verkäufer über getrennte Blindindizes. Die eigentlichen Bestellpositionen, Preise, Liefer-/Kontaktinformationen und Zustände liegen im verschlüsselten Payload.

Ein Blindindex ist kein Autorisierungsbeweis. Nach dem Finden eines Kandidaten wird das Objekt entschlüsselt und die echte ID-Beziehung sowie der angemeldete Benutzer werden geprüft.

## 5. Blog und Newsletter

Blogposts gehören zu einem Shop und Owner; ihr Slug ist innerhalb des Shops indiziert. Veröffentlichungsstatus wird nach Entschlüsselung geprüft.

Newsletter-Abonnements verwenden Double Opt-in. Shop, E-Mail, Bestätigungs-, Abmelde- und Statuswerte besitzen getrennte, teils shopgebundene Blindindexnamespaces. Dadurch kann die Anwendung Token finden, ohne sie als öffentliche Property zu speichern.

Kampagnen sind eigene Nodes. Versand läuft über konfiguriertes SMTP mit STARTTLS oder SSL und ohne Trackingpixel.

## 6. Forum und Knowledge Base

### Geltungsbereich

Themen und Knowledge-Artikel können global oder shopbezogen sein. Die technische Property `scope` unterscheidet `global` und `shop`; bei Shopobjekten existiert zusätzlich `shop_idx`.

Die globale Übersichtsroute soll beide Arten vereinigen, soweit der Benutzer Zugriff besitzt:

- globale Inhalte,
- Inhalte aktiver Shops,
- private/mitgliederbezogene Inhalte nur entsprechend der fachlichen Regeln,
- eigene Inhalte für Autor bzw. Shopbesitzer.

Ein direkter Shop-Link filtert dagegen auf den Shopkontext.

### Getrennte Threads

Forumsthema und Antworten sind getrennte Nodes. Antworten referenzieren das Thema über `topic_idx`. Das ermöglicht unabhängige Medien, Autorzuordnung und Datenschutzbehandlung.

Knowledge-Artikel besitzen Autor-, optional Shop-, Status- und Inhaltsdaten. Entwürfe sind nicht allein durch Kenntnis der ID öffentlich.

## 7. Creator und Mitgliedschaften

Ein Creator-Profil gehört über `user_idx` zu genau einem Benutzer. Creator-Posts tragen `creator_idx`, Status und Sichtbarkeit.

Eine Mitgliedschaft bildet das Paar `shop_id:user_id` in einem eigenen Namespace ab. Zusätzliche Indizes für Shop und Benutzer erlauben Listen aus beiden Richtungen. Mitgliederzugriff wird aus dem entschlüsselten Membershipobjekt und dem aktuellen Benutzer abgeleitet.

## 8. Downloads und Dokumente

Downloads speichern Dateiinhalte Base64-kodiert innerhalb des verschlüsselten Fachobjekts. Es wird kein vom Benutzer gelieferter beliebiger Dateipfad später vom Server geöffnet. Antworten erzwingen Attachment, `application/octet-stream`, `nosniff` und private Cache-Regeln.

Dokumente sind textuelle Shopobjekte mit `public`, `members` oder `private` sowie Entwurf/veröffentlicht. Ihre CMS-Darstellung ist nicht automatisch die native `DocumentCell` der MyceliaDB-Resonanzengine. Eine spätere Integration muss Sichtbarkeit und Entschlüsselungsgrenze explizit beachten.

## 9. Tickets

Ticket und Nachricht sind getrennt. Das Ticket besitzt `shop_idx` und `customer_idx`; Nachrichten besitzen `ticket_idx` und `author_idx`. Für schnellere Datenschutz-/Konversationsauswahl werden relevante Shop-/Kundenindizes zusätzlich an Nachrichten geführt.

Leseberechtigt sind Ticketkunde und Besitzer des betroffenen Shops. Screenshots/Bilder sind getrennte `media:image:`-Nodes und werden über das Elternobjekt autorisiert.

## 10. Community

Community-Posts sind global lesbare Fachobjekte; Schreiben verlangt Anmeldung. Kommentare referenzieren den Post über `post_idx`. Ownershipindizes unterstützen Export, Löschung und Autoransichten.

Bei Kontolöschung muss unterschieden werden:

- eigener, isoliert löschbarer Inhalt,
- Elternbeitrag mit Antworten anderer Personen,
- eigener Kommentar unter fremdem Beitrag.

Die Repositorylogik kann deshalb anonymisieren oder gezielt löschen, statt blind ganze Threads zu entfernen.

## 11. Gemeinsamer sicherer Media-Layer

`SecureMediaRepository` unterstützt Elternarten für CMS, Shopbranding, Blog, Creator, Forum, Knowledge, Community, Tickets und Dokumente.

### Upload

1. Datei mit Pillow vollständig dekodieren.
2. Typ-, Byte-, Pixel- und Dimensionsgrenzen prüfen.
3. EXIF-Orientierung anwenden.
4. Metadaten entfernen.
5. in ein kanonisches JPEG neu kodieren.
6. SHA-256 berechnen.
7. Bytes Base64-kodiert in das Media-Fachobjekt aufnehmen.
8. vollständiges Objekt als MCMS3 speichern.

Properties enthalten unter anderem Parenttyp, Slot sowie Blindindizes für Parent, Owner und optional Shop.

### Ausgabe

`/media/content/<id>.jpg` lädt und entschlüsselt das Mediaobjekt, findet anschließend das Elternobjekt und wendet dessen Sichtbarkeit an. Bei nicht vorhandenem oder nicht berechtigtem Zugriff wird 404 verwendet, um keine Existenzinformation preiszugeben.

Vor Ausgabe wird der SHA-256 der entschlüsselten Bildbytes erneut verglichen. Antwortheader verhindern MIME-Sniffing und öffentliche Zwischenspeicherung.

## 12. Richtext

Formatierbare Inhalte werden als `MYCELIA_RICHTEXT` Version 1 gespeichert. Der Browser darf nur definierte Block- und Marktypen serialisieren. Der Server normalisiert und validiert erneut. Dadurch wird keine frei ausführbare HTML-Zeichenkette zur Quelle der Darstellung.

Die verschlüsselte Speicherung ersetzt diese Prüfung nicht: Daten können von älteren Versionen stammen oder ein privilegierter Prozess könnte ungültige Inhalte geschrieben haben. Deshalb validieren Leser sicherheitsrelevante Strukturen erneut.

## 13. Löschmodelle

Es existieren drei unterschiedliche Vorgänge:

- **Soft Delete:** Objekt bleibt gespeichert, ein verschlüsseltes Feld markiert es als gelöscht.
- **Hard Delete:** `ERASE_NODE` entfernt den manuellen Node und seine Links nativ.
- **Anonymisierung:** Objekt bleibt wegen Beiträgen anderer Beteiligter bestehen, persönliche Zuordnung wird durch eine neutrale Identität ersetzt.

Welches Modell gilt, hängt von Fachlogik und Rechten Dritter ab. Backups benötigen eine getrennte Aufbewahrungs-/Bereinigungsstrategie.

## 14. Schemaentwicklung

Die JSON-Objekte besitzen derzeit im Allgemeinen keinen einheitlichen expliziten `schema_version`-Header. Python-Dataclasses erwarten passende Felder. Für zukünftige inkompatible Änderungen empfiehlt sich:

1. Version im Payload,
2. tolerante Leser für mindestens eine Vorgängerversion,
3. migrationsfähige Writer,
4. erst nach verifiziertem Snapshot Umschreiben,
5. keine Node-ID-Änderung ohne Entschlüsselung und Neuverschlüsselung.

Weil die Node-ID kryptografisch gebunden ist, ist ein Rename technisch eine Migration: altes Paket entschlüsseln, unter neuer ID neu verschlüsseln, Indizes schreiben, prüfen, alten Node löschen.

## 15. Beispiel eines vollständigen Datenflusses

Ein Benutzer erstellt ein shopbezogenes Forumsthema:

1. Session und CSRF werden geprüft.
2. Shop existiert; Berechtigung zum Erstellen wird geprüft.
3. Titel/Inhalt und optionale Bilder werden validiert.
4. Topic-ID und Node-ID werden erzeugt.
5. `author_idx` und `shop_idx` werden mit getrennten Namespaces gebildet.
6. vollständiges Topicobjekt wird mit der Topic-Node-ID als MCMS3 verschlüsselt.
7. Nodeproperties werden in MyceliaDB geschrieben.
8. Bilder werden normalisiert und als eigene verschlüsselte Media-Nodes geschrieben.
9. nativer Checkpoint und HMAC-Sidecar werden aktualisiert.
10. Beim globalen Forum werden globale und zugängliche Shopthemen aggregiert.
11. Beim Anzeigen eines Bildes wird die Sichtbarkeit des Themas erneut geprüft.

Dieses Beispiel zeigt das Projektprinzip: Speicherung, Suchbeziehung, Kryptografie und Autorisierung sind zusammenhängend, aber nicht dieselbe Kontrolle.

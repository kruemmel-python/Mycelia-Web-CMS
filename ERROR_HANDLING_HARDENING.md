# Mycelia WebCMS v0.8.0 – User Error Handling Hardening

Dieser Stand baut auf `Mycelia-WebCMS_v0_8_0(3)` auf.

## Ziel

Erwartbare Fehleingaben eines Benutzers dürfen nicht als ungefangener Flask-500 enden. Validierungsfehler werden verständlich und sichtbar an den Benutzer zurückgegeben; technische Integritäts-/DB-Fehler bleiben getrennt und werden weiterhin fail-closed behandelt.

## Umgesetzt

- Shop-Logo/Banner-Validierung liegt jetzt innerhalb der Route-Fehlergrenze und wird vor dem Speichern des Shop-Datensatzes ausgeführt.
- Zentrale Fallback-Behandlung für nicht lokal abgefangene `ValueError`, `PermissionError` und `MailerError`.
- Freundliche Behandlung von HTTP 400, 404, 405, 413 und 429.
- Eigene, nicht detail-leakende 500-Seite für echte interne Fehler; technische Details bleiben ausschließlich im lokalen Log.
- 413-Handling für Requests über dem globalen 2-MB-Limit.
- Bildfehlermeldungen nennen Ursache und konkrete Abhilfe.
- Clientseitige Vorprüfung für Upload-Größe, Anzahl und MIME-Typ.
- Bilder: maximal 280 KB pro Datei; JPEG/PNG/WebP; Anzahl je Feld entsprechend der jeweiligen Funktion.
- Downloads: maximal 700 KB.
- Fehlermeldungen werden mit `role="alert"` ausgegeben und rot hervorgehoben.
- Ungültige Dateifelder erhalten `aria-invalid="true"` und eine rote Feldmeldung direkt am Uploadfeld.

## Sicherheit

Die Browserprüfung ist reine UX. Der Server validiert Dateiinhalte, Größe, Dekodierbarkeit, Bildformat, Pixelzahl und Mediengrenzen weiterhin autoritativ. Host-Header-Fehler werden nicht über einen Referer-Redirect beantwortet. Datenbank-, Krypto- und Backup-Integritätsfehler bleiben separate 503-Fail-Closed-Fehler.

## Regressionstest

`tests/test_user_error_handling.py` prüft die neuen Fehlergrenzen und Upload-Guards.

Gesamtteststand nach Änderung: **45 passed**.

## Feldvalidierung / UX-Härtung

Zusätzlich zur serverseitigen Validierung besitzt Mycelia nun eine globale clientseitige Formularprüfung. Erwartbare Fehleingaben werden unmittelbar am jeweiligen Feld in Rot angezeigt und blockieren das Absenden, bis die Eingabe korrigiert wurde.

Abgedeckt sind insbesondere Pflichtfelder, Mindest-/Maximallängen, Slugs, Benutzername, E-Mail, HTTPS-Websites, Währungscodes, Ganzzahlen, Preis- und Bestandsgrenzen, Bestellmengen, Lieferadressen, Passwortwiederholung, DELETE/RESTORE/PURGE-Bestätigungen, Uploadgröße/-anzahl/-MIME und RichText-Pflicht-/Längenlimits. Serverseitige Validierung bleibt unverändert autoritativ und kann nicht durch JavaScript ersetzt oder umgangen werden.


## Startup-Regression: MailerError global handler

Behoben wurde ein Startabbruch durch `NameError: MailerError is not defined` in `cms/app.py`.
Der globale Flask-Errorhandler importiert `MailerError` nun explizit aus `cms.modules.webshop.mailer`.
Ein Regressionstest stellt sicher, dass der Handler nicht erneut ohne den erforderlichen Import eingecheckt wird.

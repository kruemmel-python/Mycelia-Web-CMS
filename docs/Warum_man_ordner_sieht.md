Was du im Browser bei einem Bild unter F12 siehst, ist kein Ordnerpfad auf der Festplatte, sondern eine virtuelle HTTP-Adresse:

```html
<img src="/media/content/935147b....jpg">
```

Der Browser interpretiert das ausschließlich als:

```text
Sende GET /media/content/935147b....jpg an 127.0.0.1:8088
```

## Was anschließend passiert

Flask ordnet diese URL dynamisch einer Python-Funktion zu:

```python
@bp.get("/media/content/<image_id>.jpg")
def content_image(image_id):
```

Siehe [media_routes.py](F:\Mycelia-WebCMS_v0_8_0\cms\media_routes.py:121).

Der Ablauf ist:

```text
Browser
  │
  │ GET /media/content/<Bild-ID>.jpg
  ▼
Flask-Medienroute
  │
  ├─ verschlüsselten media:image:-Node aus MyceliaDB laden
  ├─ Payload authentifizieren und entschlüsseln
  ├─ Zugriffsrecht am Elternobjekt prüfen
  ├─ Base64-Bilddaten dekodieren
  ├─ SHA-256 des Bildes kontrollieren
  └─ Bytes mit Content-Type image/jpeg zurückgeben
```

Es gibt also keinen Ordner:

```text
F:\Mycelia-WebCMS_v0_8_0\media\content\
```

und auch keine Datei:

```text
935147b....jpg
```

Das Bild liegt als verschlüsselter Datensatz in MyceliaDB. Die Endung `.jpg` ist lediglich Bestandteil des URL-Schemas und hilft Browser, Entwickler und Routing dabei, die Ressource als Bild zu erkennen.

## Warum der Browser trotzdem einen Pfad anzeigt

HTTP arbeitet grundsätzlich mit URL-Pfaden. Diese müssen nicht mit Verzeichnissen übereinstimmen.

Dasselbe gilt beispielsweise für:

```text
/s/mycelis-cms
/forum/new
/account/privacy
/media/content/<id>.jpg
```

Keiner dieser Pfade muss als Windows-Ordner existieren. Die Anwendung entscheidet, welche Funktion eine URL verarbeitet.

Im Template wird die URL automatisch erzeugt:

```jinja2
{{ url_for('media.content_image', image_id=shop_banner.id) }}
```

Siehe [public_shop.html](F:\Mycelia-WebCMS_v0_8_0\templates\webshop\public_shop.html:1).

## Warum diese Lösung sicherer ist

Ein klassischer Uploadordner würde ungefähr so funktionieren:

```text
static/uploads/banner.jpg
```

Dann könnte der Webserver die Datei direkt aus dem Dateisystem ausliefern. Die Anwendung hätte bei jedem Abruf möglicherweise keine Gelegenheit mehr, Berechtigungen zu kontrollieren.

Mycelia verwendet stattdessen eine kontrollierte Medienroute. Bei jedem Abruf wird geprüft:

- Existiert der verschlüsselte Datensatz?
- Ist seine Integrität gültig?
- Zu welchem Shop, Thema, Ticket oder Dokument gehört er?
- Ist das Elternobjekt sichtbar?
- Ist der Benutzer Besitzer, Mitglied oder berechtigter Ticketteilnehmer?

Bei fehlender Berechtigung liefert die Route `404`, auch wenn die Bild-ID existiert. Dadurch wird nicht einmal die Existenz eines privaten Bildes bestätigt.

Die Antwort wird außerdem mit diesen Regeln ausgeliefert:

```text
Content-Type: image/jpeg
Cache-Control: private, no-store, max-age=0
X-Content-Type-Options: nosniff
```

Kurz gesagt:

> `/media/content/...jpg` ist eine virtuelle, zugriffsgeschützte Abrufadresse – kein echter Bildordner und kein offengelegter Dateisystempfad.
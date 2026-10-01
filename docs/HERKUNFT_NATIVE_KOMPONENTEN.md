# Herkunft der nativen Komponenten und Architekturentwicklung

Stand: 1. Oktober 2026

## 1. Warum enthält ein WebCMS eine native DLL?

Die native Bibliothek in Mycelia WebCMS entstand nicht ursprünglich, weil ein Content-Management-System zwingend eine GPU-DLL benötigt. Sie steht in einer längeren Entwicklungslinie aus OpenCL-, Simulations-, Mycelium- und Datenbankprojekten.

Der öffentlich dokumentierte Ursprung ist das eigenständige Projekt [CC_OpenCl_Enterprise](https://github.com/kruemmel-python/CC_OpenCl_Enterprise). Dessen Repository beschreibt einen separat kompilierbaren OpenCL-Treiber, der als wiederverwendbare DLL für weitere Projekte vorbereitet wurde. Die Bibliothek kapselt OpenCL-Kontexte, Programme, Kernel, Buffer und GPU-Ausführung hinter nativen Schnittstellen.

Die kurze Antwort lautet deshalb:

> Die DLL wurde nicht gebaut, weil ein CMS eine DLL benötigt. Das WebCMS wurde später auf Komponenten einer bereits vorhandenen GPU- und Compute-Architektur aufgebaut.

Das erklärt, warum sich im heutigen Projekt Begriffe und Strukturen finden, die weit über klassische CMS-Aufgaben hinausgehen.

## 2. CC_OpenCl_Enterprise als allgemeine Compute-Schicht

CC_OpenCl_Enterprise ist laut eigener Projektdokumentation eine wiederverwendbare GPU-Schicht für mehrere Algorithmusklassen. Dazu gehören:

- Tensor- und Feldoperationen,
- Simulationsalgorithmen,
- Agentensysteme,
- Mycelium-Modelle,
- SubQG- und quantum-inspired Experimente,
- resonante Felder,
- energieabhängige Scheduler,
- morphogenetische Regelwerke.

Der Treiber enthält eingebettete OpenCL-Kernel. Obwohl zentrale Quelldateien die Endung `.c` tragen, werden sie wegen C++-Raw-String-Literalen als C++17 übersetzt. Das eigenständige Repository dokumentiert hierfür sowohl einen direkten MSVC-Build als auch CMake-Unterstützung.

### 2.1 Modularer Enterprise Algorithm Pack

Die aktuelle öffentliche Dokumentation des Treiberprojekts beschreibt eine vom historischen Monolith-Kernel getrennte Algorithmusschicht. Sie wird beim ersten Aufruf kompiliert und exportiert unter anderem:

- `execute_resonant_field_step_gpu`: gekoppelte Oszillator- und Resonanzfelder,
- `execute_energy_gated_scheduler_gpu`: GPU-seitiges Aktivitäts-Gating und Kompaktierung aktiver Agenten,
- `execute_morphogenetic_rule_step_gpu`: tabellarische morphogenetische Regeln über GPU-Felder.

Eigene `cl_program`- und `cl_kernel`-Handles isolieren Buildfehler, Lebenszyklus und Cleanup dieser neueren Algorithmen vom historischen Kern.

Diese Funktionen zeigen den ursprünglichen Zweck der Bibliothek: Sie ist eine allgemeine native Compute-Infrastruktur. Ein WebCMS verwendet nur einen spezialisierten Ausschnitt dieser Herkunft.

### 2.2 Mycelia Security SDK als Ursprung der Kryptografieschnittstelle

Die Sicherheitslinie stammt aus dem eigenständigen Projekt [Mycelia-Security-SDK](https://github.com/kruemmel-python/Mycelia-Security-SDK). Es kombinierte die OpenCL-/SubQG-Engine mit einer kleinen, sprachneutralen C-API sowie Python- und C#-Wrappern. Das öffentliche Repository dokumentiert außerdem Datei-Vault, verschlüsselten Chat und einen blinden Relay-Server als ursprüngliche Anwendungsfälle.

Die historische C-Schnittstelle bestand im Kern aus:

```text
myc_init
myc_get_device_count
myc_get_last_error
myc_create_context
myc_destroy_context
myc_set_seed
myc_process_buffer
```

Ein opaker `myc_context_t` band den Zustand an ein OpenCL-Gerät. `myc_set_seed` setzte einen 64-Bit-Seed; `myc_process_buffer` erzeugte ab einem absoluten `stream_offset` einen symmetrischen XOR-Stream. Der Offset ermöglichte blockweises Streaming und Random Access, ohne eine komplette Datei gleichzeitig im Arbeitsspeicher zu halten.

Die [SDK-Architekturdokumentation](https://github.com/kruemmel-python/Mycelia-Security-SDK/blob/main/architecture.md) bezeichnet dieses historische Verfahren als SubQG/Bio-CTR: Ein deterministischer Simulationszustand erzeugte im VRAM blockweise einen reproduzierbaren Schlüsselstrom. Die damaligen Vault- und Chat-Wrapper kombinierten ihn mit Seed-Maskierung, Kompression und Integritätsprüfungen.

### 2.3 Sicherheitskritische Einordnung des ursprünglichen SDK

Das öffentliche SDK bezeichnet sich selbst als experimentelle Kryptografie-Engine. Seine historische Dokumentation erklärt Herkunft und Funktionsweise, ersetzt aber keine unabhängige kryptografische Analyse. Für die offizielle WebCMS-Dokumentation gelten deshalb folgende Präzisierungen:

- Ein 64-Bit-Seed ist sicherheitsrelevantes Schlüsselmaterial. „Keyless“ bedeutet hier, dass ein langer Keystream bei Bedarf aus einem kompakten Seed rekonstruiert wird; nicht, dass keinerlei Geheimnis existiert.
- Der Besitz oder die Geheimhaltung einer DLL darf kein notwendiger Sicherheitsfaktor sein. Der WebCMS-Schutz muss auch dann auf kryptografischen Schlüsseln beruhen, wenn Quellcode und Binärlogik bekannt sind.
- XOR ist nur so sicher wie der erzeugte Stream, dessen Einmaligkeit und dessen Schlüsselraum.
- Zlib, CRC32 und Adler32 erkennen zufällige Übertragungsfehler, sind aber keine kryptografische Authentifizierung gegen aktive Manipulation.
- Deterministisches Chaos allein ist kein Ersatz für eine öffentlich analysierte Key-Derivation und einen Message Authentication Code.
- Hardwarebindung und Reproduzierbarkeit stehen in Spannung: Ein Persistenzformat muss auch nach Treiber-, Compiler- oder GPU-Wechsel zuverlässig lesbar bleiben.

Diese Punkte erklären die spätere Härtung, ohne die technische Herkunft zu leugnen.

### 2.4 Vom ursprünglichen SDK zum gehärteten WebCMS-Pfad

Die mit WebCMS v0.8.0 ausgelieferte Security-API erweitert die historische Schnittstelle:

```text
myc_set_key_256
myc_get_security_capabilities
```

Die Entwicklung lässt sich in drei Paketgenerationen gliedern:

| Generation | Grundlage | Rolle in v0.8.0 |
|---|---|---|
| MCMS1 | historischer 64-Bit-Seed und GPU-Stream | ausschließlich kompatibles Lesen |
| MCMS2 | 256-Bit-Record-Key, GPU-Blockstream plus HMAC-SHA256-Maske und Record-HMAC | kompatibles Lesen und Recovery |
| MCMS3 | 256-Bit-Record-Key und vollständig spezifizierter HMAC-SHA256-Counterstream auf der CPU | aktuelles Schreibformat |

MCMS2 beseitigte die alleinige Abhängigkeit vom 64-Bit-Seed, behielt aber für den Stream die historische GPU-Runtime. MCMS3 löst neue Datensätze von dieser Reproduzierbarkeitsgrenze. Die GPU bleibt für alte Pakete verfügbar, ist aber kein notwendiger Sicherheitsanker für neue CMS-Daten.

### 2.5 Woher die Sicherheit des heutigen WebCMS tatsächlich kommt

Die heutigen Schutzwirkungen entstehen aus einer Kombination überprüfbarer Mechanismen:

- zufälliger 256-Bit-CMS-Master-Key,
- zufälliges 128-Bit-Nonce pro Verschlüsselung,
- HMAC-SHA256-basierte, nach Zweck getrennte Record-Key-Ableitung,
- Bindung der Ableitung und des Authentifizierungstags an die vollständige Node-ID,
- separater Schlüssel für Verschlüsselungsstream und Authentifizierung,
- Prüfung des HMAC vor jeder Entschlüsselung,
- namespaced Blindindizes statt suchbarer Klartextwerte,
- HMAC-authentifizierte native Snapshots,
- Argon2id für Passwörter,
- restriktive ACLs, Loopback-DB, per Start erneuerter DB-Token und fachliche Autorisierung,
- fail-closed Capability- und Formatprüfungen,
- gepinnte historische Runtime nur als Lesbarkeitsvertrag für MCMS1/2.

Die Sicherheit kommt damit nicht aus einem einzelnen Baustein und nicht allein aus der GPU. Das ursprüngliche Mycelia Security SDK lieferte Engine, Streamingmodell und Integrations-API. WebCMS v0.8.0 ergänzt die heute maßgeblichen kryptografischen Schutzschichten und die betrieblichen Vertrauensgrenzen.

## 3. Frühe MyceliaDB-Linie

Das separate Repository [CMS-MyceliaDB-Enterprise](https://github.com/kruemmel-python/CMS-MyceliaDB-Enterprise) dokumentiert eine frühere SQL-freie Plattform aus PHP-Webfrontend und Python/OpenCL-Engine. Ihre Fachentitäten wurden als Mycelia-/DAD-Attraktoren gespeichert und über eigene Snapshots persistiert. Eine SQL-Datenbank wurde weder erzeugt noch benötigt.

Diese frühere Plattform ist nicht dieselbe Anwendung wie Mycelia WebCMS v0.8.0. Sie ist ein historisch und architektonisch verwandtes System, aus dem mehrere Grundideen stammen.

## 4. Direct GPU Ingest in der früheren Plattform

Ab der dort dokumentierten Version 1.7 versiegelte das Browserfrontend sensible Formularfelder, bevor PHP sie erhielt:

1. Der Browser fragte einen öffentlichen RSA-OAEP-Schlüssel der Engine ab.
2. Er erzeugte pro Submit einen temporären AES-256-GCM-Schlüssel.
3. Formularfelder wurden mit AES-256-GCM verschlüsselt.
4. Der AES-Schlüssel wurde mit RSA-OAEP-3072-SHA256 versiegelt.
5. PHP erhielt im Wesentlichen nur `direct_op` und `sealed_ingest`.
6. PHP leitete das Paket unverändert an die Python-Engine weiter.
7. Die Engine öffnete, normalisierte und speicherte den Inhalt als Mycelia-Attraktor.

Das damalige Sicherheitsziel war **PHP-blinder Direct Ingest**: Formularinhalte sollten weder in normalen PHP-POST-Strukturen noch in PHP-Fachlogik oder typischen PHP-Logs als Klartext auftreten.

### 4.1 Die ausdrücklich dokumentierte Grenze

Die frühere Projektdokumentation behauptete für diese erste Phase keine vollständige RAM-freie GPU-Residency. Der Envelope wurde zunächst in der Python-Engine mit einer CPU-Kryptografiebibliothek geöffnet. Klartext materialisierte sich daher kurzfristig im Python-CPU-Speicher, bevor er in nachgelagerte Mycelia-/GPU-Pfade gelangte.

Diese Einschränkung ist wichtig: Ein Name wie „Direct GPU Ingest“ allein beweist nicht, dass zu keinem Zeitpunkt CPU-Klartext existiert. Die damalige Dokumentation trennte deshalb zwischen:

- PHP-blindem Transport: erreicht,
- vollständigem nativen GPU-Envelope-Opening: in Phase 1 nicht erreicht,
- strikter Inflight-VRAM-Aussage: in Phase 1 ausdrücklich `false`.

## 5. Zero-Logic Gateway und Sessionbindung

Die spätere Version 1.9 des früheren Systems verschob weitere Entscheidungen aus PHP in die Engine:

- produktive Mutationen verlangten `sealed_ingest` und `direct_op`,
- Klartext-POSTs wurden abgelehnt,
- PHP hielt nur ein opaques Engine-Session-Handle und rotierende Request-Tokens,
- Tokens wurden in den WebCrypto-Envelope eingebunden und je Mutation rotiert,
- Rollen, Autor, Owner und Signaturen wurden Engine-seitig bestimmt.

„Zero Logic“ bedeutet in diesem Kontext nicht, dass PHP überhaupt keinen Code ausführt. Gemeint ist, dass die Webschicht keine vertrauenswürdigen fachlichen Sicherheitsentscheidungen über Klartextdaten treffen sollte.

## 6. Native-GPU-Residency-Contract

Die dort dokumentierte Version 1.10 ergänzte prüfbare Engine-Befehle:

```text
native_gpu_capability_report
native_gpu_residency_selftest
strict_vram_certification
```

Das Ziel war, GPU-Nutzung und Speicherresidenz nicht lediglich zu behaupten, sondern durch Capabilityberichte, Selbsttests und externe Memory-Probes nachzuweisen. Ohne erwartete native Bibliothek und Exporte blieb die Strict-VRAM-Zertifizierung fail-closed blockiert.

Spätere Versionen ergänzten konsistente Evidence-Bundles, klassifizierte Memory-Probes, Redaction und geplante Heartbeat-Audits. Diese Historie erklärt, warum Prüfbarkeit und fail-closed-Verhalten auch im heutigen Projekt zentrale Prinzipien sind.

## 7. Warum eine GPU in einer Datenplattform sinnvoll sein kann

Für gewöhnliche CMS-CRUD-Operationen wäre eine zwingende GPU-Persistenz unnötig kompliziert. In anderen Workloads kann eine gekoppelte Compute- und Datenarchitektur sinnvoll sein:

- große parallele Zustandsräume,
- Agenten- und biologische Simulationen,
- neuronale oder physikalische Felder,
- Vektor- und Matrixtransformationen,
- energie- oder schwellenwertbasierte Scheduler,
- Systeme, deren aktiver Zustand ohnehin dauerhaft im VRAM liegt.

Wenn Daten bereits GPU-resident verarbeitet werden, können vermiedene CPU/GPU-Transfers einen echten Vorteil darstellen. Aus diesem Forschungs- und Simulationsumfeld stammt die frühe Mycelia-Architektur.

## 8. Warum WebCMS v0.8.0 diese Architektur nicht vollständig übernimmt

Das heutige WebCMS hat andere Prioritäten:

- reproduzierbare und langfristig lesbare Persistenz,
- deterministische Wiederherstellung,
- kontrollierte Backup- und Recovery-Pfade,
- stabile Deploymentbedingungen,
- klare Fehlerzustände,
- geringe Hardwareabhängigkeit für normale Seitenzugriffe,
- nachvollziehbare Datenschutz- und Autorisierungslogik.

Deshalb wurden Architekturprinzipien übernommen, nicht jede historische Implementierungsentscheidung.

### 8.1 Was im heutigen v0.8.0 tatsächlich gilt

- Das Webfrontend ist Flask/Waitress, nicht das frühere PHP-Gateway.
- Normale Formulare werden serverseitig verarbeitet; es gibt im aktuellen Projekt kein `sealed_ingest`-/`direct_op`-Browserprotokoll.
- Neue verschlüsselte Datensätze verwenden MCMS3 mit einem CPU-seitigen, reproduzierbaren HMAC-SHA256-Counterstream.
- Die GPU-abhängigen MCMS1-/MCMS2-Pfade bleiben zum Lesen historischer Daten erhalten.
- MyceliaDB ist weiterhin die einzige Persistenzschicht; SQL oder SQLite werden nicht ergänzt.
- CMS-Fachobjekte werden als manuelle MyceliaDB-Nodes mit verschlüsseltem Payload gespeichert.
- Die native DB bietet zusätzlich Dokumentingestion und Resonanzgraphen; aktuelle CMS-CRUD-Abfragen laufen jedoch nicht automatisch darüber.
- Die heutige DB-GPU-Bridge ist optional. Die aktuelle Resonanzdiffusion ist CPU-seitiger C++-Code.
- Das aktuelle Projekt exportiert keine Befehle `native_gpu_capability_report`, `native_gpu_residency_selftest` oder `strict_vram_certification`.

### 8.2 Was nicht behauptet werden darf

Für WebCMS v0.8.0 wäre derzeit unzutreffend:

- alle CMS-Daten blieben ausschließlich im VRAM,
- Browserformulare würden direkt GPU-versiegelt an die Engine geleitet,
- Flask sähe bei Mutationen grundsätzlich keinen Klartext,
- normale Datenbankabfragen würden auf der GPU ausgeführt,
- die frühere Strict-VRAM-Zertifizierung sei Bestandteil dieser Version.

Diese Aussagen gehören zur früheren Plattform oder zu weitergehenden Forschungszielen, nicht zum aktuellen Implementierungsnachweis.

## 9. Übernommene Architekturprinzipien

Trotz der technischen Spezialisierung besteht deutliche Kontinuität:

### Eigene SQL-freie Persistenz

MyceliaDB bleibt eine eigenständige Persistenzschicht. Das CMS führt keine zweite SQL-/SQLite-Wahrheit ein.

### Explizite Vertrauensgrenzen

Browser, Webanwendung, Security-Komponente, DB-Protokoll und Snapshot sind getrennte Sicherheitszonen.

### Native Komponenten für klar begrenzte Aufgaben

Native Komponenten werden dort eingesetzt, wo Kompatibilität, Enginezustand oder hardwarenahe Verarbeitung dies rechtfertigen.

### Fail-closed

Fehlen Schlüssel, Capabilities, Snapshot-HMAC oder die erwartete DB-Authentifizierung, startet beziehungsweise lädt das System nicht in einem stillschweigend schwächeren Modus.

### Prüfbarkeit statt pauschaler Sicherheitsbehauptung

Hashes, Capabilitystrings, HMAC-Prüfungen, Tests und Recovery-Probes liefern konkrete Evidenz. Prozentuale oder absolute Sicherheitsversprechen werden vermieden.

### Datenminimierung

Höhere Schichten und persistente Properties sollen nur die Informationen erhalten, die für ihre Aufgabe erforderlich sind.

## 10. Entwicklungslinie

```text
CC_OpenCl_Enterprise
        │
        │ allgemeine OpenCL-/GPU-Compute-Schicht
        ▼
frühe MyceliaDB- und DAD-Attraktorarchitektur
        │
        │ SQL-freie Daten- und Compute-Plattform
        ▼
Direct GPU Ingest
        │
        │ Browser-Sealing und PHP-blinder Transport
        ▼
Zero-Logic Gateway / Native GPU Residency
        │
        │ Engine-Autorität und prüfbare VRAM-Evidence
        ▼
Mycelia WebCMS v0.8.0
        │
        └─ spezialisierter CMS-Betrieb
           manuelle MyceliaDB-Nodes
           MCMS3 für reproduzierbare neue Verschlüsselung
           MCMS1/2-Kompatibilität
           authentifizierte native Snapshots
```

Diese Darstellung ist eine Architektur- und Entwicklungslinie, keine Behauptung, dass jede Funktion aller Vorgängerprojekte unverändert im aktuellen WebCMS enthalten ist.

## 11. Warum diese Historie Teil der offiziellen Dokumentation ist

Ohne Herkunftskontext wirkt eine OpenCL-DLL in einem WebCMS wie eine unnötige Sonderlösung. Mit dem Kontext wird sichtbar:

- Das WebCMS ist ein später Anwendungsfall einer breiteren Compute-Infrastruktur.
- Die GPU-Architektur war für Forschungs-, Simulations- und VRAM-residente Systeme gedacht.
- Das heutige CMS hat den Stack für einen anderen Workload spezialisiert.
- Die Reduzierung zwingender GPU-Pfade ist kein Sicherheitsrückschritt, sondern verbessert Reproduzierbarkeit und Recovery für Webpersistenz.
- Historische GPU-Kompatibilität bleibt dort erhalten, wo bestehende Ciphertexte davon abhängen.

Die entscheidende Frage lautet daher nicht nur „Warum verwendet ein CMS eine DLL?“, sondern „Welche Teile einer tieferen Compute-Architektur sind für einen verlässlichen CMS-Betrieb heute noch sinnvoll?“

## 12. Quellen und Projektbezug

- [CC_OpenCl_Enterprise – eigenständiger OpenCL-Treiber und Enterprise Algorithm Pack](https://github.com/kruemmel-python/CC_OpenCl_Enterprise)
- [Mycelia-Security-SDK – historisches GPU-Kryptografie-SDK, C-API, Vault und Chat](https://github.com/kruemmel-python/Mycelia-Security-SDK)
- [Mycelia Security SDK – historische Architektur](https://github.com/kruemmel-python/Mycelia-Security-SDK/blob/main/architecture.md)
- [Mycelia Security SDK – historische API-Referenz](https://github.com/kruemmel-python/Mycelia-Security-SDK/blob/main/API%20Reference.md)
- [CMS-MyceliaDB-Enterprise – frühere SQL-freie PHP/Python/OpenCL-Plattform](https://github.com/kruemmel-python/CMS-MyceliaDB-Enterprise)
- Aktueller WebCMS-Code: `cms/security.py`, `cms/db.py`, `cms/backup.py`
- Aktuelle native DB: `third_party/MyceliaDB_Enterprise_Studio_v0_2_secure/`
- Aktueller Security Core: `third_party/Mycelia-Security-SDK_v2_secure/`

Externe Repositories entwickeln sich unabhängig weiter. Für Aussagen über den aktuellen WebCMS-Ist-Stand bleiben die im jeweiligen Entwicklerpaket enthaltenen Quellen maßgeblich.

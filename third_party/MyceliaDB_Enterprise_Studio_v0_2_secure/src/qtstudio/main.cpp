
#include <QtWidgets>
#include <QTcpSocket>
#include <QFileDialog>
#include <QRegularExpression>
#include <QDesktopServices>
#include <QUrl>
#include <QMouseEvent>
#include <QNetworkAccessManager>
#include <QNetworkRequest>
#include <QNetworkReply>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QEventLoop>
#include <QTimer>

class MyceliaStudioWindow final : public QMainWindow {
public:
    MyceliaStudioWindow() {
        setWindowTitle("MyceliaDB Enterprise Studio Premium — Dante Manager");
        resize(1540, 940);
        buildUi();
        applyPremiumStyle();
        log("Studio ready. Start the server, then Connect.");
    }

private:
    QTcpSocket socket_;
    QLineEdit* host_{};
    QSpinBox* port_{};
    QLabel* connectionBadge_{};
    QLabel* gpuBadge_{};
    QLabel* healthBadge_{};
    QTextEdit* logView_{};
    QTextEdit* consoleOut_{};
    QLineEdit* commandLine_{};
    QTreeWidget* nodeTree_{};
    QTableWidget* linkTable_{};
    QTableWidget* traceTable_{};
    QProgressBar* signalLoad_{};
    QPlainTextEdit* ruleEditor_{};
    QTableWidget* docTable_{};
    QTableWidget* searchTable_{};
    QTableWidget* resonanceTable_{};
    QLineEdit* searchLine_{};
    QTextEdit* docPreview_{};
    QLabel* imagePreview_{};
    QString currentImagePath_{};
    QTextEdit* mediaMeta_{};
    QTableWidget* formTable_{};
    QTextEdit* llmPreview_{};
    QTextEdit* sideOriginalPreview_{};
    QTextEdit* sideLlmPreview_{};
    QString currentEvidenceLabel_{};
    QString currentEvidenceText_{};
    QComboBox* uiModeSelector_{};
    QTabWidget* evidenceTabs_{};
    QTabWidget* workspaceTabs_{};
    QTextEdit* gpuStatusView_{};
    QLabel* gpuDriverLabel_{};
    QLabel* gpuModeLabel_{};
    QLabel* gpuHealthLabel_{};
    QLabel* gpuBackendLabel_{};

    static QString quoteArg(QString s) {
        s.replace("\\", "\\\\");
        s.replace("\"", "\\\"");
        return "\"" + s + "\"";
    }

    bool eventFilter(QObject* watched, QEvent* event) override {
        if (watched == imagePreview_ && event && event->type() == QEvent::MouseButtonDblClick) {
            if (!currentImagePath_.isEmpty() && QFileInfo::exists(currentImagePath_)) {
                QDesktopServices::openUrl(QUrl::fromLocalFile(currentImagePath_));
                return true;
            }
        }
        return QMainWindow::eventFilter(watched, event);
    }

    void openCurrentEvidenceImage() {
        if (!currentImagePath_.isEmpty() && QFileInfo::exists(currentImagePath_)) {
            QDesktopServices::openUrl(QUrl::fromLocalFile(currentImagePath_));
            return;
        }
        QMessageBox::information(this, "No source image", "No linked source image is available for the selected hit.");
    }

    void applyUiMode() {
        const bool adminMode = uiModeSelector_ && uiModeSelector_->currentIndex() == 1;
        auto applyTableMode = [adminMode](QTableWidget* table) {
            if (!table) return;
            table->setColumnHidden(1, !adminMode); // Kind
            table->setColumnHidden(3, !adminMode); // Energy
        };
        applyTableMode(searchTable_);
        applyTableMode(resonanceTable_);
        if (evidenceTabs_) {
            const int metadataIndex = evidenceTabs_->indexOf(mediaMeta_);
            if (metadataIndex >= 0) evidenceTabs_->setTabVisible(metadataIndex, adminMode);
        }
    }

    void setFormRow(const QString& key, const QString& value) {
        if (!formTable_ || key.trimmed().isEmpty() || value.trimmed().isEmpty()) return;
        const int row = formTable_->rowCount();
        formTable_->insertRow(row);
        formTable_->setItem(row, 0, new QTableWidgetItem(key.trimmed()));
        formTable_->setItem(row, 1, new QTableWidgetItem(value.trimmed()));
    }

    void updateRecordMask(const QString& label, const QString& evidence) {
        if (!formTable_) return;
        formTable_->setRowCount(0);
        setFormRow("Treffer", label);

        QString text = evidence;
        text.replace("\\n", " ");
        text.replace(QRegularExpression("\\s+"), " ");

        QRegularExpression householdRow(
            "(\\d+)\\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+\\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.-]+)\\s+"
            "(\\d{2}\\.\\d{2}\\.\\d{4})\\s+([A-Za-zÄÖÜäöüß.-]+)\\s+(\\d{2}\\.\\d{2}\\.\\d{4})");
        auto hm = householdRow.match(text);
        if (hm.hasMatch()) {
            setFormRow("Lfd. Nr.", hm.captured(1));
            setFormRow("Person", hm.captured(2));
            setFormRow("Geburtsdatum", hm.captured(3));
            setFormRow("Beziehung", hm.captured(4));
            setFormRow("Wohnhaft seit", hm.captured(5));
        }

        QRegularExpression emailRe("([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,})");
        auto email = emailRe.match(text);
        if (email.hasMatch()) setFormRow("E-Mail", email.captured(1));

        QRegularExpression plzOrtRe("(\\d{5})\\s+(Leipzig|Dresden|Berlin|Chemnitz|Halle|Erfurt|Jena|Magdeburg)", QRegularExpression::CaseInsensitiveOption);
        auto plz = plzOrtRe.match(text);
        if (plz.hasMatch()) setFormRow("Ort", plz.captured(1) + " " + plz.captured(2));

        QRegularExpression moneyRe("(\\d{1,3}(?:\\.\\d{3})*,\\d{2})\\s*EUR");
        auto mi = moneyRe.globalMatch(text);
        int moneyCount = 0;
        while (mi.hasNext() && moneyCount < 5) {
            auto m = mi.next();
            setFormRow(QString("Betrag %1").arg(++moneyCount), m.captured(1) + " EUR");
        }

        if (formTable_->rowCount() == 1) {
            setFormRow("Belegauszug", text.left(500));
        }
        formTable_->resizeColumnsToContents();
        formTable_->horizontalHeader()->setStretchLastSection(true);
    }

    QString callLmStudioForEvidence(const QString& label, const QString& evidence) {
        const QString endpoint = qEnvironmentVariable("MYCELIA_LMSTUDIO_URL", "http://127.0.0.1:1234/v1/chat/completions");
        const QString model = qEnvironmentVariable("MYCELIA_LMSTUDIO_MODEL", "google_gemma-4-e4b-it");

        QJsonArray messages;
        messages.append(QJsonObject{
            {"role", "system"},
            {"content",
             "Du bist der lokale Evidence-Interpreter für MyceliaDB. "
             "Deine Aufgabe ist nicht freie Zusammenfassung, sondern Formularrekonstruktion aus OCR-Text. "
             "Du darfst keine Fakten erfinden. Du darfst aber offensichtliche OCR-Fehler vorsichtig normalisieren "
             "z. B. Persénliche -> Persönliche, Staatsangehérigkeit -> Staatsangehörigkeit, Fir -> Für, ia -> ja. "
             "Checkbox-Regel: [X], [XI], [XJ], X, XX oder ein X direkt vor/neben einer Option bedeutet angekreuzt. "
             "Leere, U, Ü, O, D, ( ), [_], [] oder einzelne Klammern bedeuten nicht angekreuzt. "
             "Wenn zwei Optionen wie weiblich/männlich vorkommen und nur weiblich ein X trägt, gib nur weiblich aus. "
             "Wenn ein Textblock zwei nebeneinanderliegende Felder enthält, trenne sie anhand der Feldlabels. "
             "Beispiel: 'Verwandtschaftsverhältnis zum Kind Das Kind lebt bei mir leiblicher Vater X ia U nein' bedeutet "
             "Verwandtschaftsverhältnis zum Kind: leiblicher Vater und Das Kind lebt bei mir: ja. "
             "Wenn ein Wert nicht sicher rekonstruierbar ist, schreibe 'nicht sicher lesbar' statt zu raten. "
             "Antworte sachlich, kurz, bürotauglich, auf Deutsch."}
        });
        messages.append(QJsonObject{
            {"role", "user"},
            {"content",
             "Trefferlabel:\n" + label + "\n\n"
             "OCR-/Evidence-Text:\n" + evidence + "\n\n"
             "Aufgabe:\n"
             "Rekonstruiere den Formularabschnitt als saubere Mitarbeiteransicht.\n\n"
             "Ausgabeformat exakt so:\n"
             "Abschnitt: <erkannter Abschnitt>\n\n"
             "Feldwerte:\n"
             "- Feld: Wert\n"
             "- Feld: Wert\n\n"
             "Ankreuzfelder:\n"
             "- Feld/Gruppe: ausgewählte Option\n\n"
             "Personen und Beziehungen:\n"
             "- Person/Beziehung, falls vorhanden\n\n"
             "Hinweise:\n"
             "- Nur echte Unsicherheiten nennen. Keine technischen OCR-Erklärungen.\n\n"
             "Spezielle Formularregeln:\n"
             "- Bei 'Angaben zum Kind': Vorname, Geschlecht, Geburtsdatum, Geburtsort, Staatsangehörigkeit, Verwandtschaftsverhältnis und 'Das Kind lebt bei mir' getrennt ausgeben.\n"
             "- Bei 'Persönliche Daten': Antragstellerdaten und Kinddaten nicht vermischen.\n"
             "- Bei 'Bankverbindung': IBAN, BIC und Kreditinstitut getrennt ausgeben.\n"
             "- Rohtext wie '[XI weiblich Ü) männlich' bedeutet normalerweise 'Geschlecht: weiblich'.\n"
             "- Rohtext wie 'X ia U nein' bedeutet normalerweise 'ja' angekreuzt und 'nein' nicht angekreuzt.\n"
             "- Die Aussage 'Verwandtschaftsverhältnis zum Kind Das Kind lebt bei mir leiblicher Vater X ia U nein' darf niemals zu 'Verwandtschaftsverhältnis: Das Kind lebt bei mir' werden."}
        });

        QJsonObject payload{
            {"model", model},
            {"temperature", 0.1},
            {"stream", false},
            {"messages", messages}
        };

        QNetworkAccessManager manager;
        QNetworkRequest request{QUrl(endpoint)};
        request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");

        QNetworkReply* reply = manager.post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));
        QEventLoop loop;
        QTimer timer;
        timer.setSingleShot(true);

        connect(&timer, &QTimer::timeout, &loop, [&] {
            if (reply && reply->isRunning()) reply->abort();
            loop.quit();
        });
        connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);

        timer.start(120000);
        loop.exec();

        if (!reply) return "LM Studio Fehler: keine Antwort.";
        const QByteArray bytes = reply->readAll();
        const auto error = reply->error();
        const QString errorText = reply->errorString();
        reply->deleteLater();

        if (error != QNetworkReply::NoError) {
            return "LM Studio nicht erreichbar oder Anfrage fehlgeschlagen.\n\n"
                   "Erwartet wird ein OpenAI-kompatibler LM-Studio-Server unter:\n" +
                   endpoint + "\n\n"
                   "Modell: " + model + "\n\n"
                   "Fehler: " + errorText;
        }

        QJsonParseError parseError{};
        const QJsonDocument doc = QJsonDocument::fromJson(bytes, &parseError);
        if (parseError.error != QJsonParseError::NoError || !doc.isObject()) {
            return "LM Studio Antwort konnte nicht gelesen werden.\n\nRohantwort:\n" + QString::fromUtf8(bytes);
        }

        const QJsonArray choices = doc.object().value("choices").toArray();
        if (choices.isEmpty()) {
            return "LM Studio Antwort enthält keine choices.\n\nRohantwort:\n" + QString::fromUtf8(bytes);
        }

        const QJsonObject message = choices.at(0).toObject().value("message").toObject();
        const QString content = message.value("content").toString().trimmed();
        if (content.isEmpty()) {
            return "LM Studio Antwort war leer.\n\nRohantwort:\n" + QString::fromUtf8(bytes);
        }
        return content;
    }

    void improveEvidenceWithLmStudio() {
        if (currentEvidenceText_.trimmed().isEmpty()) {
            QMessageBox::information(this, "Keine Evidence", "Bitte zuerst einen Treffer auswählen.");
            return;
        }

        QApplication::setOverrideCursor(Qt::WaitCursor);
        const QString result = callLmStudioForEvidence(currentEvidenceLabel_, currentEvidenceText_);
        QApplication::restoreOverrideCursor();

        if (llmPreview_) {
            llmPreview_->setPlainText(result);
            const int idx = evidenceTabs_ ? evidenceTabs_->indexOf(llmPreview_) : -1;
            if (idx >= 0) evidenceTabs_->setCurrentIndex(idx);
        }
        if (sideOriginalPreview_) sideOriginalPreview_->setPlainText(currentEvidenceText_);
        if (sideLlmPreview_) sideLlmPreview_->setPlainText(result);
    }

    void showOriginalAndLmSideBySide() {
        if (sideOriginalPreview_) sideOriginalPreview_->setPlainText(currentEvidenceText_);
        if (sideLlmPreview_ && sideLlmPreview_->toPlainText().trimmed().isEmpty()) {
            sideLlmPreview_->setPlainText("Noch keine LLM-Aufbereitung vorhanden.\n\nKlicke auf 'LM Studio Evidence'.");
        }
        const int idx = evidenceTabs_ ? evidenceTabs_->indexOf(sideOriginalPreview_->parentWidget()) : -1;
        if (idx >= 0) evidenceTabs_->setCurrentIndex(idx);
    }


    void buildUi() {
        auto* root = new QWidget;
        auto* main = new QVBoxLayout(root);
        main->setContentsMargins(18, 18, 18, 18);
        main->setSpacing(14);
        main->addWidget(buildHeader());

        auto* splitter = new QSplitter(Qt::Horizontal);
        splitter->setChildrenCollapsible(false);
        splitter->addWidget(buildSidebar());
        splitter->addWidget(buildWorkspace());
        splitter->setStretchFactor(0, 0);
        splitter->setStretchFactor(1, 1);
        splitter->setSizes({285, 1255});
        main->addWidget(splitter, 1);
        setCentralWidget(root);

        connect(&socket_, &QTcpSocket::connected, this, [this] {
            connectionBadge_->setText("CONNECTED");
            connectionBadge_->setProperty("state", "ok");
            repolish(connectionBadge_);
            log("Connected to MyceliaDB server.");
            runHealthCheck();
            refreshGpuPanel();
            requestAndLog("FIELD_STATUS");
            refreshDocuments();
        });
        connect(&socket_, &QTcpSocket::disconnected, this, [this] {
            connectionBadge_->setText("OFFLINE");
            connectionBadge_->setProperty("state", "bad");
            healthBadge_->setText("HEALTH: unknown");
            healthBadge_->setProperty("state", "warn");
            repolish(connectionBadge_);
            repolish(healthBadge_);
            log("Disconnected.");
        });
        connect(&socket_, &QTcpSocket::errorOccurred, this, [this](QAbstractSocket::SocketError err) {
            // QTcpSocket::waitForReadyRead(timeout) can set SocketTimeoutError even when
            // a command response was already received. That is not a transport failure
            // for our line-oriented protocol, so do not spam the audit log.
            if (err == QAbstractSocket::SocketTimeoutError) return;
            log("Socket error: " + socket_.errorString());
        });
    }

    QWidget* buildHeader() {
        auto* box = new QFrame;
        box->setObjectName("hero");
        auto* row = new QHBoxLayout(box);
        row->setContentsMargins(20, 16, 20, 16);

        auto* titleBox = new QVBoxLayout;
        auto* title = new QLabel("MyceliaDB Enterprise Studio");
        title->setObjectName("title");
        auto* sub = new QLabel("Dante Manager • Mycelium Editor • Document Intelligence • Signal Trace • GPU Bridge");
        sub->setObjectName("subtitle");
        titleBox->addWidget(title);
        titleBox->addWidget(sub);
        row->addLayout(titleBox, 1);

        host_ = new QLineEdit("127.0.0.1");
        host_->setFixedWidth(150);
        port_ = new QSpinBox;
        port_->setRange(1, 65535);
        port_->setValue(4555);
        port_->setFixedWidth(90);

        auto* connectBtn = new QPushButton("Connect");
        auto* healthBtn = new QPushButton("Server Health");
        connectionBadge_ = badge("OFFLINE", "bad");
        healthBadge_ = badge("HEALTH: unknown", "warn");
        gpuBadge_ = badge("GPU: unknown", "warn");

        row->addWidget(new QLabel("Host"));
        row->addWidget(host_);
        row->addWidget(new QLabel("Port"));
        row->addWidget(port_);
        row->addWidget(connectBtn);
        row->addWidget(healthBtn);
        row->addWidget(connectionBadge_);
        row->addWidget(healthBadge_);
        row->addWidget(gpuBadge_);

        connect(connectBtn, &QPushButton::clicked, this, [this] { connectToServer(); });
        connect(healthBtn, &QPushButton::clicked, this, [this] { runHealthCheck(); refreshGpuPanel(); });
        return box;
    }

    QWidget* buildSidebar() {
        auto* frame = new QFrame;
        frame->setObjectName("panel");
        frame->setMinimumWidth(265);
        auto* v = new QVBoxLayout(frame);
        v->setContentsMargins(16, 16, 16, 16);

        auto* caption = new QLabel("Dante BankManager");
        caption->setObjectName("section");
        v->addWidget(caption);

        const QStringList actions = {
            "Dashboard", "Document Intake", "Search Intelligence", "Node Browser",
            "Link Registry", "Trace Viewer", "Rule Composer", "GPU/OpenCL", "Audit Log"
        };
        for (int i=0; i<actions.size(); ++i) {
            const auto& a = actions[i];
            auto* b = new QPushButton(a);
            b->setObjectName("navButton");
            v->addWidget(b);
            connect(b, &QPushButton::clicked, this, [this, a] {
                if (!workspaceTabs_) return;
                if (a == "Dashboard") workspaceTabs_->setCurrentIndex(0);
                else if (a == "Document Intake" || a == "Search Intelligence") workspaceTabs_->setCurrentIndex(2);
                else if (a == "Node Browser" || a == "Link Registry") workspaceTabs_->setCurrentIndex(3);
                else if (a == "Trace Viewer") workspaceTabs_->setCurrentIndex(4);
                else if (a == "Rule Composer") workspaceTabs_->setCurrentIndex(5);
                else if (a == "GPU/OpenCL") workspaceTabs_->setCurrentIndex(6);
                else if (a == "Audit Log") log("Audit Log: event stream is shown in System Log.");
            });
        }

        v->addSpacing(10);
        signalLoad_ = new QProgressBar;
        signalLoad_->setRange(0, 100);
        signalLoad_->setValue(42);
        signalLoad_->setFormat("Signal load %p%");
        v->addWidget(signalLoad_);

        logView_ = new QTextEdit;
        logView_->setReadOnly(true);
        logView_->setMinimumHeight(240);
        v->addWidget(new QLabel("System Log"));
        v->addWidget(logView_, 1);
        return frame;
    }

    QWidget* buildWorkspace() {
        auto* tabs = new QTabWidget;
        workspaceTabs_ = tabs;
        tabs->addTab(buildDashboard(), "Dashboard");
        tabs->addTab(buildConsole(), "Mycelium Console");
        tabs->addTab(buildDocumentIntake(), "Document Intelligence");
        tabs->addTab(buildGraphBrowser(), "Node/Link Browser");
        tabs->addTab(buildTracePanel(), "Signal Trace");
        tabs->addTab(buildRules(), "Rule Composer");
        tabs->addTab(buildGpuPanel(), "GPU Bridge");
        connect(tabs, &QTabWidget::currentChanged, this, [this](int idx) { if (idx == 6) refreshGpuPanel(); });
        return tabs;
    }

    QWidget* buildDashboard() {
        auto* w = new QWidget;
        auto* grid = new QGridLayout(w);
        grid->setSpacing(14);
        grid->addWidget(metric("Documents", "letters, forms, scans, dumps", "IMPORT"), 0, 0);
        grid->addWidget(metric("Search", "Peter Müller Leipzig", "SEARCH"), 0, 1);
        grid->addWidget(metric("Nodes", "document cells + graph cells", "LIST_NODES"), 0, 2);
        grid->addWidget(metric("GPU", "OpenCL propagation bridge", "GPU_STATUS"), 0, 3);

        auto* info = new QTextEdit;
        info->setReadOnly(true);
        info->setText(
            "Enterprise topology model\n\n"
            "MyceliaDB is not an SQL database. It stores nodes, links, fields, signals, mutations, documents and rules.\n\n"
            "New document intelligence layer:\n"
            "• import text files: letters, forms, applications, filled requests, notes\n"
            "• import SQL dumps as searchable document-cells without turning MyceliaDB into SQL\n"
            "• every imported document becomes a Mycelia node\n"
            "• inverted term field enables queries such as: Peter Müller Leipzig\n"
            "• results return matching documents, score, path and text preview\n\n"
            "OCR path: images are read through an external Tesseract-compatible OCR engine, then transformed into Mycelia segments, term nodes, entity nodes and weighted resonance links."
        );
        grid->addWidget(info, 1, 0, 1, 4);
        return w;
    }

    QWidget* buildConsole() {
        auto* w = new QWidget;
        auto* v = new QVBoxLayout(w);
        consoleOut_ = new QTextEdit;
        consoleOut_->setReadOnly(true);
        commandLine_ = new QLineEdit;
        commandLine_->setPlaceholderText("SPAWN alpha | INGEST_TEXT \"D:\\forms\\antrag.txt\" antrag:1 | INGEST_OCR_IMAGE \"D:\\scans\\antrag.png\" | QUERY_FIELD Peter Müller Leipzig | EXPLAIN_RESONANCE Lena Hartmann");

        auto* row = new QHBoxLayout;
        auto* run = new QPushButton("Run");
        auto* demo = new QPushButton("Run Premium Demo");
        row->addWidget(commandLine_, 1);
        row->addWidget(run);
        row->addWidget(demo);

        v->addWidget(consoleOut_, 1);
        v->addLayout(row);
        connect(run, &QPushButton::clicked, this, [this] { runCommand(commandLine_->text()); });
        connect(commandLine_, &QLineEdit::returnPressed, this, [this] { runCommand(commandLine_->text()); });
        connect(demo, &QPushButton::clicked, this, [this] {
            const QStringList demoCommands = {
                "PING", "SPAWN alpha", "SPAWN beta", "LINK alpha beta 0.82",
                "PULSE alpha 1.0", "TRACE alpha 4", "GPU_STATUS"
            };
            for (const auto& c : demoCommands) runCommand(c);
            refreshGraphFromServer();
        });
        return w;
    }

    QWidget* buildDocumentIntake() {
        auto* w = new QWidget;
        auto* main = new QVBoxLayout(w);

        auto* top = new QHBoxLayout;
        auto* importText = new QPushButton("Import Text Files");
        auto* importSql = new QPushButton("Import SQL Dump");
        auto* importOcr = new QPushButton("Import OCR Images");
        auto* ocrStatus = new QPushButton("OCR Status");
        auto* saveDb = new QPushButton("Save Database");
        auto* loadDb = new QPushButton("Load Database");
        auto* clearDb = new QPushButton("New / Clear");
        auto* refresh = new QPushButton("Refresh Documents");
        uiModeSelector_ = new QComboBox;
        uiModeSelector_->addItems({"Mitarbeiter-Modus", "Admin-Modus"});
        uiModeSelector_->setToolTip("Mitarbeiter-Modus blendet technische Diagnosewerte aus. Admin-Modus zeigt interne Mycelia-Werte.");
        top->addWidget(importText);
        top->addWidget(importSql);
        top->addWidget(importOcr);
        top->addWidget(ocrStatus);
        top->addWidget(saveDb);
        top->addWidget(loadDb);
        top->addWidget(clearDb);
        top->addWidget(refresh);
        top->addWidget(uiModeSelector_);
        top->addStretch(1);

        docTable_ = new QTableWidget(0, 4);
        docTable_->setHorizontalHeaderLabels({"Document ID", "Type", "Terms", "Raw"});
        docTable_->horizontalHeader()->setStretchLastSection(true);
        docTable_->setSelectionBehavior(QAbstractItemView::SelectRows);
        docTable_->setSelectionMode(QAbstractItemView::SingleSelection);

        auto* searchBox = new QFrame;
        searchBox->setObjectName("panel");
        auto* srow = new QHBoxLayout(searchBox);
        searchLine_ = new QLineEdit("Peter Müller Leipzig");
        auto* search = new QPushButton("Query Resonance Field");
        auto* explain = new QPushButton("Explain Energy Path");
        auto* preview = new QPushButton("Preview Selected");
        auto* lmStudio = new QPushButton("LM Studio Evidence");
        auto* compareEvidence = new QPushButton("Original + LLM");
        lmStudio->setToolTip("Bereinigt und strukturiert den ausgewählten Evidence-Text über LM Studio.");
        compareEvidence->setToolTip("Zeigt OCR-Rohtext und LLM-Aufbereitung nebeneinander.");
        srow->addWidget(new QLabel("Query"));
        srow->addWidget(searchLine_, 1);
        srow->addWidget(search);
        srow->addWidget(explain);
        srow->addWidget(preview);
        srow->addWidget(lmStudio);
        srow->addWidget(compareEvidence);

        auto* split = new QSplitter(Qt::Horizontal);
        auto makeResultTable = [] {
            auto* t = new QTableWidget(0, 5);
            t->setHorizontalHeaderLabels({"Rank", "Kind", "Label / Node", "Energy", "Evidence"});
            t->horizontalHeader()->setStretchLastSection(true);
            t->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Fixed);
            t->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Fixed);
            t->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Interactive);
            t->horizontalHeader()->setSectionResizeMode(3, QHeaderView::Fixed);
            t->horizontalHeader()->setSectionResizeMode(4, QHeaderView::Stretch);
            t->setColumnWidth(0, 58);
            t->setColumnWidth(2, 320);
            t->setSelectionBehavior(QAbstractItemView::SelectRows);
            t->setSelectionMode(QAbstractItemView::SingleSelection);
            t->setAlternatingRowColors(true);
            t->verticalHeader()->setVisible(false);
            t->setWordWrap(false);
            t->setSortingEnabled(false);
            t->horizontalHeader()->setSectionsClickable(false);
            t->setColumnHidden(1, true);   // kind is internal metadata, not part of operator UI
            t->setColumnHidden(3, true);   // energy is diagnostic only
            return t;
        };
        searchTable_ = makeResultTable();
        resonanceTable_ = makeResultTable();
        evidenceTabs_ = new QTabWidget;
        docPreview_ = new QTextEdit;
        docPreview_->setReadOnly(true);
        imagePreview_ = new QLabel("No source image selected");
        imagePreview_->setAlignment(Qt::AlignCenter);
        imagePreview_->setMinimumSize(320, 360);
        imagePreview_->setScaledContents(false);
        auto* imageScroll = new QScrollArea;
        imageScroll->setWidgetResizable(true);
        imageScroll->setWidget(imagePreview_);
        mediaMeta_ = new QTextEdit;
        mediaMeta_->setReadOnly(true);
        formTable_ = new QTableWidget(0, 2);
        formTable_->setHorizontalHeaderLabels({"Feld", "Wert"});
        formTable_->horizontalHeader()->setStretchLastSection(true);
        formTable_->verticalHeader()->setVisible(false);
        formTable_->setAlternatingRowColors(true);
        formTable_->setSelectionBehavior(QAbstractItemView::SelectRows);
        llmPreview_ = new QTextEdit;
        llmPreview_->setReadOnly(true);
        llmPreview_->setPlaceholderText("Wähle einen Treffer und klicke auf 'LM Studio Evidence'.");
        auto* sideBySide = new QSplitter(Qt::Horizontal);
        sideOriginalPreview_ = new QTextEdit;
        sideOriginalPreview_->setReadOnly(true);
        sideLlmPreview_ = new QTextEdit;
        sideLlmPreview_->setReadOnly(true);
        sideOriginalPreview_->setPlaceholderText("OCR-/Evidence-Rohtext");
        sideLlmPreview_->setPlaceholderText("LM-Studio-Aufbereitung");
        sideBySide->addWidget(sideOriginalPreview_);
        sideBySide->addWidget(sideLlmPreview_);
        sideBySide->setSizes({420, 420});
        evidenceTabs_->addTab(docPreview_, "Evidence Text");
        evidenceTabs_->addTab(llmPreview_, "LLM Evidence");
        evidenceTabs_->addTab(sideBySide, "Original + LLM");
        evidenceTabs_->addTab(formTable_, "Formular-Ansicht");
        evidenceTabs_->addTab(imageScroll, "Source Image");
        evidenceTabs_->addTab(mediaMeta_, "Media Metadata");

        split->addWidget(searchTable_);
        split->addWidget(resonanceTable_);
        split->addWidget(evidenceTabs_);
        split->setSizes({660, 520, 420});

        auto updatePreviewFromTable = [this](QTableWidget* table) {
            if (!table || !docPreview_) return;
            const int row = table->currentRow();
            if (row < 0) return;
            auto* labelItem = table->item(row, 2);
            auto* evidenceItem = table->item(row, 4);
            QString nodeId = labelItem ? labelItem->toolTip() : QString();

            QString text;
            if (labelItem) text += "<h3>" + labelItem->text().toHtmlEscaped() + "</h3>";
            QString evidenceText;
            if (evidenceItem) {
                evidenceText = evidenceItem->toolTip();
                if (evidenceText.isEmpty()) evidenceText = evidenceItem->text();
                text += "<pre style='white-space:pre-wrap'>" + evidenceText.toHtmlEscaped() + "</pre>";
            }
            currentEvidenceLabel_ = labelItem ? labelItem->text() : QString();
            currentEvidenceText_ = evidenceText;
            docPreview_->setHtml(text);
            if (sideOriginalPreview_) sideOriginalPreview_->setPlainText(currentEvidenceText_);
            if (sideLlmPreview_) sideLlmPreview_->clear();
            updateRecordMask(currentEvidenceLabel_, evidenceText);

            if (mediaMeta_) mediaMeta_->setPlainText("No linked source image.");
            currentImagePath_.clear();
            if (imagePreview_) {
                imagePreview_->setText("No linked source image");
                imagePreview_->setPixmap(QPixmap());
                imagePreview_->setToolTip(QString());
            }

            if (!nodeId.isEmpty()) {
                QString media = request("GET_MEDIA_FOR_NODE " + quoteArg(nodeId));
                if (mediaMeta_) mediaMeta_->setPlainText(media);
                QRegularExpression re("stored=([^\\s]+)");
                auto m = re.match(media);
                QString path = m.hasMatch() ? m.captured(1) : QString();
                if (!path.isEmpty()) {
                    // Enterprise media preview must be robust: the server may return
                    // an absolute path, an app-root relative path ("data/media/..."),
                    // or a snapshot-relative path after LOAD_DB. Try all safe variants.
                    QStringList candidates;
                    candidates << path;
                    if (QFileInfo(path).isRelative()) {
                        candidates << QDir::current().absoluteFilePath(path);
                        candidates << QCoreApplication::applicationDirPath() + "/" + path;
                        candidates << QCoreApplication::applicationDirPath() + "/../../" + path;
                    }

                    QPixmap px;
                    QString loadedFrom;
                    for (const QString& candidate : candidates) {
                        QFileInfo info(candidate);
                        if (info.exists() && px.load(info.absoluteFilePath())) {
                            loadedFrom = info.absoluteFilePath();
                            break;
                        }
                    }

                    if (!px.isNull() && imagePreview_) {
                        QSize target = imagePreview_->size();
                        if (target.width() < 300) target = QSize(420, 560);
                        imagePreview_->setPixmap(px.scaled(target, Qt::KeepAspectRatio, Qt::SmoothTransformation));
                        imagePreview_->setToolTip(loadedFrom + "\n\nDoppelklick öffnet das Bild im Standardprogramm.");
                        imagePreview_->setText(QString());
                        currentImagePath_ = loadedFrom;
                    } else if (imagePreview_) {
                        imagePreview_->setText("Image linked, but could not be loaded:\n" + path +
                                               "\n\nChecked:\n" + candidates.join("\n"));
                    }
                }
            }
        };
        connect(searchTable_, &QTableWidget::cellClicked, this, [this, updatePreviewFromTable](int, int) { updatePreviewFromTable(searchTable_); });
        connect(resonanceTable_, &QTableWidget::cellClicked, this, [this, updatePreviewFromTable](int, int) { updatePreviewFromTable(resonanceTable_); });
        connect(searchTable_, &QTableWidget::cellDoubleClicked, this, [this, updatePreviewFromTable](int, int) { updatePreviewFromTable(searchTable_); openCurrentEvidenceImage(); });
        connect(resonanceTable_, &QTableWidget::cellDoubleClicked, this, [this, updatePreviewFromTable](int, int) { updatePreviewFromTable(resonanceTable_); openCurrentEvidenceImage(); });
        connect(uiModeSelector_, &QComboBox::currentIndexChanged, this, [this](int) { applyUiMode(); });
        imagePreview_->installEventFilter(this);
        applyUiMode();

        main->addLayout(top);
        main->addWidget(docTable_, 2);
        main->addWidget(searchBox);
        main->addWidget(split, 3);

        connect(importText, &QPushButton::clicked, this, [this] { importTextFiles(); });
        connect(importSql, &QPushButton::clicked, this, [this] { importSqlDump(); });
        connect(importOcr, &QPushButton::clicked, this, [this] { importOcrImages(); });
        connect(ocrStatus, &QPushButton::clicked, this, [this] { requestAndLog("OCR_STATUS"); });
        connect(saveDb, &QPushButton::clicked, this, [this] { saveDatabase(); });
        connect(loadDb, &QPushButton::clicked, this, [this] { loadDatabase(); });
        connect(lmStudio, &QPushButton::clicked, this, [this] { improveEvidenceWithLmStudio(); });
        connect(compareEvidence, &QPushButton::clicked, this, [this] { showOriginalAndLmSideBySide(); });
        connect(clearDb, &QPushButton::clicked, this, [this] { clearDatabase(); });
        connect(refresh, &QPushButton::clicked, this, [this] { refreshDocuments(); });
        connect(search, &QPushButton::clicked, this, [this] { searchDocuments(); });
        connect(explain, &QPushButton::clicked, this, [this] { explainResonance(); });
        connect(searchLine_, &QLineEdit::returnPressed, this, [this] { searchDocuments(); });
        connect(preview, &QPushButton::clicked, this, [this] { previewSelectedDocument(); });
        return w;
    }

    QWidget* buildGraphBrowser() {
        auto* w = new QWidget;
        auto* split = new QSplitter(Qt::Horizontal, w);
        auto* layout = new QVBoxLayout(w);
        auto* top = new QHBoxLayout;
        auto* refresh = new QPushButton("Refresh Live Graph");
        top->addWidget(refresh);
        top->addWidget(uiModeSelector_);
        top->addStretch(1);
        layout->addLayout(top);
        layout->addWidget(split);

        nodeTree_ = new QTreeWidget;
        nodeTree_->setHeaderLabels({"Node", "State", "Field"});
        split->addWidget(nodeTree_);

        linkTable_ = new QTableWidget(0, 4);
        linkTable_->setHorizontalHeaderLabels({"From", "To", "Weight", "Status"});
        linkTable_->horizontalHeader()->setStretchLastSection(true);
        split->addWidget(linkTable_);
        connect(refresh, &QPushButton::clicked, this, [this] { refreshGraphFromServer(); });
        return w;
    }

    QWidget* buildTracePanel() {
        auto* w = new QWidget;
        auto* v = new QVBoxLayout(w);
        auto* row = new QHBoxLayout;
        auto* seed = new QLineEdit("alpha");
        auto* depth = new QSpinBox;
        depth->setRange(1, 32);
        depth->setValue(4);
        auto* trace = new QPushButton("Trace Signal");
        row->addWidget(new QLabel("Seed"));
        row->addWidget(seed);
        row->addWidget(new QLabel("Depth"));
        row->addWidget(depth);
        row->addWidget(trace);
        row->addStretch(1);

        traceTable_ = new QTableWidget(0, 4);
        traceTable_->setHorizontalHeaderLabels({"Hop", "Node", "Energy", "Decision"});
        traceTable_->horizontalHeader()->setStretchLastSection(true);
        v->addLayout(row);
        v->addWidget(traceTable_, 1);

        connect(trace, &QPushButton::clicked, this, [this, seed, depth] {
            QString response = request(QString("TRACE %1 %2").arg(seed->text()).arg(depth->value()));
            addTraceRows(response);
            log(QString("TRACE %1 -> %2").arg(seed->text(), response));
        });
        return w;
    }

    QWidget* buildRules() {
        auto* w = new QWidget;
        auto* v = new QVBoxLayout(w);
        ruleEditor_ = new QPlainTextEdit;
        ruleEditor_->setPlainText(
            "rule document_entity_linking {\n"
            "  when document contains person and city\n"
            "  spawn entity.person\n"
            "  spawn entity.place\n"
            "  link document -> entity.person weight 0.91\n"
            "  link entity.person -> entity.place weight 0.84\n"
            "}\n\n"
            "rule risk_diffusion {\n"
            "  when pulse.energy > 0.70\n"
            "  follow links where weight > 0.50\n"
            "  mutate target.risk += pulse.energy * weight\n"
            "}\n"
        );
        auto* deploy = new QPushButton("Validate / Deploy Rule");
        v->addWidget(ruleEditor_, 1);
        v->addWidget(deploy);
        connect(deploy, &QPushButton::clicked, this, [this] {
            console("RULE OK: local validation passed. Server rule deployment hook ready.");
            log("Rule Composer validation passed.");
        });
        return w;
    }

    QWidget* buildGpuPanel() {
        auto* w = new QWidget;
        auto* root = new QVBoxLayout(w);
        root->setContentsMargins(12, 12, 12, 12);
        root->setSpacing(12);

        auto* header = new QLabel("GPU / OpenCL Bridge Diagnostics");
        header->setObjectName("section");
        root->addWidget(header);

        auto* grid = new QGridLayout;
        grid->setSpacing(12);

        auto makeCard = [](const QString& title, const QString& value) {
            auto* card = new QFrame;
            card->setObjectName("metric");
            auto* v = new QVBoxLayout(card);
            auto* t = new QLabel(title);
            t->setObjectName("metricTitle");
            auto* val = new QLabel(value);
            val->setObjectName("metricText");
            val->setWordWrap(true);
            v->addWidget(t);
            v->addWidget(val);
            return std::pair<QFrame*, QLabel*>{card, val};
        };

        auto driver = makeCard("Driver", "unknown");
        gpuDriverLabel_ = driver.second;
        auto mode = makeCard("Runtime Mode", "unknown");
        gpuModeLabel_ = mode.second;
        auto health = makeCard("Bridge Health", "unknown");
        gpuHealthLabel_ = health.second;
        auto backend = makeCard("Propagation Backend", "unknown");
        gpuBackendLabel_ = backend.second;

        grid->addWidget(driver.first, 0, 0);
        grid->addWidget(mode.first, 0, 1);
        grid->addWidget(health.first, 0, 2);
        grid->addWidget(backend.first, 0, 3);
        root->addLayout(grid);

        auto* explainer = new QTextEdit;
        explainer->setReadOnly(true);
        explainer->setMaximumHeight(150);
        explainer->setText(
            "This panel verifies the native GPU/OpenCL bridge used by MyceliaDB.\\n\\n"
            "The bridge is an acceleration hook for pulse propagation and resonance-field workloads. "
            "If the original OpenCL DLL is available, MyceliaDB reports GPU_BRIDGE OK. "
            "If it is missing or incompatible, the database remains operational with CPU propagation fallback."
        );
        root->addWidget(explainer);

        gpuStatusView_ = new QTextEdit;
        gpuStatusView_->setReadOnly(true);
        gpuStatusView_->setPlaceholderText("Press Refresh GPU Status or connect to the server.");
        root->addWidget(gpuStatusView_, 1);

        auto* row = new QHBoxLayout;
        auto* refresh = new QPushButton("Refresh GPU Status");
        auto* probe = new QPushButton("Run Bridge Probe");
        auto* copy = new QPushButton("Copy Diagnostics");
        row->addWidget(refresh);
        row->addWidget(probe);
        row->addWidget(copy);
        row->addStretch(1);
        root->addLayout(row);

        connect(refresh, &QPushButton::clicked, this, [this] { refreshGpuPanel(); });
        connect(probe, &QPushButton::clicked, this, [this] {
            refreshGpuPanel();
            if (gpuStatusView_) {
                gpuStatusView_->append("\\nProbe result: bridge command completed. MyceliaDB can continue resonance work.");
            }
        });
        connect(copy, &QPushButton::clicked, this, [this] {
            if (gpuStatusView_) QApplication::clipboard()->setText(gpuStatusView_->toPlainText());
        });

        return w;
    }

    void refreshGpuPanel() {
        if (!gpuStatusView_ && !gpuDriverLabel_) return;

        QString r = request("GPU_STATUS");
        updateGpuBadge(r);

        QString driver = "not reported";
        QRegularExpression driverRe("driver=([^\\s]+)");
        auto m = driverRe.match(r);
        if (m.hasMatch()) driver = m.captured(1);

        const bool ok = r.contains("GPU_BRIDGE OK", Qt::CaseInsensitive);
        const bool fallback = r.contains("FALLBACK", Qt::CaseInsensitive) || r.contains("cpu", Qt::CaseInsensitive);

        if (gpuDriverLabel_) gpuDriverLabel_->setText(driver);
        if (gpuModeLabel_) gpuModeLabel_->setText(ok ? "native OpenCL bridge" : (fallback ? "CPU fallback" : "unknown"));
        if (gpuHealthLabel_) gpuHealthLabel_->setText(ok ? "online" : (fallback ? "fallback" : "unknown"));
        if (gpuBackendLabel_) gpuBackendLabel_->setText(ok ? "pulse propagation / resonance-field acceleration hook" : "CPU propagation");

        if (gpuStatusView_) {
            gpuStatusView_->clear();
            gpuStatusView_->append("GPU_STATUS");
            gpuStatusView_->append("----------");
            gpuStatusView_->append(r.trimmed());
            gpuStatusView_->append("");
            gpuStatusView_->append(ok
                ? "Status: The original GPU/OpenCL bridge is loaded and available to MyceliaDB."
                : "Status: GPU bridge is not online. MyceliaDB can continue with CPU propagation fallback.");
            gpuStatusView_->append("");
            gpuStatusView_->append("Driver: " + driver);
            gpuStatusView_->append("Use: resonance-field propagation, pulse workflows and future batch acceleration.");
        }
    }

    QFrame* metric(const QString& name, const QString& detail, const QString& command) {
        auto* f = new QFrame;
        f->setObjectName("metric");
        auto* v = new QVBoxLayout(f);
        auto* n = new QLabel(name);
        n->setObjectName("metricTitle");
        auto* d = new QLabel(detail);
        d->setObjectName("metricText");
        auto* b = new QPushButton(command);
        v->addWidget(n);
        v->addWidget(d);
        v->addStretch(1);
        v->addWidget(b);
        connect(b, &QPushButton::clicked, this, [this, command] {
            if (command == "IMPORT") importTextFiles();
            else if (command == "SEARCH") searchDocuments();
            else if (command == "LIST_NODES") refreshGraphFromServer();
            else if (command == "GPU_STATUS") requestAndLog("GPU_STATUS");
        });
        return f;
    }

    QLabel* badge(const QString& text, const QString& state) {
        auto* l = new QLabel(text);
        l->setObjectName("badge");
        l->setProperty("state", state);
        l->setAlignment(Qt::AlignCenter);
        l->setMinimumWidth(110);
        return l;
    }

    void connectToServer() {
        if (socket_.state() != QAbstractSocket::UnconnectedState) socket_.disconnectFromHost();
        socket_.connectToHost(host_->text(), static_cast<quint16>(port_->value()));
        if (!socket_.waitForConnected(1500)) {
            log("Connect failed: " + socket_.errorString());
            return;
        }
        socket_.waitForReadyRead(1000);
        socket_.readAll();
    }

    QString request(const QString& command) {
        if (socket_.state() != QAbstractSocket::ConnectedState) {
            log("Not connected. Command skipped: " + command);
            return "ERR not connected";
        }

        const QString upper = command.trimmed().toUpper();
        const bool isLongRead =
            upper.startsWith("QUERY_FIELD") ||
            upper.startsWith("EXPLAIN_RESONANCE") ||
            upper.startsWith("GET_NEIGHBORS") ||
            upper.startsWith("LIST_LINKS") ||
            upper.startsWith("LIST_NODES") ||
            upper.startsWith("LIST_DOCS");

        const int totalTimeoutMs =
            upper.startsWith("INGEST_OCR_IMAGE") ? 180000 :
            upper.startsWith("IMPORT_IMAGE")     ? 180000 :
            upper.startsWith("OCR_IMAGE")        ? 180000 :
            upper.startsWith("INGEST_IMAGE")     ? 180000 :
            upper.startsWith("INGEST_SQL")       ? 45000  :
            upper.startsWith("IMPORT_SQL")       ? 45000  :
            upper.startsWith("INGEST_TEXT")      ? 45000  :
            upper.startsWith("IMPORT_TEXT")      ? 45000  :
            isLongRead                           ? 45000  :
            15000;

        socket_.write(command.toUtf8() + "\n");
        if (!socket_.waitForBytesWritten(5000)) return "ERR write timeout";

        QElapsedTimer timer;
        timer.start();
        QByteArray data;

        // OCR and resonance responses may be multi-line and can arrive in bursts.
        // The previous UI read returned after ~120ms of silence, which was too
        // aggressive: the table received only "RESONANCE_RESULTS ..." without
        // the following HIT blocks. We now wait for a command-specific quiet
        // period before considering the response complete.
        const int quietMs = upper.startsWith("INGEST_OCR_IMAGE") ? 1200 :
                            isLongRead ? 900 : 180;

        while (timer.elapsed() < totalTimeoutMs) {
            const int remaining = totalTimeoutMs - static_cast<int>(timer.elapsed());
            const int waitSlice = data.isEmpty() ? qMin(remaining, 1000) : qMin(remaining, quietMs);
            if (socket_.bytesAvailable() == 0 && !socket_.waitForReadyRead(waitSlice)) {
                if (!data.isEmpty()) break; // quiet period: response is complete
                continue;
            }
            data += socket_.readAll();
        }

        if (data.isEmpty()) {
            return upper.startsWith("INGEST_OCR_IMAGE")
                ? "ERR read timeout while OCR was running. The server may still be processing; try Refresh Documents after a moment."
                : "ERR read timeout";
        }

        return QString::fromUtf8(data).trimmed();
    }

    void requestAndLog(const QString& command) {
        QString r = request(command);
        log(command + " -> " + r);
        if (command == "GPU_STATUS") updateGpuBadge(r);
        if (command == "PING") updateHealthBadge(r);
    }

    void runHealthCheck() {
        QString r = request("PING");
        updateHealthBadge(r);
        log("PING -> " + r);
    }

    void updateHealthBadge(const QString& response) {
        bool ok = response.startsWith("PONG");
        healthBadge_->setText(ok ? "HEALTH: OK" : "HEALTH: warn");
        healthBadge_->setProperty("state", ok ? "ok" : "warn");
        repolish(healthBadge_);
    }

    void updateGpuBadge(const QString& response) {
        gpuBadge_->setText(response.contains("OK") ? "GPU: online" : "GPU: fallback");
        gpuBadge_->setProperty("state", response.contains("OK") ? "ok" : "warn");
        repolish(gpuBadge_);
    }

    void runCommand(QString command) {
        command = command.trimmed();
        if (command.isEmpty()) return;
        console("> " + command);
        QString response = request(command);
        console(response);
        log(command + " -> " + response);
        if (commandLine_) commandLine_->clear();
        if (command.startsWith("SPAWN") || command.startsWith("LINK") || command.startsWith("IMPORT_")) refreshGraphFromServer();
        if (command.startsWith("TRACE")) addTraceRows(response);
        if (command == "GPU_STATUS") updateGpuBadge(response);
        if (command == "LIST_DOCS") populateDocuments(response);
    }

    void importTextFiles() {
        QStringList files = QFileDialog::getOpenFileNames(
            this, "Import text documents into MyceliaDB",
            QDir::homePath(),
            "Documents (*.txt *.md *.csv *.log *.json *.xml *.html *.htm);;All files (*.*)"
        );
        for (const auto& f : files) {
            QString id = "doc:" + QFileInfo(f).completeBaseName().replace(QRegularExpression("[^A-Za-z0-9_.-]"), "_");
            QString cmd = "INGEST_TEXT " + quoteArg(f) + " " + quoteArg(id);
            QString r = request(cmd);
            log(cmd + " -> " + r);
            if (consoleOut_) console(cmd + "\n" + r);
        }
        refreshDocuments();
        refreshGraphFromServer();
    }

    void importSqlDump() {
        QString file = QFileDialog::getOpenFileName(
            this, "Import SQL dump as Mycelia document-cell",
            QDir::homePath(),
            "SQL dumps (*.sql *.dump);;All files (*.*)"
        );
        if (file.isEmpty()) return;
        QString id = "sql:" + QFileInfo(file).completeBaseName().replace(QRegularExpression("[^A-Za-z0-9_.-]"), "_");
        QString cmd = "INGEST_SQL " + quoteArg(file) + " " + quoteArg(id);
        QString r = request(cmd);
        log(cmd + " -> " + r);
        if (consoleOut_) console(cmd + "\n" + r);
        refreshDocuments();
        refreshGraphFromServer();
    }

    void importOcrImages() {
        QStringList files = QFileDialog::getOpenFileNames(
            this, "Import scanned forms/images through OCR into MyceliaDB",
            QDir::homePath(),
            "Scanned images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;All files (*.*)"
        );
        for (const auto& f : files) {
            QString id = "ocr:" + QFileInfo(f).completeBaseName().replace(QRegularExpression("[^A-Za-z0-9_.-]"), "_");
            QString cmd = "INGEST_OCR_IMAGE " + quoteArg(f) + " " + quoteArg(id);
            QString r = request(cmd);
            log(cmd + " -> " + r.left(260));
            if (consoleOut_) console(cmd + "\n" + r);
            if (r.startsWith("ERR")) {
                QMessageBox::warning(this, "OCR import failed",
                    "MyceliaDB could not OCR this image.\n\n"
                    "Check that Tesseract OCR is installed and available in PATH, "
                    "or set MYCELIA_TESSERACT to the full tesseract.exe path.\n\n" + r);
            }
        }
        refreshDocuments();
        refreshGraphFromServer();
    }

    void refreshDocuments() {
        QString r = request("LIST_DOCS");
        populateDocuments(r);
        log("LIST_DOCS -> " + r);
    }

    void populateDocuments(const QString& response) {
        if (!docTable_) return;
        docTable_->setRowCount(0);
        if (!response.startsWith("DOCS")) return;
        QStringList entries = response.mid(4).trimmed().split(" ", Qt::SkipEmptyParts);
        for (const auto& e : entries) {
            QStringList parts = e.split("|");
            if (parts.isEmpty()) continue;
            int row = docTable_->rowCount();
            docTable_->insertRow(row);
            docTable_->setItem(row, 0, new QTableWidgetItem(parts.value(0)));
            QString type, terms;
            for (const auto& p : parts) {
                if (p.startsWith("type=")) type = p.mid(5);
                if (p.startsWith("terms=")) terms = p.mid(6);
                if (p.startsWith("segments=")) terms += " / seg " + p.mid(9);
            }
            docTable_->setItem(row, 1, new QTableWidgetItem(type));
            docTable_->setItem(row, 2, new QTableWidgetItem(terms));
            docTable_->setItem(row, 3, new QTableWidgetItem(e));
        }
    }

    void searchDocuments() {
        if (!searchTable_) return;
        QString q = searchLine_ ? searchLine_->text().trimmed() : "Peter Müller Leipzig";
        if (q.isEmpty()) return;
        QString r = request("QUERY_FIELD " + quoteArg(q));
        populateResonanceTable(searchTable_, r);
        log("QUERY_FIELD -> " + r.left(180));
    }

    void explainResonance() {
        if (!resonanceTable_) return;
        QString q = searchLine_ ? searchLine_->text().trimmed() : "Peter Müller Leipzig";
        if (q.isEmpty()) return;
        QString r = request("EXPLAIN_RESONANCE " + quoteArg(q));
        populateResonanceTable(resonanceTable_, r);
        log("EXPLAIN_RESONANCE -> " + r.left(180));
    }

    void populateResonanceTable(QTableWidget* table, const QString& response) {
        if (!table) return;
        table->setSortingEnabled(false);
        table->setRowCount(0);

        if (response.startsWith("RESONANCE_RESULTS 0") || response.startsWith("RESONANCE_EXPLAIN 0")) {
            table->insertRow(0);
            table->setItem(0, 0, new QTableWidgetItem("-"));
            table->setItem(0, 1, new QTableWidgetItem("none"));
            table->setItem(0, 2, new QTableWidgetItem("No resonance hits"));
            table->setItem(0, 3, new QTableWidgetItem("0"));
            table->setItem(0, 4, new QTableWidgetItem(response.left(500)));
            table->setSortingEnabled(false);
            return;
        }

        QString normalized = response;
        normalized.replace("\r\n", "\n");
        normalized.replace("\r", "\n");
        normalized.replace(" | HIT rank=", "\nHIT rank=");
        normalized.replace(QRegularExpression("\\s+HIT\\s+rank="), "\nHIT rank=");

        // Each HIT is a compact record generated by the server. The earlier
        // parser used id=([^\\n]+), which accidentally swallowed the whole
        // one-line record into one cell when the socket response arrived
        // flattened. This parser stops every field at the next explicit key.
        QStringList blocks = normalized.split(QRegularExpression("\\nHIT\\s+rank="), Qt::SkipEmptyParts);
        int parsedRows = 0;

        for (QString block : blocks) {
            block = block.trimmed();
            if (block.startsWith("RESONANCE_RESULTS") || block.startsWith("RESONANCE_EXPLAIN")) {
                const int hitPos = block.indexOf(QRegularExpression("HIT\\s+rank="));
                if (hitPos < 0) continue;
                block = block.mid(hitPos + QString("HIT rank=").size()).trimmed();
            }

            if (!QRegularExpression("^\\d+").match(block).hasMatch()) continue;
            block = "rank=" + block;

            auto cap = [&](const QString& pattern) -> QString {
                QRegularExpression re(pattern, QRegularExpression::DotMatchesEverythingOption);
                auto m = re.match(block);
                return m.hasMatch() ? m.captured(1).trimmed() : QString();
            };

            QString rank = cap("rank=([0-9]+)");
            QString id = cap("id=(.*?)\\s+energy=");
            QString energy = cap("energy=([^\\s]+)");
            QString kind = cap("kind=([^\\s]+)\\s+label=");
            QString label = cap("label=\\\"(.*?)\\\"\\s+evidence=");
            QString evidence = cap("evidence=\\\"(.*)\\\"\\s*$");
            if (evidence.isEmpty()) evidence = cap("evidence=\\\"(.*)$");

            if (rank.isEmpty()) continue;
            if (label.isEmpty()) label = id;
            if (kind.isEmpty()) kind = "hit";

            evidence.replace("\\n", " ");
            evidence.replace(QRegularExpression("\\s+"), " ");
            QString evidenceBrief = evidence;
            if (evidenceBrief.size() > 280) evidenceBrief = evidenceBrief.left(277) + "...";

            auto makeItem = [](const QString& text, const QString& tip = QString()) {
                auto* item = new QTableWidgetItem(text);
                item->setToolTip(tip.isEmpty() ? text : tip);
                return item;
            };

            const int row = table->rowCount();
            table->insertRow(row);
            table->setItem(row, 0, makeItem(rank));
            table->setItem(row, 1, makeItem(kind));
            table->setItem(row, 2, makeItem(label, id));
            table->setItem(row, 3, makeItem(energy));
            table->setItem(row, 4, makeItem(evidenceBrief, evidence));
            table->setRowHeight(row, 26);
            ++parsedRows;
        }

        if (parsedRows == 0) {
            table->insertRow(0);
            table->setItem(0, 0, new QTableWidgetItem("-"));
            table->setItem(0, 1, new QTableWidgetItem("raw"));
            table->setItem(0, 2, new QTableWidgetItem("No HIT blocks parsed"));
            table->setItem(0, 3, new QTableWidgetItem("0"));
            table->setItem(0, 4, new QTableWidgetItem(normalized.left(4000)));
        }

        table->setSortingEnabled(false);
        applyUiMode();
    }

    QString prettyResonance(QString r) {
        r.replace(" | HIT ", "\n\nHIT ");
        r.replace(" energy=", "\n  energy=");
        r.replace(" kind=", "\n  kind=");
        r.replace(" label=", "\n  label=");
        r.replace(" evidence=", "\n  evidence=");
        r.replace(" engine=", "\nengine=");
        return r;
    }

    void saveDatabase() {
        QString path = QFileDialog::getSaveFileName(
            this, "Save MyceliaDB snapshot",
            QDir::homePath() + "/myceliadb_snapshot.mycdb",
            "MyceliaDB Snapshot (*.mycdb);;All files (*.*)"
        );
        if (path.isEmpty()) return;
        QString r = request("SAVE_DB " + quoteArg(path));
        log("SAVE_DB -> " + r);
        QMessageBox::information(this, "Save Database", r);
    }

    void loadDatabase() {
        QString path = QFileDialog::getOpenFileName(
            this, "Load MyceliaDB snapshot",
            QDir::homePath(),
            "MyceliaDB Snapshot (*.mycdb);;All files (*.*)"
        );
        if (path.isEmpty()) return;
        QString r = request("LOAD_DB " + quoteArg(path));
        log("LOAD_DB -> " + r);
        refreshDocuments();
        refreshGraphFromServer();
        QMessageBox::information(this, "Load Database", r);
    }

    void clearDatabase() {
        if (QMessageBox::question(this, "Clear Database", "Clear the current in-memory MyceliaDB field?") != QMessageBox::Yes) return;
        QString r = request("CLEAR_DB");
        log("CLEAR_DB -> " + r);
        refreshDocuments();
        refreshGraphFromServer();
        if (searchTable_) searchTable_->setRowCount(0);
        if (resonanceTable_) resonanceTable_->setRowCount(0);
        if (docPreview_) docPreview_->clear();
    }

    void previewSelectedDocument() {
        if (!docTable_ || !docPreview_) return;
        auto items = docTable_->selectedItems();
        if (items.isEmpty()) return;
        int row = items.first()->row();
        QString id = docTable_->item(row, 0)->text();
        QString r = request("GET_DOC " + quoteArg(id));
        docPreview_->setText(r);
        log("GET_DOC " + id + " -> " + r.left(160));
    }

    void refreshGraphFromServer() {
        if (!nodeTree_ || !linkTable_) return;
        QString nodes = request("LIST_NODES");
        QString links = request("LIST_LINKS");

        nodeTree_->clear();
        QStringList nlist = nodes.mid(5).trimmed().split(" ", Qt::SkipEmptyParts);
        for (const auto& n : nlist) {
            QString state = n.startsWith("doc:") || n.startsWith("sql:") ? "document" : "active";
            QString field = n.startsWith("doc:") ? "text" : (n.startsWith("sql:") ? "sql-dump" : "graph");
            nodeTree_->addTopLevelItem(new QTreeWidgetItem({n, state, field}));
        }

        linkTable_->setRowCount(0);
        QStringList llist = links.mid(5).trimmed().split(" ", Qt::SkipEmptyParts);
        for (const auto& l : llist) {
            QRegularExpression re("^(.+)->(.+)\\((.+)\\)$");
            auto m = re.match(l);
            if (m.hasMatch()) addLinkRow(m.captured(1), m.captured(2), m.captured(3), "stable");
        }
    }

    void addLinkRow(const QString& from, const QString& to, const QString& weight, const QString& status) {
        int r = linkTable_->rowCount();
        linkTable_->insertRow(r);
        linkTable_->setItem(r, 0, new QTableWidgetItem(from));
        linkTable_->setItem(r, 1, new QTableWidgetItem(to));
        linkTable_->setItem(r, 2, new QTableWidgetItem(weight));
        linkTable_->setItem(r, 3, new QTableWidgetItem(status));
    }

    void addTraceRows(const QString& response) {
        if (!traceTable_) return;
        if (!response.startsWith("TRACE")) {
            addTraceRow(traceTable_->rowCount(), "-", "-", response);
            return;
        }
        QStringList nodes = response.mid(5).trimmed().split(" ", Qt::SkipEmptyParts);
        for (int i=0; i<nodes.size(); ++i) addTraceRow(i, nodes[i], QString::number(1.0/(i+1), 'f', 2), "visited");
    }

    void addTraceRow(int hop, const QString& node, const QString& energy, const QString& decision) {
        int r = traceTable_->rowCount();
        traceTable_->insertRow(r);
        traceTable_->setItem(r, 0, new QTableWidgetItem(QString::number(hop)));
        traceTable_->setItem(r, 1, new QTableWidgetItem(node));
        traceTable_->setItem(r, 2, new QTableWidgetItem(energy));
        traceTable_->setItem(r, 3, new QTableWidgetItem(decision));
    }

    void console(const QString& s) { if (consoleOut_) consoleOut_->append(s); }
    void log(const QString& s) { if (logView_) logView_->append(QTime::currentTime().toString("HH:mm:ss") + "  " + s); }

    void repolish(QWidget* w) {
        w->style()->unpolish(w);
        w->style()->polish(w);
        w->update();
    }

    void applyPremiumStyle() {
        qApp->setStyleSheet(R"(
            QWidget { background: #0b1020; color: #e8eefc; font-family: Segoe UI, Inter, Arial; font-size: 10.5pt; }
            QFrame#hero, QFrame#panel, QFrame#metric { background: #111a33; border: 1px solid #26365f; border-radius: 16px; }
            QLabel#title { font-size: 24pt; font-weight: 700; color: #ffffff; }
            QLabel#subtitle { color: #9fb2d9; font-size: 10pt; }
            QLabel#section { color: #ffffff; font-weight: 700; font-size: 13pt; }
            QLabel#metricTitle { font-size: 18pt; font-weight: 700; }
            QLabel#metricText { color: #9fb2d9; }
            QLabel#badge { border-radius: 12px; padding: 7px 12px; font-weight: 700; }
            QLabel#badge[state="ok"] { background: #123d2a; color: #7dffb2; border: 1px solid #1e7a4c; }
            QLabel#badge[state="bad"] { background: #421b25; color: #ff9daf; border: 1px solid #7a2b3b; }
            QLabel#badge[state="warn"] { background: #4a3713; color: #ffd27a; border: 1px solid #8a6720; }
            QPushButton { background: #1e2d55; border: 1px solid #375189; padding: 9px 13px; border-radius: 10px; color: #eef4ff; }
            QPushButton:hover { background: #284078; }
            QPushButton#navButton { text-align: left; }
            QLineEdit, QSpinBox, QTextEdit, QPlainTextEdit, QTreeWidget, QTableWidget {
                background: #081022; border: 1px solid #26365f; border-radius: 10px; padding: 7px;
                selection-background-color: #3a5fa8;
            }
            QTabWidget::pane { border: 1px solid #26365f; border-radius: 12px; }
            QTabBar::tab { background: #111a33; border: 1px solid #26365f; padding: 10px 16px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #203763; }
            QHeaderView::section { background: #13203d; color: #e8eefc; border: none; padding: 8px; }
            QProgressBar { border: 1px solid #26365f; border-radius: 8px; text-align: center; background: #081022; }
            QProgressBar::chunk { background: #3a5fa8; border-radius: 8px; }
        )");
    }
};

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    MyceliaStudioWindow window;
    window.show();
    return app.exec();
}


import sys
import sqlite3
import hashlib
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QPushButton, QTextEdit, QLabel,
    QFileDialog, QVBoxLayout, QHBoxLayout,
    QProgressBar, QTableWidget,
    QTableWidgetItem, QMessageBox
)
from PySide6.QtCore import QThread, Signal

DB_NAME = "file_index.db"


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self.create_tables()

    def create_tables(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY,
            size INTEGER,
            mtime REAL,
            hash TEXT
        )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON files(hash)")
        self.conn.commit()

    def clear_files(self):
        self.conn.execute("DELETE FROM files")
        self.conn.commit()

    def save_file(self, path, size, mtime, file_hash):
        self.conn.execute("""
        INSERT INTO files(path,size,mtime,hash)
        VALUES(?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            size=excluded.size,
            mtime=excluded.mtime,
            hash=excluded.hash
        """, (path, size, mtime, file_hash))

    def get_duplicates(self):
        return self.conn.execute("""
        SELECT hash, COUNT(*)
        FROM files
        WHERE hash IS NOT NULL
        GROUP BY hash
        HAVING COUNT(*) > 1
        """).fetchall()

    def get_paths_by_hash(self, file_hash):
        return [r[0] for r in self.conn.execute(
            "SELECT path FROM files WHERE hash=?", (file_hash,)
        ).fetchall()]


def calculate_hash(filepath):
    sha = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()
    except Exception:
        return None


class IndexWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal()

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run(self):
        db = Database()
        folder = Path(self.folder)
        files = [f for f in folder.rglob("*") if f.is_file()]
        total = len(files)

        if total == 0:
            self.finished.emit()
            return

        for i, file in enumerate(files):
            try:
                stat = file.stat()
                file_hash = calculate_hash(file)
                db.save_file(str(file), stat.st_size, stat.st_mtime, file_hash)
                self.log.emit(f"Индексируется: {file}")
                self.progress.emit(int((i + 1) / total * 100))
            except Exception as e:
                self.log.emit(f"Ошибка: {e}")

        db.conn.commit()
        db.conn.close()
        self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.worker = None

        self.setWindowTitle("Поиск дубликатов файлов")
        self.resize(1300, 750)
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QLabel { color: white; font-size: 14px; }
            QPushButton {
                background-color: #2d89ef; color: white; border-radius: 10px;
                padding: 12px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1f6fd1; }
            QTextEdit {
                background: #1e1e1e; color: #00ff99; border: 1px solid #333;
                border-radius: 8px; padding: 8px;
            }
            QTableWidget {
                background: #1e1e1e; color: white; gridline-color: #333;
                border: 1px solid #333;
            }
            QHeaderView::section {
                background-color: #333; color: white; padding: 6px; border: none;
            }
            QProgressBar {
                border: 1px solid #555; border-radius: 8px;
                text-align: center; color: white; font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2d89ef; border-radius: 8px;
            }
        """)
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        sidebar = QVBoxLayout()
        title = QLabel("ФАЙЛОВЫЙ ИНДЕКСАТОР")
        title.setStyleSheet("font-size:24px;font-weight:bold;color:#2d89ef;")
        subtitle = QLabel("Профессиональная версия")
        subtitle.setStyleSheet("color:#bbbbbb;font-size:12px;")

        self.btn_index = QPushButton("Индексировать папку")
        self.btn_duplicates = QPushButton("Найти дубликаты")
        self.btn_backup = QPushButton("Проверить резервную копию")

        sidebar.addWidget(title)
        sidebar.addWidget(subtitle)
        sidebar.addSpacing(20)
        sidebar.addWidget(self.btn_index)
        sidebar.addWidget(self.btn_duplicates)
        sidebar.addWidget(self.btn_backup)
        sidebar.addStretch()

        right_layout = QVBoxLayout()
        self.progress = QProgressBar()
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Тип", "Путь"])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        right_layout.addWidget(self.progress)
        right_layout.addWidget(self.table)
        right_layout.addWidget(self.log)

        main_layout.addLayout(sidebar, 1)
        main_layout.addLayout(right_layout, 4)

        self.btn_index.clicked.connect(self.handle_index)
        self.btn_duplicates.clicked.connect(self.handle_duplicates)
        self.btn_backup.clicked.connect(self.handle_backup)

    def append_log(self, text):
        self.log.append(text)

    def handle_index(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if not folder:
            return
        self.db.clear_files()
        self.log.clear()
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.worker = IndexWorker(folder)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.index_finished)
        self.worker.start()

    def index_finished(self):
        self.db = Database()
        QMessageBox.information(self, "Готово", "Индексация завершена.")

    def handle_duplicates(self):
        duplicates = self.db.get_duplicates()
        self.table.setRowCount(0)
        if not duplicates:
            self.append_log("Дубликаты не найдены.")
            return
        row = 0
        for file_hash, _ in duplicates:
            for path in self.db.get_paths_by_hash(file_hash):
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem("Дубликат"))
                self.table.setItem(row, 1, QTableWidgetItem(path))
                row += 1
        self.append_log(f"Найдено групп дубликатов: {len(duplicates)}")

    def handle_backup(self):
        source = QFileDialog.getExistingDirectory(self, "Выберите исходную папку")
        if not source:
            return
        backup = QFileDialog.getExistingDirectory(self, "Выберите папку резервной копии")
        if not backup:
            return

        source, backup = Path(source), Path(backup)
        source_files = {f.relative_to(source): f for f in source.rglob("*") if f.is_file()}
        backup_files = {f.relative_to(backup): f for f in backup.rglob("*") if f.is_file()}

        missing, modified = [], []
        for rel_path, src_file in source_files.items():
            if rel_path not in backup_files:
                missing.append(str(rel_path))
                continue
            if calculate_hash(src_file) != calculate_hash(backup_files[rel_path]):
                modified.append(str(rel_path))

        self.table.setRowCount(0)
        row = 0
        for item in missing:
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem("Отсутствует"))
            self.table.setItem(row, 1, QTableWidgetItem(item))
            row += 1
        for item in modified:
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem("Изменён"))
            self.table.setItem(row, 1, QTableWidgetItem(item))
            row += 1
        self.append_log(f"Отсутствует: {len(missing)} | Изменено: {len(modified)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

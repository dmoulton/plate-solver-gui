from re import I
import sys
import os
import shutil
import glob
from typing import Optional
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QMessageBox,
    QPushButton, QLabel, QFileDialog, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QSizePolicy, QTabWidget, QHeaderView, QAction
)
from PyQt5.QtCore import Qt, QProcess, QTimer, QCoreApplication
from PyQt5.QtGui import QImage, QPixmap
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

VERSION = '1.01'
NAME = "Plate Solver"
COPYRIGHT_YEAR = "2025"
AUTHOR = "David Moulton"

SOLVE_FIELD = 'solve-field'
WINDOW_WIDTH = 750
WINDOW_HEIGHT = 700

COMMON_PATHS = [
    "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin",
    os.path.expanduser("~/.local/bin"),
    os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin"),
    os.path.expanduser("~/home/linuxbrew/.linuxbrew/bin"),
    r"C:\\Python39\\Scripts",
    r"C:\\Users\\%USERNAME%\\AppData\\Local\\Programs\\Python\\Python39\\Scripts",
    r"C:\\Users\\%USERNAME%\\anaconda3\\Scripts",
    r"C:\\ProgramData\\chocolatey\\bin",
    r"C:\\Program Files\\AstrometryNet\\bin",
]

def prepend_common_paths():
    old_path = os.environ.get("PATH", "")
    path_dirs = old_path.split(os.pathsep)
    for p in COMMON_PATHS:
        if p and os.path.isdir(p) and p not in path_dirs:
            path_dirs.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(path_dirs)

def image_to_pixmap(path):
    suffix = os.path.splitext(path)[1].lower()
    if suffix in ('.fits', '.fit', '.fts'):
        with fits.open(path) as hdul:
            data = hdul[0].data.astype(np.float32)
        data = np.squeeze(data)
        if data.ndim > 2:
            data = data[0]
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
        lo, hi = np.percentile(data, (1, 99))
        scaled = np.clip((data - lo) / (hi - lo), 0, 1)
        img8 = (scaled * 255).astype(np.uint8)
        h, w = img8.shape
        qimg = QImage(img8.data, w, h, img8.strides[0], QImage.Format_Grayscale8)
        return QPixmap.fromImage(qimg)
    elif suffix in ('.tif', '.tiff'):
        try:
            pil_img = Image.open(path)
            gray = pil_img.convert('L')
            w, h = gray.size
            data = gray.tobytes()
            qimg = QImage(data, w, h, w, QImage.Format_Grayscale8)
            return QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"Error loading image: {e}")
            return QPixmap()
    else:
        pix = QPixmap(path)
        if pix.isNull():
            raise ValueError(f"Could not load image: {path}")
        return pix

class PlateSolveApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_menu()
        self.init_window()

        self.filename = None
        self.proc: Optional[QProcess] = None
        self.temp_dir = os.path.expanduser('~/tmp/platesolver')

    def init_menu(self):
        menubar = self.menuBar()
        app_menu = menubar.addMenu("PlateSolver")
        about_action = QAction("About PlateSolver", self)
        about_action.triggered.connect(self.show_about)
        app_menu.addAction(about_action)

    def init_window(self):
        self.original_pixmap = None
        self.setWindowTitle('PlateSolver')
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.init_controls(layout)
        self.init_solved_table(layout)
        
        self.init_tabs(layout)
        self.init_abort(layout)

    def init_solved_table(self, layout):
        self.solved_table = QTableWidget(2, 4)
        self.solved_table.setFixedHeight(70)
        self.solved_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        header = self.solved_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        self.solved_table.verticalHeader().setVisible(False)
        self.solved_table.horizontalHeader().setVisible(False)
        self.solved_table.setShowGrid(False)

        # Set labels and default placeholders
        center_item = QTableWidgetItem('Center (RA, Dec)')
        center_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 0, center_item)
        self.solved_table.setItem(0, 1, QTableWidgetItem('--'))

        rotation_item = QTableWidgetItem('Rotation')
        rotation_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(1, 0, rotation_item)
        self.solved_table.setItem(1, 1, QTableWidgetItem('--'))

        resolution_item = QTableWidgetItem('Pixel Scale')
        resolution_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 2, resolution_item)
        self.solved_table.setItem(0, 3, QTableWidgetItem('--'))

        # Row 1, cols 2 and 3: empty placeholders
        self.solved_table.setItem(1, 2, QTableWidgetItem(' '))
        self.solved_table.setItem(1, 3, QTableWidgetItem(' '))

        layout.addWidget(self.solved_table)

    def init_controls(self, layout):
        btn_layout = QHBoxLayout()

        self.open_btn = QPushButton('Open Image/File')
        self.open_btn.clicked.connect(self.open_file)
        btn_layout.addWidget(self.open_btn, alignment=Qt.AlignLeft)
        btn_layout.addStretch()

        btn_layout.addWidget(QLabel('Pixel Scale (arcsec/pixel):'))
        self.res_input = QLineEdit('')
        self.res_input.setFixedWidth(50)
        btn_layout.addWidget(self.res_input)

        clear_btn = QPushButton('Clear')
        clear_btn.setFixedWidth(55)
        clear_btn.clicked.connect(lambda: self.res_input.clear())
        btn_layout.addWidget(clear_btn)
        btn_layout.addStretch()

        self.annotate_cb = QCheckBox("Annotate (slower)")
        self.annotate_cb.setChecked(False)
        btn_layout.addWidget(self.annotate_cb)
        btn_layout.addStretch()

        self.solve_btn = QPushButton('Solve Image')
        self.solve_btn.clicked.connect(self.solve_field)
        self.solve_btn.setEnabled(False)
        btn_layout.addWidget(self.solve_btn, alignment=Qt.AlignRight)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def init_tabs(self, layout):
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)

        self.image_label = QLabel('No image loaded')
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)
        image_layout.addWidget(self.image_label)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.addWidget(self.output_text)

        self.tab_widget.addTab(image_tab, "Image")
        self.tab_widget.addTab(log_tab, "Log")

        layout.addWidget(self.tab_widget)

    def init_abort(self, layout):
        abort_layout = QHBoxLayout()
        self.abort_btn = QPushButton('Abort')
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self.abort_solve)
        abort_layout.addStretch()
        abort_layout.addWidget(self.abort_btn)
        layout.addLayout(abort_layout)

    def show_about(self):
        QMessageBox.about(self, "About PlateSolver", 
                        f"{NAME} v{VERSION}\n\n"\
                        "A simple GUI for plate solving with Astrometry.net\n\n"\
                        f"© {COPYRIGHT_YEAR} {AUTHOR}\n\n"\
                        "https://github.com/dmoulton/plate-solver-gui")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select image or FITS', os.path.expanduser('~/Pictures'),
            'Supported Files (*.fits *.fz *.jpg *.jpeg *.png *.tiff *.tif);;All Files (*)')
        if not path:
            return
        self.filename = path
        self.solve_btn.setEnabled(True)
        self.output_text.clear()
        for row in range(self.solved_table.rowCount()):
            self.solved_table.item(row, 1).setText('')
            self.solved_table.item(row, 3).setText('')
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.fits', '.fit', '.tif', '.tiff']:
            pix = image_to_pixmap(path)
            self.original_pixmap = pix
            self._resize_image_to_fit()
        else:
            self.image_label.setText(f'Loaded file: {os.path.basename(path)}')

    def solve_field(self):
        if not self.filename:
            return
        prepend_common_paths()
        brew_prefix = '/opt/homebrew/bin' if os.path.isdir('/opt/homebrew/bin') else '/usr/local/bin'
        os.environ['PATH'] = brew_prefix + os.pathsep + os.environ.get('PATH', '')
        self.abort_btn.setEnabled(True)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.makedirs(self.temp_dir)
        try:
            res = float(self.res_input.text())
            low, high = max(res-0.2,0.0), res+0.2
        except ValueError:
            res, low, high = 0.0, 0.4, 2.2
        self.solve_btn.setEnabled(False)
        self.output_text.append(f'\n⏳ Solving: {self.filename} (scale {res:.2f}±0.20")')
        self.proc = QProcess(self)
        env = self.proc.processEnvironment()
        env.insert('PATH', os.environ.get('PATH',''))
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(lambda c,s: self._on_finished(c,s,res))
        args = [
            '--overwrite','--scale-units','arcsecperpix','--scale-low',f'{low:.3f}',
            '--scale-high',f'{high:.3f}','--downsample','2','--plot-scale','0.25',
            '--dir',self.temp_dir,self.filename
        ]
        if not self.annotate_cb.isChecked():
            args.append('--no-plots')
        self.proc.start(SOLVE_FIELD, args)


    def _on_stdout(self):
        self.tab_widget.setCurrentIndex(1)  # Switch to Log tab
        self.output_text.append(bytes(self.proc.readAllStandardOutput()).decode())

    def _on_stderr(self):
        self.tab_widget.setCurrentIndex(1)  # Switch to Log tab
        self.output_text.append(f'<span style="color:red;">{bytes(self.proc.readAllStandardError()).decode()}</span>')

    def _on_finished(self, exitCode, exitStatus, res):
        self.solve_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        base = os.path.splitext(os.path.basename(self.filename))[0]
        candidates = glob.glob(os.path.join(self.temp_dir,f'{base}.new*'))
        if not candidates:
            self.solved_table.item(0,1).setText('Not found')
            self.solved_table.item(1,1).setText('Not found')
        else:
            try:
                hdr = fits.getheader(candidates[0])
                wcs = WCS(hdr)
                ra,dec = hdr.get('CRVAL1'),hdr.get('CRVAL2')
                self.solved_table.item(0,1).setText(f'{ra:.6f}°, {dec:.6f}°')
                cd = wcs.wcs.cd
                rot = f'{(180/np.pi)*np.arctan2(cd[0,1],cd[1,1])%360:.2f}°' if cd is not None else 'Unknown'
                self.solved_table.item(1,1).setText(rot)
                actual_res = np.sqrt(abs(np.linalg.det(cd)))*3600 if cd is not None else res
                
                self.solved_table.item(0,3).setText(f'{actual_res:.2f}"')
            except Exception:
                self.solved_table.item(0,1).setText('Error')
                self.solved_table.item(1,1).setText('Error')
                self.solved_table.item(0,3).setText('Error')
        self.output_text.append('✅ Plate solve complete')
        annotated_path = os.path.join(self.temp_dir, f"{base}-ngc.png")
        if os.path.exists(annotated_path):
            pix = QPixmap(annotated_path)
            self.original_pixmap = pix
            self._resize_image_to_fit()
        else:
            self.output_text.append('No Annotations')
        try: shutil.rmtree(self.temp_dir)
        except: pass

    def abort_solve(self, checked: bool = False):
        if not (self.proc and self.proc.state() == QProcess.Running):
            return
        self.abort_btn.setEnabled(False)
        self.solve_btn.setEnabled(True)
        self.output_text.append('❌ Aborting solve…')
        self.proc.finished.disconnect()
        QTimer.singleShot(0, self.proc.terminate)
        QTimer.singleShot(1000, self._force_kill)

    def _force_kill(self):
        self.abort_btn.setEnabled(False)
        if self.proc and self.proc.state() == QProcess.Running:
            self.output_text.append('⚠️ Still running—force killing now.')
            QTimer.singleShot(0, self.proc.kill)

    def closeEvent(self, event):
        if self.proc and self.proc.state() == QProcess.Running:
            self.abort_solve()
            QCoreApplication.processEvents()
        event.accept()

    def _resize_image_to_fit(self):
        if self.original_pixmap:
            area_size = self.image_label.size()
            scaled_pix = self.original_pixmap.scaled(
                area_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pix)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_image_to_fit()

if __name__=='__main__':
    app = QApplication(sys.argv)
    window = PlateSolveApp()
    window.show()
    sys.exit(app.exec_())

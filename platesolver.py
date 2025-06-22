from re import I
import sys
import os
import shutil
import glob
from typing import Optional
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,QCheckBox,
    QPushButton, QLabel, QFileDialog, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QProcess, QTimer, QCoreApplication
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QHeaderView
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

# Always use system-installed solve-field
SOLVE_FIELD = 'solve-field'

COMMON_PATHS = [
    # standard UNIX
    "/usr/bin",
    "/usr/local/bin",

    # macOS Homebrew (Intel)
    "/usr/local/bin",
    # macOS Homebrew (Apple Silicon)
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",

    # user‐local installs
    os.path.expanduser("~/.local/bin"),

    # conda
    os.path.join(os.environ.get("CONDA_PREFIX", ""), "bin"),

    # Linuxbrew (if you ever use it on Linux)
    os.path.expanduser("~/home/linuxbrew/.linuxbrew/bin"),

    # Windows
    r"C:\Python39\Scripts",
    r"C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python39\Scripts",
    r"C:\Users\%USERNAME%\anaconda3\Scripts",
    r"C:\ProgramData\chocolatey\bin",
    r"C:\Program Files\AstrometryNet\bin",
]

IMAGE_WIDTH = 600
WINDOW_WIDTH = 750
WINDOW_HEIGHT = 700

def prepend_common_paths():
    # grab existing PATH, split into a list
    old_path = os.environ.get("PATH", "")
    path_dirs = old_path.split(os.pathsep)

    # for each common path, if it exists on disk and isn't already in PATH, prepend it
    for p in COMMON_PATHS:
        if p and os.path.isdir(p) and p not in path_dirs:
            path_dirs.insert(0, p)

    # write it back
    os.environ["PATH"] = os.pathsep.join(path_dirs)
def image_to_pixmap(path):
    """
    Load a FITS or TIFF (or any Qt-supported format) from `path`, convert to
    an 8-bit image, and return a QPixmap.
    """
    suffix = os.path.splitext(path)[1].lower()

    if suffix in ('.fits', '.fit', '.fts'):
        # --- same as before: FITS → numpy → auto-stretch → QPixmap
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
            gray = pil_img.convert('L')  # Convert to 8-bit grayscale
            w, h = gray.size
            data = gray.tobytes()
            qimg = QImage(data, w, h, w, QImage.Format_Grayscale8)
            return QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"Error loading image: {e}")
            return QPixmap()  # empty pixmap as fallback

    else:
        # fallback: let Qt try
        pix = QPixmap(path)
        if pix.isNull():
            raise ValueError(f"Could not load image: {path}")
        return pix

class PlateSolveApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PlateSolver')
        self.resize(750, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Create solved info table (no borders)
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

        # Solved information table
        center_item = QTableWidgetItem('Center (RA, Dec)')
        center_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 0, center_item)
        center_val = QTableWidgetItem('--')
        center_val.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 1, center_val)

        rotation_item = QTableWidgetItem('Rotation')
        rotation_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(1, 0, rotation_item)
        rotation_val = QTableWidgetItem('--')
        rotation_val.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(1, 1, rotation_val)

        resolution_item = QTableWidgetItem('Pixel Scale')
        resolution_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 2, resolution_item)
        resolution_val = QTableWidgetItem('--')
        resolution_val.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(0, 3, resolution_val)

        placeholder_item = QTableWidgetItem(' ')
        placeholder_item.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(1, 2, placeholder_item)
        placeholder_val = QTableWidgetItem(' ')
        placeholder_val.setFlags(Qt.ItemIsEnabled)
        self.solved_table.setItem(1, 3, placeholder_val)

        # Top row
        btn_layout = QHBoxLayout()
        self.open_btn = QPushButton('Open Image/File')
        self.open_btn.clicked.connect(self.open_file)
        btn_layout.addWidget(self.open_btn, alignment=Qt.AlignLeft)
        btn_layout.addStretch()

        btn_layout.addWidget(QLabel('Pixel Scale (arcsec/pixel):'))
        self.res_input = QLineEdit('')
        self.res_input.setFixedWidth(50)
        self.res_input.setToolTip("Approximate pixel scale in arcseconds/pixel\n(e.g. 1.0 for 1.0″/px)\nLeave empty if unknown")
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

        # Solved image info
        layout.addWidget(self.solved_table)

        # Image display
        self.image_label = QLabel('No image loaded')
        self.image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image_label)

        # Output log
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFixedHeight(200)
        layout.addWidget(self.output_text)

        # Abort button below log
        abort_layout = QHBoxLayout()
        self.abort_btn = QPushButton('Abort')
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self.abort_solve)
        abort_layout.addStretch()
        abort_layout.addWidget(self.abort_btn)
        layout.addLayout(abort_layout)

        # Internal state
        self.filename = None
        self.proc: Optional[QProcess] = None
        self.temp_dir = os.path.expanduser('~/tmp/platesolver')

    def open_file(self):
        start_dir = os.path.expanduser('~/Pictures')
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select image or FITS', start_dir,
            'Supported Files (*.fits *.fz *.jpg *.jpeg *.png *.tiff *.tif);;All Files (*)'
        )
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
            if pix.width() > IMAGE_WIDTH:
                pix = pix.scaledToWidth(IMAGE_WIDTH, Qt.SmoothTransformation)
            self.image_label.setPixmap(pix)
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
        self.output_text.append(f'⏳ Solving: {self.filename} (scale {res:.2f}±0.20")')

        self.proc = QProcess(self)
        env = self.proc.processEnvironment()
        # ensure system PATH is used
        env.insert('PATH', os.environ.get('PATH',''))
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._on_stdout)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(lambda c,s: self._on_finished(c,s,res))

        args = [
            '--overwrite',
            '--scale-units','arcsecperpix',
            '--scale-low',f'{low:.3f}',
            '--scale-high',f'{high:.3f}',
            '--downsample','2',
            '--plot-scale','0.25',
            '--dir',self.temp_dir,
            self.filename
        ]
        if not self.annotate_cb.isChecked():
            args.append('--no-plots')

        self.proc.start(SOLVE_FIELD, args)

    def _on_stdout(self):
        self.output_text.append(bytes(self.proc.readAllStandardOutput()).decode())

    def _on_stderr(self):
        self.output_text.append(f'<span style="color:red;">{bytes(self.proc.readAllStandardError()).decode()}</span>')

    def _on_finished(self, exitCode, exitStatus, res):
        self.solve_btn.setEnabled(True)
        base = os.path.splitext(os.path.basename(self.filename))[0]
        candidates = glob.glob(os.path.join(self.temp_dir,f'{base}.new*'))
        if not candidates:
            self.solved_table.item(0,1).setText('Not found')
            self.solved_table.item(1,1).setText('Not found')
            # self.solved_table.item(2,1).setText(f'{res:.2f}"')
        else:
            try:
                hdr = fits.getheader(candidates[0])
                wcs = WCS(hdr)
                ra,dec = hdr.get('CRVAL1'),hdr.get('CRVAL2')
                self.solved_table.item(0,1).setText(f'{ra:.6f}°, {dec:.6f}°')
                cd = wcs.wcs.cd
                rot = f'{(180/np.pi)*np.arctan2(cd[0,1],cd[1,1])%360:.2f}°' if cd is not None else 'Unknown'
                self.solved_table.item(1,1).setText(rot)
                if cd is not None:
                    actual_res = np.sqrt(abs(np.linalg.det(cd)))*3600
                    self.solved_table.item(0,3).setText(f'{actual_res:.2f}"')
                else:
                    self.solved_table.item(0,3).setText(f'{res:.2f}"')
            except Exception:
                self.solved_table.item(0,1).setText('Error')
                self.solved_table.item(1,1).setText('Error')
                self.solved_table.item(0,3).setText(f'{res:.2f}"')
        self.output_text.append('✅ Plate solve complete')

        base = os.path.splitext(os.path.basename(self.filename))[0]
        annotated_path = os.path.join(self.temp_dir, f"{base}-ngc.png")
        if os.path.exists(annotated_path):
            pix = QPixmap(annotated_path)
            if pix.width() > IMAGE_WIDTH:
                pix = pix.scaledToWidth(IMAGE_WIDTH, Qt.SmoothTransformation)
            self.image_label.setPixmap(pix)
        else:
            self.output_text.append('No Annotations')

        try: shutil.rmtree(self.temp_dir)
        except: pass


    def abort_solve(self, checked: bool = False):
        if not (self.proc and self.proc.state() == QProcess.Running):
            return

        self.abort_btn.setEnabled(True)
        self.output_text.append('❌ Aborting solve…')

        # politely ask, then force-kill later if needed
        self.proc.finished.disconnect()
        QTimer.singleShot(0, self.proc.terminate)
        QTimer.singleShot(1000, self._force_kill)

    def _force_kill(self):
        self.abort_btn.setEnabled(True)
        if self.proc and self.proc.state() == QProcess.Running:
            self.output_text.append('⚠️ Still running—force killing now.')
            # schedule kill after we re-enter the loop
            QTimer.singleShot(0, self.proc.kill)


    def closeEvent(self, event):
        if self.proc and self.proc.state() == QProcess.Running:
            self.abort_solve()
            # give the process a moment to die
            QCoreApplication.processEvents()
        event.accept()

if __name__=='__main__':
    app = QApplication(sys.argv)
    window = PlateSolveApp()
    window.show()
    sys.exit(app.exec_())

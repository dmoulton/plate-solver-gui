import sys
import os
import shutil
import glob
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QSizePolicy
)
from PyQt5.QtCore import Qt, QProcess
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QHeaderView
from astropy.io import fits
from astropy.wcs import WCS

# Always use system-installed solve-field
SOLVE_FIELD = 'solve-field'

class PlateSolveApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PlateSolver')
        self.resize(800, 700)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Create solved info table (no borders)
        self.solved_table = QTableWidget(3, 2)
        self.solved_table.setFixedHeight(110)
        self.solved_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header = self.solved_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.solved_table.verticalHeader().setVisible(False)
        self.solved_table.horizontalHeader().setVisible(False)
        self.solved_table.setShowGrid(False)
        fields = ['Center (RA, Dec)', 'Rotation', 'Resolution']
        for row, field in enumerate(fields):
            item = QTableWidgetItem(field)
            item.setFlags(Qt.ItemIsEnabled)
            self.solved_table.setItem(row, 0, item)
            val = QTableWidgetItem('--')
            val.setFlags(Qt.ItemIsEnabled)
            self.solved_table.setItem(row, 1, val)

        # Top buttons row
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

        self.solve_btn = QPushButton('Solve Image')
        self.solve_btn.clicked.connect(self.solve_field)
        self.solve_btn.setEnabled(False)
        btn_layout.addWidget(self.solve_btn, alignment=Qt.AlignRight)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Resolution and solved info row
        info_layout = QHBoxLayout()

        info_layout.addWidget(self.solved_table)
        layout.addLayout(info_layout)

        # Image display
        self.image_label = QLabel('No image loaded')
        self.image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image_label)

        # Output log
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFixedHeight(260)
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
        self.proc = None
        self.temp_dir = os.path.expanduser('~/tmp/platesolver')

    def resizeEvent(self, event):
        target_width = int(self.width() * 0.6)
        self.solved_table.setFixedWidth(target_width)
        super().resizeEvent(event)

    def open_file(self):
        start_dir = os.path.expanduser('~/Pictures')
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select image or FITS', start_dir,
            'Supported Files (*.fits *.fz *.jpg *.jpeg *.png);;All Files (*)'
        )
        if not path:
            return
        self.filename = path
        self.solve_btn.setEnabled(True)
        self.output_text.clear()
        for row in range(self.solved_table.rowCount()):
            self.solved_table.item(row, 1).setText('--')

        ext = os.path.splitext(path)[1].lower()
        if ext in ['.jpg', '.jpeg', '.png']:
            pix = QPixmap(path)
            if pix.width() > 700:
                pix = pix.scaledToWidth(700, Qt.SmoothTransformation)
            self.image_label.setPixmap(pix)
        else:
            self.image_label.setText(f'Loaded file: {os.path.basename(path)}')

    def solve_field(self):
        if not self.filename:
            return

        brew_prefix = '/opt/homebrew/bin' if os.path.isdir('/opt/homebrew/bin') else '/usr/local/bin'
        os.environ['PATH'] = brew_prefix + os.pathsep + os.environ.get('PATH', '')

        self.abort_btn.setEnabled(True)
        if os.path.exists(self.temp_dir): shutil.rmtree(self.temp_dir)
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
            '--no-plots',
            '--dir',self.temp_dir,
            self.filename
        ]
        self.proc.start(SOLVE_FIELD, args)

    def _on_stdout(self):
        self.output_text.append(bytes(self.proc.readAllStandardOutput()).decode())

    def _on_stderr(self):
        self.output_text.append(f'<span style="color:red;">{bytes(self.proc.readAllStandardError()).decode()}</span>')

    def _on_finished(self, exitCode, exitStatus, res):
        self.solve_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        base = os.path.splitext(os.path.basename(self.filename))[0]
        candidates = glob.glob(os.path.join(self.temp_dir,f'{base}.new*'))
        if not candidates:
            self.solved_table.item(0,1).setText('Not found')
            self.solved_table.item(1,1).setText('Not found')
            self.solved_table.item(2,1).setText(f'{res:.2f}"')
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
                    self.solved_table.item(2,1).setText(f'{actual_res:.2f}"')
                else:
                    self.solved_table.item(2,1).setText(f'{res:.2f}"')
            except:
                self.solved_table.item(0,1).setText('Error')
                self.solved_table.item(1,1).setText('Error')
                self.solved_table.item(2,1).setText(f'{res:.2f}"')
        self.output_text.append('✅ Plate solve complete')
        try: shutil.rmtree(self.temp_dir)
        except: pass

    def abort_solve(self):
        if self.proc and self.proc.state()==QProcess.Running:
            self.proc.kill()
            self.output_text.append('❌ Plate solve aborted')
            self.solve_btn.setEnabled(True)
            self.abort_btn.setEnabled(False)

if __name__=='__main__':
    app = QApplication(sys.argv)
    window = PlateSolveApp()
    window.show()
    sys.exit(app.exec_())

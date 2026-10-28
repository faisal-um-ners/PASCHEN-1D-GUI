"""GUI entry point:  ``python -m paschen_studio gui``  or  ``paschen-studio``."""
from __future__ import annotations

import os
import sys


def _check_qt():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print("PySide6 is required for the graphical interface.\n"
              "Install it with:   python -m pip install PySide6\n"
              "(or reinstall the studio:  python -m pip install -e studio)")
        return False
    return True


def setup_application(argv=None, theme_name: str | None = None):
    """Create (or reuse) the QApplication with fonts, palette and style sheet."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import QCoreApplication, QSettings, Qt
    from PySide6.QtGui import QFont, QGuiApplication
    from PySide6.QtWidgets import QApplication

    from .. import APP_NAME, APP_ORG
    from . import icons
    from . import theme as T

    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    QCoreApplication.setOrganizationName(APP_ORG)
    QCoreApplication.setApplicationName(APP_NAME)
    app = QApplication.instance() or QApplication(list(argv or sys.argv))
    app.setStyle("Fusion")
    app.setWindowIcon(icons.app_icon())
    f = QFont()
    families = ["Inter", "SF Pro Text", ".AppleSystemUIFont", "Segoe UI", "Helvetica Neue", "Noto Sans",
                "Ubuntu", "Cantarell", "DejaVu Sans", "Arial"]
    try:
        f.setFamilies(families)
    except AttributeError:  # pragma: no cover
        f.setFamily(families[0])
    base = 10.0 if sys.platform != "darwin" else 13.0
    f.setPointSizeF(base)
    app.setFont(f)
    s = QSettings()
    name = theme_name or s.value("theme", "light") or "light"
    apply_theme(app, name)
    return app


def apply_theme(app, name: str):
    from PySide6.QtGui import QColor, QPalette

    from . import icons
    from . import theme as T

    t = T.set_current(name)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["surface2"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(t["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["text3"]))
    pal.setColor(QPalette.Link, QColor(t["accent"]))
    app.setPalette(pal)
    base_pt = app.font().pointSizeF()
    qss = (T.stylesheet(name, base_pt)
           .replace("url(:/chk)", f'url("{icons.check_icon_file()}")')
           .replace("url(:/chev_down)", f'url("{icons.ui_asset_file("chev_down", t["text2"])}")')
           .replace("url(:/chev_up)", f'url("{icons.ui_asset_file("chev_up", t["text2"])}")')
           .replace("url(:/radio)", f'url("{icons.ui_asset_file("radio_dot", t["accent"])}")'))
    app.setStyleSheet(qss)
    T.apply_matplotlib(name)


def main(path: str | None = None, solver_root: str | None = None) -> int:
    if not _check_qt():
        return 1
    app = setup_application()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from .. import solver as S

    settings = QSettings()
    root = S.find_solver_root(solver_root or settings.value("solver_root", None))
    if root is None:
        QMessageBox.information(None, "PASCHEN-1D Studio",
                                "Please select the PASCHEN-1D folder (the folder that contains paschen_1d.py).")
        d = QFileDialog.getExistingDirectory(None, "Select the PASCHEN-1D folder")
        if not d or not S.is_solver_root(d):
            QMessageBox.critical(None, "PASCHEN-1D Studio", "PASCHEN-1D was not found - the studio will close.")
            return 2
        root = d
    S.set_solver_root(root)
    settings.setValue("solver_root", str(root))

    from .main_window import MainWindow
    w = MainWindow(path)
    w.show()
    return app.exec()


def gui_entry() -> int:
    """Entry point of the ``paschen-studio-gui`` launcher (optional model file argument)."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    return main(args[0] if args else None)


if __name__ == "__main__":
    sys.exit(gui_entry())

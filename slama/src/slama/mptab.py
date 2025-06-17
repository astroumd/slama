import sys
import random
from slama.monitor import MonitorPoint, MonitorPointSubscriber, MonitorPointList, MonitorListUpdater
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QColorConstants
from smax import SmaxRedisClient

cellcolor = {
    "ok": QColorConstants.White,
    "good": QColorConstants.Green,
    "warning": QColorConstants.Yellow,
    "alert": QColorConstants.Red,
}

from pathlib import Path


class CellSubscriber(MonitorPointSubscriber, QTableWidgetItem):
    """Table cell that subscribes to monitor point updates"""

    def __init__(self, mp: MonitorPoint, client: SmaxRedisClient):
        MonitorPointSubscriber.__init__(mp)
        self.setData(str(mp.value))


class Cell(QTableWidgetItem):

    def __init__(self, mp: MonitorPoint):
        self._mp = mp
        self.update()

    def update(self):
        self.setData(str(self._mp.value))
        self.set_validity_color()

    def set_validity_color(self):
        pass


# evantually have a table be a subscriber to a list of monitor points and update any time there is
# a change.  would this block any user interaction though?


class MpTableWidget(QTableWidget):
    """Custom TableWidget to display data with updating cells."""

    def __init__(self, rows: int, columns: int, path: Path):
        super().__init__(rows, columns)
        self._cells = []
        self._path = path
        self._mpl = MonitorListUpdater(MonitorPointList.from_file(path))
        self.setHorizontalHeaderLabels([f"ANT {i+1}" for i in range(columns)])

        # Create and initialize the data generators
        i = 0
        for row in range(rows):
            self.setHorizontalHeaderItem(row, self._mp[i].name)
            for col in range(columns):
                self._cell.append(Cell(self._mp[i]))
                self.setItem(row, col, self._cell[i])
                i += 1

        # Set up a timer to update the table data regularly
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_table)
        self.timer.start(2000)

    def update_table(self):
        """Update the values in the table."""
        self._mpl.update()
        for c in self._cells:
            c.update()


class MainWindow(QMainWindow):
    """Main window to hold the table."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Dynamic Data Table")
        self.setGeometry(100, 100, 800, 400)

        self.table = MpTableWidget(6, 8, "mpdefs.json")  # 6 rows, 8 columns

        layout = QVBoxLayout()
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

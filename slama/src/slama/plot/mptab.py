import sys
import random
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QGridLayout,
    QVBoxLayout,
    QWidget,
    QLabel,
    QLineEdit,
)
from PyQt6.QtGui import QColorConstants, QColor
from smax import SmaxRedisClient
from pathlib import Path

from ..monitor import (
    MonitorPoint,
    MonitorPointSubscriber,
    MonitorPointList,
    MonitorListUpdater,
    Validity,
)


def validity_color(validity: Validity) -> QColor:
    if validity >= Validity.VALID_ERROR_LOW or validity == Validity.VALID_ERROR:
        return QColorConstants.Red
    if validity >= Validity.VALID_WARNING_LOW or validity == Validity.VALID_WARNING:
        return QColorConstants.Yellow
    if validity == Validity.VALID_GOOD:
        return QColorConstants.White  # when Green?
    if validity < Validity.VALID:
        return QColorConstants.Gray
    return QColorConstants.White


class CellSubscriber(MonitorPointSubscriber, QTableWidgetItem):
    """Table cell that subscribes to monitor point updates"""

    def __init__(self, mp: MonitorPoint, client: SmaxRedisClient):
        MonitorPointSubscriber.__init__(mp)
        QTableWidgetItem.__init__()
        self.setData(str(mp.value))


class TextCell(QLabel):
    def __init__(self, mp: MonitorPoint):
        super().__init__()
        # print(f"doing {mp.name}")
        self._mp = mp
        self._defaultss = "border: 1px solid black; padding: 5px;"
        self.setStyleSheet(self._defaultss)
        self.update()

    def update(self):
        self.setText(str(self._mp.value))
        self.set_validity_color()

    def set_validity_color(self):
        vc = validity_color(self._mp.validity)
        # print(f"setting color {vc.name()}")
        self.setBackground(vc)

    def setBackground(self, color: QColor):
        newss = f"{self._defaultss} background-color: {color.name()}"
        self.setStyleSheet(newss)


class TableCell(QTableWidgetItem):

    def __init__(self, mp: MonitorPoint):
        super().__init__()
        # print(f"table doing {mp.name}")
        self._mp = mp
        self.update()

    def update(self):
        self.setData(0, str(self._mp.value))
        self.set_validity_color()

    def set_validity_color(self):
        vc = validity_color(self._mp.validity)
        # print(f"setting color {vc.name()}")
        self.setBackground(vc)


# evantually have a table be a subscriber to a list of monitor points and update any time there is
# a change.  would this block any user interaction though?


class MpTableWidget(QTableWidget):
    """Custom TableWidget to display data with updating cells."""

    def __init__(self, rows: int, columns: int, mpl: MonitorListUpdater, start=0):
        super().__init__(rows, columns)
        self.nrows = rows
        self.ncols = columns
        self._cells = []
        self._mpl = mpl
        self.setHorizontalHeaderLabels([f"ANT {i+1}" for i in range(columns)])

        # Create and initialize the data generators
        i = 0
        hlabels = []
        for row in range(rows):
            name = self._mpl.mplist[i + start].name
            if self._mpl.mplist[i + start].units is not None:
                name += f" ({self._mpl.mplist[i + start].units})"
            hlabels.append(name)
            # self.setHorizontalHeaderLabel(row, self._mpl[i].name)
            for col in range(columns):
                self._cells.append(TableCell(self._mpl.mplist[i + start]))
                self.setItem(row, col, self._cells[i])
                i += 1
        self.setVerticalHeaderLabels(hlabels)

    def update_table(self):
        """Update the values in the table."""
        self._mpl.update()
        print("updating table")
        for c in self._cells:
            c.update()

    def __len__(self):
        return self.nrows * self.ncols


class MpGridWidget(QGridLayout):
    def __init__(self, rows: int, cols: int, mpl: MonitorListUpdater, start=0):
        super().__init__()
        self._mpl = mpl
        self._cells = []
        for i in range(rows * cols):
            self._cells.append(TextCell(self._mpl.mplist[i + start]))
            row = i // rows  # 0 or 1
            col = (i % rows) * 2  # 0, 2, 4, 6

            label = QLabel(self._mpl.mplist[i + start].name)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            textbox = self._cells[i]

            # Add label and textbox side by side
            self.addWidget(label, row, col)
            self.addWidget(textbox, row, col + 1)

        self.setHorizontalSpacing(1)
        self.setContentsMargins(0, 0, 0, 0)


class MainWindow(QMainWindow):
    """Main window to hold the table."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Array Status")
        self.setGeometry(100, 100, 950, 400)

        self._smax_client = SmaxRedisClient("localhost", redis_port=6380)
        self._path = Path("mpdefs.json")
        self._mpl = MonitorListUpdater(MonitorPointList.from_file(self._path), self._smax_client)
        self._mpl.update()
        print(f"{len(self._mpl)=} {len(self._mpl.mplist)=}")
        self.table = MpTableWidget(7, 8, self._mpl, start=0)
        self.grid = MpGridWidget(4, 3, self._mpl, start=len(self.table))
        main_layout = QVBoxLayout()
        main_layout.addLayout(self.grid)
        main_layout.addWidget(self.table)
        # self.setLayout(main_layout)
        container = QWidget()
        container.setLayout(main_layout)

        self.setCentralWidget(container)
        # Set up a timer to update the table data regularly
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(2000)

    def update(self):
        """Update the values in the table."""
        self._mpl.update()
        for c in self.table._cells:
            c.update()
        for c in self.grid._cells:
            c.update()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

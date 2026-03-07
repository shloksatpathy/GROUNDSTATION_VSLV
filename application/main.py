import sys
from PyQt5 import QtWidgets

from user_interface.dashboard import Dashboard


def main():
    app = QtWidgets.QApplication(sys.argv)

    app.setStyleSheet("""
    QMainWindow {
        background-color: #121212;
    }

    QWidget {
        background-color: #121212;
        color: #E0E0E0;
        font-size: 13px;
    }

    QPushButton {
        background-color: #1E1E1E;
        border: 1px solid #333;
        border-radius: 6px;
        padding: 6px;
    }

    QPushButton:hover {
        background-color: #333;
    }

    QComboBox {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 4px;
    }

    QTableWidget {
        background-color: #1E1E1E;
        gridline-color: #444;
    }

    QHeaderView::section {
        background-color: #2C2C2C;
        padding: 4px;
    }
    """)    
    window = Dashboard()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
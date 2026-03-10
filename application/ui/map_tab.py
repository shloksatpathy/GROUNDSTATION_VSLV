from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel


class MapTab(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout()

        layout.addWidget(QLabel("Map will appear here"))

        self.setLayout(layout)
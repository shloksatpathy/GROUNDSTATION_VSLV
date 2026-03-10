from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton


class PacketEditorTab(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout()

        self.editor = QTextEdit()

        self.save_button = QPushButton("Save Packet Format")

        layout.addWidget(self.editor)
        layout.addWidget(self.save_button)

        self.setLayout(layout)
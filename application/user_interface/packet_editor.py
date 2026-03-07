from PyQt5 import QtWidgets
import json


class PacketEditor(QtWidgets.QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Packet Format Editor")
        self.resize(500, 400)

        layout = QtWidgets.QVBoxLayout()

        # table
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Field Name", "Type"])
        self.table.setRowCount(10)

        layout.addWidget(self.table)

        # buttons
        btn_layout = QtWidgets.QHBoxLayout()

        self.add_btn = QtWidgets.QPushButton("Add Row")
        self.remove_btn = QtWidgets.QPushButton("Remove Row")
        self.save_btn = QtWidgets.QPushButton("Save Format")

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)

        self.setLayout(layout)

        # signals
        self.add_btn.clicked.connect(self.add_row)
        self.remove_btn.clicked.connect(self.remove_row)
        self.save_btn.clicked.connect(self.save_format)

    def add_row(self):

        row = self.table.rowCount()
        self.table.insertRow(row)

    def remove_row(self):

        row = self.table.currentRow()

        if row >= 0:
            self.table.removeRow(row)

    def save_format(self):

        fields = []

        for row in range(self.table.rowCount()):

            name_item = self.table.item(row, 0)
            type_item = self.table.item(row, 1)

            if name_item and type_item:

                fields.append({
                    "name": name_item.text(),
                    "type": type_item.text()
                })

        packet_format = {
            "delimiter": ",",
            "fields": fields
        }

        with open("packet_format.json", "w") as f:
            json.dump(packet_format, f, indent=2)

        QtWidgets.QMessageBox.information(self, "Saved", "Packet format saved successfully.")
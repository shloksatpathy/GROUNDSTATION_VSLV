import json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
                             QPushButton, QMessageBox, QLabel)

from core.packet_parser import PacketParser

class PacketEditorTab(QWidget):

    def __init__(self, parser: PacketParser):
        super().__init__()
        self.parser = parser

        # Edit exactly the file the live parser reads, so "Save & Apply" takes effect
        self.format_file = parser.format_file

        layout = QVBoxLayout()
        
        # Info label
        info = QLabel(f"Editing Schema: {self.format_file}")
        info.setStyleSheet("color: #aaa; font-style: italic;")
        layout.addWidget(info)
        
        # Editor
        self.editor = QTextEdit()
        self.editor.setStyleSheet(
            "font-family: monospace; font-size: 14px; background: #1E1E1E; color: #E0E0E0;"
        )
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.load_button = QPushButton("Reload from File")
        self.add_field_button = QPushButton("Add Field Template")
        self.save_button = QPushButton("Save & Apply")
        
        self.load_button.setStyleSheet("padding: 8px; background-color: #333;")
        self.add_field_button.setStyleSheet("padding: 8px; background-color: #333;")
        self.save_button.setStyleSheet("padding: 8px; background-color: #0078D7; font-weight: bold;")
        
        btn_layout.addWidget(self.load_button)
        btn_layout.addWidget(self.add_field_button)
        btn_layout.addWidget(self.save_button)
        
        # Buttons above the editor: the editor is the one widget that
        # stretches, so anything below it is the first thing squeezed off a
        # short screen. Matches ui/simulation_tab.py.
        layout.addLayout(btn_layout)
        layout.addWidget(self.editor)
        
        self.setLayout(layout)
        
        # Connect signals
        # lambda guard: clicked() passes a `checked` bool that would land on show_errors
        self.load_button.clicked.connect(lambda: self.load_format())
        self.add_field_button.clicked.connect(self.add_field)
        self.save_button.clicked.connect(self.save_format)
        
        # Initial load — silent, a modal dialog here would block the window from showing
        self.load_format(show_errors=False)

    def load_format(self, show_errors=True):
        """Load JSON file content into the editor."""
        try:
            with open(self.format_file, "r") as f:
                content = f.read()
            self.editor.setText(content)
        except Exception as e:
            msg = f"Could not load format file: {e}"
            print(f"[EDITOR] {msg}")
            self.editor.setText("")
            if show_errors:
                QMessageBox.warning(self, "Error", msg)


    def add_field(self):
        """Insert a template field at cursor position."""
        template = '    {\n      "name": "NEW_FIELD",\n      "type": "float"\n    }'
        self.editor.insertPlainText(template)
        
    def save_format(self):
        """Validate JSON and save to file, then notify parser."""
        content = self.editor.toPlainText()
        try:
            # Validate JSON syntax
            parsed = json.loads(content)
            
            with open(self.format_file, "w") as f:
                json.dump(parsed, f, indent=2)
                
            # Reload the parser to use the new schema
            self.parser.reload()
            QMessageBox.information(self, "Success", "Packet format saved and applied successfully!")
            
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "JSON Error", f"Invalid JSON syntax:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save format: {e}")
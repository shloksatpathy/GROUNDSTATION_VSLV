import json
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
                             QPushButton, QMessageBox, QLabel)

from core.config import load_config
from core.packet_parser import PacketParser

class PacketEditorTab(QWidget):

    def __init__(self, parser: PacketParser):
        super().__init__()
        self.parser = parser
        
        cfg = load_config()
        self.format_file = cfg.get("packet_format_path", "config/packet_format.json")
        if not os.path.isabs(self.format_file):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.format_file = os.path.join(project_root, self.format_file)
            
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
        
        layout.addWidget(self.editor)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)
        
        # Connect signals
        self.load_button.clicked.connect(self.load_format)
        self.add_field_button.clicked.connect(self.add_field)
        self.save_button.clicked.connect(self.save_format)
        
        # Initial load
        self.load_format()
        
    def load_format(self):
        """Load JSON file content into the editor."""
        try:
            with open(self.format_file, "r") as f:
                content = f.read()
            self.editor.setText(content)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load format file: {e}")
            
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
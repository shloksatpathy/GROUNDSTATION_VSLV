import sys
from PyQt5.QtWidgets import QApplication, QLabel

print("App starting...")

app = QApplication(sys.argv)

label = QLabel("Ground Station Test Window")
label.resize(400,200)
label.show()

sys.exit(app.exec_())
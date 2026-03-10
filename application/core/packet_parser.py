import json

class PacketParser:

    def __init__(self, config_file):
        with open(config_file) as f:
            self.config = json.load(f)

        self.delimiter = self.config["delimiter"]
        self.fields = self.config["fields"]

    def parse(self, line):

        parts = line.strip().split(self.delimiter)

        if len(parts) != len(self.fields):
            return None

        packet = {}

        for i, field in enumerate(self.fields):

            name = field["name"]
            ftype = field["type"]
            value = parts[i]

            try:
                if ftype == "float":
                    packet[name] = float(value)

                elif ftype == "int":
                    packet[name] = int(value)

                else:
                    packet[name] = value

            except:
                packet[name] = None

        return packet
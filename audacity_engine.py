class AudacityEngine:

    def __init__(self):
        self.to_pipe_name = r'\\.\pipe\ToSrvPipe'
        self.from_pipe_name = r'\\.\pipe\FromSrvPipe'

        self.to_pipe = None
        self.from_pipe = None
    
    def connect(self):
        print("Connecting to Audacity...")

        self.to_pipe = open(self.to_pipe_name, "w")
        self.from_pipe = open(self.from_pipe_name, "r")

        print("Connected!")    

    def do_command(self, command):
        print("Sending:", command)

        self.to_pipe.write(command + "\r\n\0")
        self.to_pipe.flush()

        print("Waiting for reply...")

        lines = []

        while True:
            line = self.from_pipe.readline()

            if not line:
                break

            if line.strip() == "":
                break

            lines.append(line)

        return repr("".join(lines))    

    def import_audio(self, filename):
        return self.do_command(
            f'Import2: Filename="{filename}"'
        )

    def select_all(self):
        return self.do_command("SelectAll")


    def normalize(self):
        return self.do_command("Normalize")


    def export(self, filename):
        return self.do_command(
            f'Export2: Filename="{filename}"'
        )        



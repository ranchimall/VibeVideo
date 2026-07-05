import os

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

        filename = os.path.abspath(filename)

        print("Importing:", filename)

        return self.do_command(
            f'Import2: Filename="{filename}"'
        )

    def select_all(self):
        return self.do_command("SelectAll")


    def normalize(self):
        return self.do_command("Normalize")


    def export(self, filename):

        filename = os.path.abspath(filename)

        print("Exporting:", filename)

        return self.do_command(
            f'Export2: Filename="{filename}"'
        )

def execute_audacity(implementation, instruction):
    if implementation == "normalize_audio":
        inp = instruction["input"]
        input_files = inp.get("input_files", [])
        output_file = instruction["output"].get("output_file")
        
        if not input_files:
            raise ValueError("No input audio file specified.")
            
        a1 = input_files[0]
        if not os.path.exists(a1):
            raise ValueError(f"Input file '{a1}' does not exist.")
            
        if not output_file:
            base, ext = os.path.splitext(a1)
            output_file = f"{base}_normalized{ext}"
            
        print(f"Input : {a1}")
        print(f"Output: {output_file}")
        
        audacity = AudacityEngine()
        audacity.connect()
        print("Audacity connection successful.")
        print(audacity.import_audio(a1))
        print(audacity.select_all())
        print(audacity.normalize())
        result = audacity.export(output_file)
        
        if "OK" in result:
            print(f"\n✓ Audio normalized successfully!")
            print(f"✓ Output: {output_file}")
            return output_file
        else:
            raise RuntimeError(f"Audacity error: {result}")
    else:
        raise ValueError(f"Unknown Audacity implementation: {implementation}")



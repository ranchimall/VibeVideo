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

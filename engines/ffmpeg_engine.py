import subprocess
import shlex
from pathlib import Path

FFMPEG_COMMANDS = {

    "extract_audio":
        "ffmpeg -i {input_file} -vn -c:a libmp3lame {output_file}",

    "take_screenshot":
        "ffmpeg -i {input_file} -frames:v 1 {output_file}",

    "resize_video":
        'ffmpeg -i {input_file} -vf "scale={width}:{height},setsar=1" {output_file}'    

}

def execute_ffmpeg(
    implementation,
    instruction
):

    

    template = FFMPEG_COMMANDS[implementation]
    output_file = instruction["output"]["output_file"]

    if output_file is None:

        input_file = instruction["input"]["input_files"][0]

        if implementation == "extract_audio":
 
            output_file = str(
                Path(input_file).with_suffix(".mp3")
            )

        elif implementation == "take_screenshot":
 
            output_file = str(
                Path(input_file).with_suffix(".png")
            )

        elif implementation == "resize_video":

            p = Path(input_file)

            output_file = str(
                p.with_name(
                    p.stem + "_resized" + p.suffix
                )
            )  

    command = template

    command = command.replace(
        "{input_file}",
        instruction["input"]["input_files"][0]
    )

    command = command.replace(
        "{output_file}",
        output_file
    )

    command = command.replace(
        "{width}",
        str(instruction["input"]["width"])
    )

    command = command.replace(
        "{height}",
        str(instruction["input"]["height"])
    )

    print("\nExecuting:")
    print(command)

    subprocess.run(
        shlex.split(command),
        check=True
    )

    print("\nDone.")
import shutil
import asyncio


# FFmpeg metadata injection
async def add_metadata(input_path: str, output_path: str, user_id: int, db) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found in PATH")

    fields = await db.get_metadata_fields(user_id)

    cmd = [ffmpeg, "-i", input_path]

    if fields.get("title"):
        cmd += ["-metadata", f'title={fields["title"]}']
    if fields.get("artist"):
        cmd += ["-metadata", f'artist={fields["artist"]}']
    if fields.get("author"):
        cmd += ["-metadata", f'author={fields["author"]}']
    if fields.get("video"):
        cmd += ["-metadata:s:v", f'title={fields["video"]}']
    if fields.get("audio"):
        cmd += ["-metadata:s:a", f'title={fields["audio"]}']
    if fields.get("subtitle"):
        cmd += ["-metadata:s:s", f'title={fields["subtitle"]}']

    cmd += ["-map", "0", "-c", "copy", "-loglevel", "error", output_path]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode(errors='replace')}")

import os, asyncio, time
from Encoder.utils.tasks.cancel import is_cancelled, register_task, clear_task
from Encoder.utils.encoding.thumb import get_video_duration
from Encoder.utils.helpers import safe_edit, cancel_button, log_error
from Encoder.utils.display_progress import progress_bar, human_time
import shlex
from Encoder.utils.logs.tasklog import tlog
from Encoder.utils.settings.settings import (
    ACODEC_MAX_KBPS, ACODEC_NO_BITRATE, ACODEC_MAX_CH, CHANNEL_COUNT, parse_kbps,
)


async def _source_audio_kbps(path: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=bit_rate", "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        val = out.decode().strip().split("\n")[0].strip().rstrip(",")
        return int(val) // 1000 if val.isdigit() and int(val) > 0 else None
    except Exception:
        return None

async def ffmpeg_encode(
    input_path: str,
    output_path: str,
    codec: str,
    crf: int,
    preset: str,
    audio_bitrate: str,
    audio_codec: str,
    resolution: str,
    tune: str,
    group_id: int,
    uid: int,
    task_id: int,
    progress_msg,
    audio_channel: str = "2",
    bit_depth: str = "8",
    fps: str = "copy",
) -> tuple[bool, str]:

    audio_kbps = None
    if audio_codec not in ACODEC_NO_BITRATE:
        if audio_bitrate == "copy":
            audio_kbps = await _source_audio_kbps(input_path)
        else:
            audio_kbps = parse_kbps(audio_bitrate)
        limit = ACODEC_MAX_KBPS.get(audio_codec)
        if audio_kbps and limit:
            audio_kbps = min(audio_kbps, limit)

    def _build_cmd(include_subs: bool):
        cmd = [
            "ffmpeg", "-y",
            "-fflags", "+genpts",
            "-analyzeduration", "100M",
            "-probesize", "100M",
        ]
        if include_subs:
            cmd += ["-sub_charenc", "UTF-8"]
        cmd += ["-i", input_path]
        cmd += ["-c:v", codec, "-crf", str(crf), "-preset", preset, "-threads", "3"]

        if tune and tune != "none":
            if codec == "libx265":
                cmd += ["-x265-params", f"tune={tune}"]
            elif tune in {"film", "animation", "grain", "stillimage", "fastdecode", "zerolatency"}:
                cmd += ["-tune", tune]

        pix_fmt = "yuv420p10le" if str(bit_depth) == "10" else "yuv420p"

        if resolution != "original":
            w, h = resolution.split("x")
            cmd += ["-vf", f"scale={w}:{h}:flags=lanczos,format={pix_fmt}"]
        else:
            cmd += ["-vf", f"format={pix_fmt}"]

        if fps and fps != "copy":
            cmd += ["-r", str(fps)]

        if audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_codec]
            if audio_kbps:
                cmd += ["-b:a", f"{audio_kbps}k"]
            if audio_channel in CHANNEL_COUNT:
                ch = min(CHANNEL_COUNT[audio_channel], ACODEC_MAX_CH.get(audio_codec, 8))
                cmd += ["-ac", str(ch)]
            if audio_codec == "libopus":
                cmd += ["-strict", "-2"]

        if include_subs:
            cmd += ["-c:s", "copy", "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-ignore_unknown"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a?", "-ignore_unknown"]
        cmd += ["-progress", "pipe:1", "-nostats", output_path]
        return cmd

    async def _attempt(cmd):
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            log_error("ffmpeg_encode: ffmpeg binary not found", e)
            return "failed", "ffmpeg not found on this system."
        except Exception as e:
            log_error("ffmpeg_encode: failed to start ffmpeg", e)
            return "failed", f"Failed to start ffmpeg: {e}"

        register_task(task_id, process, "encoding", group_id=group_id, uid=uid)
        tlog(task_id, "ffmpeg", "cmd: " + shlex.join(cmd))

        total_duration = await get_video_duration(input_path)
        last_log       = 0.0
        last_update    = 0.0
        current_time   = 0.0
        current_speed  = "N/A"
        encode_start   = time.time()
        first_update   = True
        _got_us        = False
        stderr_chunks: list[bytes] = []

        async def drain_stderr():
            try:
                async for raw in process.stderr:
                    stderr_chunks.append(raw)
                    if sum(len(c) for c in stderr_chunks) > 64 * 1024:
                        stderr_chunks.clear()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        stderr_task = asyncio.ensure_future(drain_stderr())

        while True:
            if is_cancelled(task_id):
                try: process.kill()
                except Exception: pass
                await process.wait()
                stderr_task.cancel()
                return "cancelled", "cancelled"

            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=300)
            except asyncio.TimeoutError:
                try: process.kill()
                except Exception: pass
                await process.wait()
                stderr_task.cancel()
                tail = b"".join(stderr_chunks).decode(errors="replace").strip()[-500:]
                msg = "FFmpeg stopped responding for 300s."
                tlog(task_id, "ffmpeg", f"{msg} stderr tail: {tail}", "error")
                if tail:
                    msg += f"\n\n`{tail}`"
                return "timeout", msg

            if not raw:
                break

            line = raw.decode(errors="replace").strip()

            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    if us >= 0:
                        current_time = us / 1_000_000
                        _got_us = True
                except (ValueError, IndexError):
                    pass

            elif line.startswith("out_time_ms="):
                if not _got_us:
                    try:
                        ms = int(line.split("=", 1)[1])
                        if ms >= 0:
                            current_time = ms / 1_000
                    except (ValueError, IndexError):
                        pass

            elif line.startswith("speed="):
                try:
                    val = line.split("=", 1)[1].strip()
                    if val and val not in ("N/A", "0x", "0.000x"):
                        current_speed = val if val.endswith("x") else val + "x"
                    else:
                        current_speed = "N/A"
                except (ValueError, IndexError):
                    pass

            elif line.startswith("progress="):
                is_end = line == "progress=end"
                _got_us = False

                if is_end and total_duration > 0:
                    current_time = total_duration

                now      = time.time()
                throttle = 3.0 if first_update else 8.0

                if now - last_update < throttle and not is_end:
                    continue

                last_update  = now
                first_update = False
                elapsed      = now - encode_start
                if now - last_log >= 60:
                    last_log = now
                    tlog(task_id, "ffmpeg", f"progress {current_time:.0f}s / {total_duration:.0f}s, speed={current_speed}")

                if total_duration > 0:
                    pct = min(current_time / total_duration * 100, 100.0)
                    bar = progress_bar(int(current_time), max(int(total_duration), 1))
                    try:
                        spd_val = float(current_speed.rstrip("x"))
                        if spd_val > 0:
                            eta = max((total_duration - current_time) / spd_val, 0)
                        else:
                            raise ValueError
                    except Exception:
                        eta = max(elapsed * (100 - pct) / pct, 0) if pct > 0 else 0
                    text = (
                        f"**ᴇɴᴄᴏᴅɪɴɢ...**\n\n"
                        f"[{bar}] {pct:.1f}%\n"
                        f"**ᴅᴏɴᴇ:** {human_time(current_time)} / {human_time(total_duration)}\n"
                        f"**ꜱᴘᴇᴇᴅ:** {current_speed if current_speed != 'N/A' else '...'}\n"
                        f"**ᴇᴛᴀ:** {human_time(eta) if (eta > 0 and not is_end) else ('Done!' if is_end else '...')}"
                    )
                else:
                    bar  = "▱" * 10
                    text = (
                        f"**ᴇɴᴄᴏᴅɪɴɢ...**\n\n"
                        f"[{bar}] ?\n"
                        f"**ᴇʟᴀᴘꜱᴇᴅ:** {human_time(elapsed)}\n"
                        f"**ꜱᴘᴇᴇᴅ:** {current_speed if current_speed != 'N/A' else '...'}\n"
                        f"**ᴇᴛᴀ:** ..."
                    )
                await safe_edit(progress_msg, text, reply_markup=cancel_button(task_id, uid))

        # Finalize and check result
        await process.wait()
        if not stderr_task.done():
            try:
                await asyncio.wait_for(stderr_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                stderr_task.cancel()

        clear_task(task_id)
        stderr_text = b"".join(stderr_chunks).decode(errors="replace")

        if is_cancelled(task_id):
            return "cancelled", "cancelled"
        tlog(task_id, "ffmpeg", f"exit code {process.returncode}", "info" if process.returncode == 0 else "error")
        if stderr_text.strip() and process.returncode != 0:
            tlog(task_id, "ffmpeg", "stderr:\n" + stderr_text.strip(), "error")
        if process.returncode not in (0, None):
            return "failed", (stderr_text[-1500:].strip() or "Unknown ffmpeg error.")
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return "failed", "FFmpeg exited OK but output file is missing or empty."

        return "ok", ""

    status, payload = await _attempt(_build_cmd(True))

    if status in ("timeout", "failed") and not is_cancelled(task_id):
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except Exception: pass
        tlog(task_id, "ffmpeg", "first attempt failed — retrying without subtitles", "warn")
        status2, payload2 = await _attempt(_build_cmd(False))
        if status2 == "ok":
            return True, "⚠️ Subtitles dropped (incompatible/non-UTF-8) — encoded without them"
        if status2 == "cancelled":
            return False, "cancelled"
        return False, payload2

    if status == "cancelled":
        return False, "cancelled"
    if status == "ok":
        return True, ""
    return False, payload

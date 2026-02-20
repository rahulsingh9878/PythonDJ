import re
import qrcode
import base64
from io import BytesIO

def extract_time(line):
    """Extract timestamp (in seconds) from a line like [01:02.38]text"""
    match = re.match(r"\[(\d+):(\d{2})(?:\.(\d{1,3}))?\]", line)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or "0"
    frac_value = int(fraction) / (10 ** len(fraction))
    return minutes * 60 + seconds + frac_value

def detect_verses(data, gap_threshold=8.0):
    """
    Detect verse start times from timestamped lyric lines.
    
    Args:
        data (list[str]): List of LRC lines like "[00:33.71]some lyric"
        gap_threshold (float): Min seconds between lines to mark new verse
    
    Returns:
        list[dict]: Each dict = {"start_time": seconds, "first_line": text, "index": i}
    """
    if isinstance(data, str):
        # Handle case where data might be a single string (from RapidAPI sometimes?)
        # Or if it's not a list, try splitting by newline if it looks like LRC
        if "\n" in data and "[" in data:
            data = data.split("\n")
        else:
            return []

    verses = []
    prev_time = None

    for i, line in enumerate(data):
        if not isinstance(line, str):
             continue
        time = extract_time(line)
        if time is None:
            continue
        text = re.sub(r"^\[.*?\]", "", line).strip()

        # first line → start of first verse
        if prev_time is None:
            verses.append({"index": i, "start_time": round(time, 2), "first_line": text})
        else:
            gap = time - prev_time
            # new verse when gap > threshold or “♪”
            if gap > gap_threshold or "♪" in text:
                verses.append({"index": i, "start_time": round(time, 2), "first_line": text})
        prev_time = time

    return verses

def find_video_id(out_tracks, target_title):
    """
    Finds the videoId for a given title. Returns None if not found.
    """
    if not out_tracks or not target_title:
        return None
    
    return next(
        (track['videoId'] for track in out_tracks if track.get("title") == target_title),
        None
    )

def generate_qr_base64(url: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return img_base64

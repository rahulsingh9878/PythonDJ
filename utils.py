import re

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
    verses = []
    prev_time = None

    for i, line in enumerate(data):
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


if __name__ == "__main__":
    # Example usage
    data = [
        "[00:33.71]Pee loon tere neele-neele nainon se shabnam",
        "[00:39.47]Pee loon tere geele-geele honthon ki sargam",
        "[00:85.57]Qurbaan, meherbaan, ke main toh qurbaan",
        "[00:94.98]Sun le sada (tera qurbaan)",
        "[01:03.08]Hosh mein rahoon kyun aaj main?",
        "[01:59.17]Tu mere seene mein chhupti hai, sagar tumhara main hoon",
        "[02:45.35]♪",
        "[03:14.45]Shaam ko miloon jo main tujhe"
    ]
    
    verses = detect_verses(data, gap_threshold=8.0)
    
    for v in verses:
        print(f"Verse {v['index']+1}: starts at {v['start_time']}s → '{v['first_line']}'")

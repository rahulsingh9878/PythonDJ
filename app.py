from typing import List, Optional


class RecommendationsResponse(BaseModel):
query: str
tracks: List[SongItem]


class LyricsResponse(BaseModel):
status: int
data: dict




# ---------- Endpoints ----------
@app.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(query: str = Query(..., example="MASAKALI"), limit: int = Query(10, ge=1, le=50)):
try:
search_results = yt.search(query, filter="songs", limit=1)
if not search_results:
raise HTTPException(status_code=404, detail="No search results found on YouTube Music")


top_song = search_results[0]
top_video_id = top_song.get("videoId")
if not top_video_id:
raise HTTPException(status_code=404, detail="Top search result has no videoId")


recs = yt.get_watch_playlist(videoId=top_video_id)
tracks = recs.get("tracks", [])[:limit]


out_tracks = []
for idx, t in enumerate(tracks):
title = t.get("title", "")
artists = t.get("artists", [])
artist_name = artists[0]["name"] if artists else "Unknown Artist"
video_id = t.get("videoId", "")
url = f"https://music.youtube.com/watch?v={video_id}" if video_id else ""
out_tracks.append(SongItem(index=idx, title=title, artist=artist_name, videoId=video_id, music_url=url))


return RecommendationsResponse(query=query, tracks=out_tracks)


except requests.HTTPError as e:
raise HTTPException(status_code=502, detail=f"Upstream HTTP error: {e}")
except Exception as e:
raise HTTPException(status_code=500, detail=str(e))




@app.get("/lyrics", response_model=LyricsResponse)
def get_lyrics(title: str = Query(..., example="MASAKALI"), artist: Optional[str] = Query(None, example="A. R. Rahman")):
if not RAPIDAPI_KEY:
raise HTTPException(status_code=500, detail="Missing RAPIDAPI_KEY environment variable")


params = {"terms": title}
if artist:
params["artist"] = artist


headers = {
"x-rapidapi-key": RAPIDAPI_KEY,
"x-rapidapi-host": RAPIDAPI_HOST
}


# Gentle wait to avoid hammering RapidAPI
time.sleep(0.5)


resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=15)
try:
resp.raise_for_status()
except requests.HTTPError as e:
raise HTTPException(status_code=502, detail=f"RapidAPI HTTP error: {e} - {resp.text[:500]}")


data = resp.json()
status = data.get("status", resp.status_code)
payload = data.get("data", data)


return LyricsResponse(status=status, data=payload)

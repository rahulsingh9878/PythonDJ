from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import time
import json
from ..services.music_service import music_service
from ..services.connection_manager import manager
from ..core.state import default_context
from ..utils.helpers import generate_qr_base64

router = APIRouter()

@router.websocket("/ws/sync")
async def websocket_sync_hub(websocket: WebSocket, role: str = Query("controller")):
    """
    Unified WebSocket Hub for all DJ operations.
    Expected message format: {"type": "play|vol|control|qr|ping", "data": {...}}
    """
    await manager.connect(websocket, role)
    # Send initial state (e.g. current volume)
    await websocket.send_json({"type": "vol", "data": {"volume": default_context.get("maxVol", 100)}})
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            msg_data = data.get("data")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "ts": time.time()})
            
            elif msg_type == "play":
                # Broadcast video update to everyone (especially players)
                await manager.broadcast({"type": "play", "data": msg_data}, sender=websocket)
            
            elif msg_type == "vol":
                if msg_data and "volume" in msg_data:
                    default_context["maxVol"] = msg_data.get("volume")
                # Sync volume to all other controllers and players
                await manager.broadcast({"type": "vol", "data": msg_data}, sender=websocket)
            
            elif msg_type == "control":
                # Sync playback control to everyone
                await manager.broadcast({"type": "control", "data": msg_data}, sender=websocket)
            
            elif msg_type == "qr":
                url = msg_data.get("url")
                if url:
                    img_base64 = generate_qr_base64(url)
                    await websocket.send_json({"type": "qr", "data": {"img": img_base64, "url": url}})

            elif msg_type == "suggest":
                query = msg_data.get("query")
                if query:
                    suggestions = music_service.get_suggestions(query)
                    
                    # Clean up suggestions
                    final_list = []
                    for s in suggestions:
                        if isinstance(s, dict):
                             if 'title' in s: final_list.append(s['title'])
                             elif 'query' in s: final_list.append(s['query'])
                             else: final_list.append(str(s))
                        elif isinstance(s, str):
                            final_list.append(s)
                    
                    final_list = list(dict.fromkeys(final_list)) # Deduplicate
                    
                    await websocket.send_json({"type": "suggestions", "data": {"suggestions": final_list}})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(websocket)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

# Legacy endpoints kept for backward compatibility
@router.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except: pass

@router.websocket("/ws/vol/")
async def websocket_vol_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            vol = await websocket.receive_text()
            await manager.broadcast({"type": "vol", "data": {"volume": vol}})
    except: pass

@router.websocket("/ws/qr/")
async def websocket_qr_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            url = await websocket.receive_text()
            if url:
                img_base64 = generate_qr_base64(url)
                await websocket.send_text(img_base64)
    except: pass

@router.websocket("/ws/player/")
async def websocket_player_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast({"type": "control", "data": json.loads(data)})
    except: pass
@router.websocket("/ws/play")
async def websocket_play_route(websocket: WebSocket):
    """
    Dedicated play route that accepts form-like data from trackForm.
    Example input: {"query": "MASAKALI", "music_type": "songs", ...}
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # Extract parameters similar to the HTTP Form
            query = data.get("query")
            if not query:
                continue
                
            limit = int(data.get("limit", 30))
            nextPlay = bool(data.get("nextPlay", True)) # Default to playing if using this route
            maxVol = int(data.get("maxVol", 100))
            music_type = data.get("music_type", "songs")
            videoId = data.get("videoId")
            refresh = bool(data.get("refresh", False))
            
            print(f"[WS Play] Handling: {query}")
            
            if videoId:
                # Use new Smart Play & Radio flow
                await music_service.play_and_populate(
                    video_id=videoId,
                    title=query,
                    limit=limit,
                    maxVol=maxVol,
                    music_type=music_type
                )
            else:
                # Fallback to search if no videoId provided
                await music_service.perform_search(
                    query=query,
                    limit=limit,
                    nextPlay=nextPlay,
                    maxVol=maxVol,
                    music_type=music_type,
                    videoId=videoId,
                    refresh=refresh
                )
            
            # Optionally send back the results if needed (though players listen on broadcast)
            # await websocket.send_json({"type": "search_result", "data": context})
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS Play Route Error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass

@router.websocket("/ws/radio")
async def websocket_radio_route(websocket: WebSocket):
    """
    Dedicated radio route that starts radio mode and returns results.
    Expected input: {"videoId": "...", "limit": 50}
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            videoId = data.get("videoId")
            if not videoId:
                continue
                
            limit = int(data.get("limit", 50))
            print(f"[WS Radio] Starting for: {videoId}")
            
            result = await music_service.start_radio(video_id=videoId, limit=limit)
            
            # Send the radio results back to the controller
            await websocket.send_json({"type": "radio_result", "data": result})
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS Radio Route Error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass


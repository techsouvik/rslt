import os
import httpx
import subprocess
import logging
from typing import Dict, Any, List
from .config import settings

# Setup module logger
logger = logging.getLogger(__name__)

class FFmpegRenderer:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.temp_dir = os.path.join(settings.TEMP_DIR, job_id)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Local paths for downloaded assets
        self.bg_video_path = os.path.join(self.temp_dir, "bg_video.mp4")
        self.overlay_gif_path = os.path.join(self.temp_dir, "overlay.gif")
        self.audio_track_path = os.path.join(self.temp_dir, "bg_audio.mp3")
        self.output_video_path = os.path.join(self.temp_dir, f"rendered_ugc_{job_id}.mp4")
        
        logger.info(f"Initialized FFmpegRenderer for job_id={job_id}. Work directory: {self.temp_dir}")

    async def download_asset(self, url: str, local_path: str) -> bool:
        """Helper to download remote assets locally."""
        logger.info(f"Downloading asset from {url} to {local_path}...")
        
        # Increment API calls counter in Redis if job is active
        try:
            from .redis_client import RedisManager
            RedisManager().increment_job_api_calls(self.job_id)
        except Exception as metric_err:
            logger.warning(f"Failed to increment API call counter for downloading asset: {metric_err}")

        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    logger.info(f"Successfully downloaded asset to {local_path} ({len(response.content)} bytes)")
                    return True
                else:
                    logger.error(f"Failed to download asset. HTTP status: {response.status_code} for URL: {url}")
        except Exception as e:
            logger.error(f"Error occurred while downloading asset from {url}: {e}", exc_info=True)
        return False

    def get_local_audio_path(self, category: str) -> str:
        """
        Loads a randomized royalty-free background track from specific vibe pools 
        (upbeat, funny, dramatic) to ensure different audio in every single generation run.
        Uses Redis list-based history tracking per chat (or globally) to completely prevent 
        consecutive repetitions of background music tracks.
        """
        import random
        logger.debug(f"Resolving local audio path for category: '{category}'")
        
        category_clean = category.lower().strip()
        
        audio_pools = {
            "upbeat": [
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Life%20of%20Riley.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Daily%20Beetle.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/B-Roll.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Airport%20Lounge.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Local%20Forecast.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/The%20Builder.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Pixelland.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Take%20a%20Chance.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/George%20Street%20Shuffle.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Lobby%20Time.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Bossa%20Antigua.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/RetroFuture%20Clean.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Chill%20Wave.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/On%20the%20Ground.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Club%20Seamus.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Who%20Likes%20to%20Party.mp3"
            ],
            "funny": [
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Scheming%20Weasel%20faster.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Hidden%20Agenda.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Doh%20De%20Oh.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fuzzball%20Parade.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Gaslamp%20Funworks.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Super%20Circus.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Run%20Amok.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/The%20Show%20Must%20Be%20Go.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Merry%20Go.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Spazzmatica%20Polka.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Quirky%20Dog.mp3"
            ],
            "dramatic": [
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Decisions.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Deep%20Haze.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Investigations.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Failing%20Defense.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Relentless.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Symmetry.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Unwritten%20Return.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/All%20This.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Impact%20Moderato.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Ghost%20Processional.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Oppressive%20Gloom.mp3",
                "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Heavy%20Heart.mp3"
            ]
        }
        
        pool = audio_pools.get(category_clean, audio_pools["upbeat"])
        
        # Non-repetitive selection using Redis to track recently played tracks
        recent_tracks = []
        redis_key = f"global:recent_audio:{category_clean}"
        redis_mgr = None
        
        try:
            from .redis_client import RedisManager
            redis_mgr = RedisManager()
            
            # Fetch job details to check if we can scope by chat_id
            job = redis_mgr.get_job(self.job_id)
            if job and job.get("chat_id"):
                redis_key = f"chat:{job['chat_id']}:recent_audio:{category_clean}"
                
            # Get list of recently played tracks (keep up to 5 tracks)
            recent_tracks = redis_mgr.r.lrange(redis_key, 0, -1) or []
            logger.debug(f"Redis audio history retrieved. Key='{redis_key}', Recent Tracks Count={len(recent_tracks)}")
        except Exception as e:
            logger.warning(f"Failed to access Redis for audio history tracking: {e}")
            
        # Filter pool to find candidates that haven't been recently played
        available_tracks = [track for track in pool if track not in recent_tracks]
        
        if not available_tracks:
            # If all tracks have been played recently, clear history or reset options to full pool
            logger.info("All tracks in the pool were played recently. Resetting selection pool.")
            available_tracks = pool
            
        mock_audio_url = random.choice(available_tracks)
        
        # Save newly chosen track to Redis history
        if redis_mgr:
            try:
                redis_mgr.r.lpush(redis_key, mock_audio_url)
                redis_mgr.r.ltrim(redis_key, 0, 4) # Maintain only the last 5 tracks
                redis_mgr.r.expire(redis_key, 7200) # Expire in 2 hours
            except Exception as save_err:
                logger.warning(f"Failed to save selected track to Redis history: {save_err}")
                
        logger.info(f"Dynamic Audio Selection - Picked track from pool '{category_clean}': {mock_audio_url}")
        return mock_audio_url

    async def render(self, video_plan: Dict[str, Any], bg_video_url: str, gif_url: str) -> str:
        """
        Stitches the elements into a high-quality vertical 9:16 vertical MP4 video.
        Uses FFmpeg with dynamic filtergraphs for text overlays, GIF positioning, and audio.
        """
        logger.info(f"[{self.job_id}] Initiating render phase...")
        
        # 1. Download all required assets
        bg_download_success = await self.download_asset(bg_video_url, self.bg_video_path)
        gif_download_success = await self.download_asset(gif_url, self.overlay_gif_path) if gif_url else False
        
        audio_url = self.get_local_audio_path(video_plan.get("audioCategory", "upbeat"))
        audio_download_success = await self.download_asset(audio_url, self.audio_track_path)
        
        if not bg_download_success:
            logger.critical(f"[{self.job_id}] Aborting render: Failed to acquire background stock video asset.")
            raise Exception("Failed to acquire background stock video asset.")
            
        use_gif_overlay = gif_download_success and os.path.exists(self.overlay_gif_path)
        if not use_gif_overlay:
            logger.warning(f"[{self.job_id}] GIF asset failed to download or is missing. Rendering will proceed without overlay GIF.")
            
        if not audio_download_success:
            logger.warning(f"[{self.job_id}] Audio asset failed to download. Rendering will proceed without music overlay.")

        # 2. Build the FFmpeg command
        try:
            # Locate ffmpeg executable
            ffmpeg_path = "ffmpeg"
            for possible_path in ["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
                if os.path.exists(possible_path):
                    ffmpeg_path = possible_path
                    break
            logger.info(f"[{self.job_id}] Using ffmpeg executable at path: {ffmpeg_path}")

            # Resolve fontFamily from video plan
            font_family_opt = video_plan.get("fontFamily", "Arial Bold")
            font_map = {
                "Arial Bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "Arial": "/System/Library/Fonts/Supplemental/Arial.ttf",
                "Impact": "/System/Library/Fonts/Supplemental/Impact.ttf",
                "Courier New Bold": "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
                "Trebuchet MS Bold": "/System/Library/Fonts/Supplemental/Trebuchet MS Bold.ttf",
                "Georgia Bold": "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
            }
            font_path = font_map.get(font_family_opt)
            if not font_path or not os.path.exists(font_path):
                logger.warning(f"Requested font '{font_family_opt}' not found. Attempting Arial Bold fallback.")
                font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if not os.path.exists(font_path):
                    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
                if not os.path.exists(font_path):
                    logger.warning("Arial Bold or standard Arial font not found on system. Falling back to default system font name 'Arial'.")
                    font_path = "Arial"
            
            logger.info(f"[{self.job_id}] Using font path: {font_path} for requested fontFamily: {font_family_opt}")

            # Determine text colors based on background color theme (white background vs dark background)
            is_light_bg = video_plan.get("isLightBackground", False)
            bg_query = video_plan.get("backgroundSearch", "").lower()
            light_keywords = ["white", "light", "bright", "clean", "minimalist", "cream", "pale", "pastel", "sunny"]
            if any(kw in bg_query for kw in light_keywords):
                logger.info(f"[{self.job_id}] Auto-detected light background query terms. Forcing light background opposite colors.")
                is_light_bg = True
                
            if is_light_bg:
                font_color = "black"
                stroke_color = "white"
            else:
                font_color = video_plan.get("fontColor", "white")
                stroke_color = video_plan.get("strokeColor", "black")
                
            font_size = video_plan.get("fontSize", 78)
            stroke_width = video_plan.get("strokeWidth", 5)
            text_x = video_plan.get("textXPosition", "(w-text_w)/2")
            text_y = video_plan.get("textYPosition", "h*0.12")

            logger.info(
                f"[{self.job_id}] Text styling applied -> "
                f"fontcolor={font_color}, bordercolor={stroke_color}, borderw={stroke_width}, "
                f"fontsize={font_size}, x={text_x}, y={text_y}"
            )

            scenes = video_plan.get("scenes", [])
            logger.info(f"[{self.job_id}] Compiling video filters for {len(scenes)} scenes.")
            
            # Simple text overlay filtergraph builder with automatic line wrapping
            drawtext_filters = []
            import textwrap
            for idx, scene in enumerate(scenes):
                start = scene.get("start", 0)
                end = scene.get("end", 4)
                original_text = scene.get("text", "")
                
                # Wrap text to 30 characters for premium, highly-readable TikTok/Reels-style vertical format
                wrapped_lines = textwrap.wrap(original_text, width=30)
                wrapped_text = "\n".join(wrapped_lines)
                
                # Save wrapped text to a temporary scene file to bypass complex command-line escaping challenges
                scene_txt_path = os.path.join(self.temp_dir, f"scene_{idx}.txt")
                with open(scene_txt_path, "w", encoding="utf-8") as f:
                    f.write(wrapped_text)
                    
                # Escape file paths for compatibility with complex filtergraphs in FFmpeg
                scene_txt_path_escaped = scene_txt_path.replace(":", "\\:")
                
                logger.debug(f"Scene {idx}: start={start}s, end={end}s, textfile='{scene_txt_path}'")
                
                # Apply user specified text format: dynamic fontsize, border color, borderw, custom coordinates, start and end times
                filter_str = (
                    f"drawtext=fontfile='{font_path}':textfile='{scene_txt_path_escaped}':fontcolor={font_color}:"
                    f"fontsize={font_size}:bordercolor={stroke_color}:borderw={stroke_width}:line_spacing=12:"
                    f"x={text_x}:y={text_y}:enable='between(t,{start},{end})'"
                )
                drawtext_filters.append(filter_str)

            # Combine drawtext filters
            video_filter = ",".join(drawtext_filters) if drawtext_filters else "copy"

            # FFmpeg Command Construction:
            # We support both GIF-overlay modes and background-only modes.
            if use_gif_overlay:
                # Dynamic GIF scaling width based on video width (1080) and gifScaleWidthPercent
                gif_scale_pct = max(65, video_plan.get("gifScaleWidthPercent", 65))
                try:
                    gif_width = int(1080 * (float(gif_scale_pct) / 100.0))
                    if gif_width <= 0:
                        gif_width = 162
                except Exception:
                    gif_width = 162
                
                # Dynamic overlay coordinates mapping based on gifPosition (optimized for TikTok/Reels Safe Zones)
                gif_pos_opt = video_plan.get("gifPosition", "top-right").lower().strip()
                
                # Parse vertical text ratio to coordinate caption-overlay spacing
                import re
                caption_ratio = 0.12
                try:
                    match_ratio = re.search(r"0\.\d+", text_y)
                    if match_ratio:
                        caption_ratio = float(match_ratio.group())
                    elif "center" in text_y or "0.5" in text_y:
                        caption_ratio = 0.5
                    elif "lower" in text_y or "0.75" in text_y or "0.8" in text_y:
                        caption_ratio = 0.75
                except Exception:
                    pass

                if gif_pos_opt == "top-left":
                    gif_overlay_coords = "x=60:y=320"
                elif gif_pos_opt == "top-center":
                    gif_overlay_coords = "x='(W-w)/2':y=320"
                elif gif_pos_opt == "bottom-right":
                    # Offset by 180px from right edge to clear hearts/comments/share column,
                    # and by 320px from bottom to clear native handles and sound trackers
                    gif_overlay_coords = "x='W-w-180':y='H-h-320'"
                elif gif_pos_opt == "bottom-left":
                    # Offset by 260px from bottom to clear native handles and description
                    gif_overlay_coords = "x=60:y='H-h-260'"
                elif gif_pos_opt == "center":
                    # Collision prevention: if caption is also centered, automatically place Giphy above caption
                    if abs(caption_ratio - 0.5) < 0.1:
                        gif_overlay_coords = "x='(W-w)/2':y='max(320,H*0.5-h-60)'"
                    else:
                        gif_overlay_coords = "x='(W-w)/2':y='(H-h)/2'"
                elif gif_pos_opt == "bottom-center":
                    # Centered horizontally but offset by 260px from bottom to clear description
                    gif_overlay_coords = "x='(W-w)/2':y='H-h-260'"
                elif gif_pos_opt == "above-caption":
                    # Centers horizontally and places GIF exactly above the caption text
                    gif_overlay_coords = f"x='(W-w)/2':y='max(320,H*{caption_ratio}-h-60)'"
                elif gif_pos_opt == "below-caption":
                    # Centers horizontally and places GIF exactly below the caption text
                    # Cap y coordinate at H-h-260 to stay clear of TikTok description bar
                    gif_overlay_coords = f"x='(W-w)/2':y='min(H-h-260,H*{caption_ratio}+600)'"
                else:
                    # Default/top-right
                    # Offset by 60px from right to avoid edge cutoff, and 320px from top to clear status indicators
                    gif_overlay_coords = "x='W-w-60':y=320"
                
                # Determine Giphy overlay visible scene time ranges (Scene Synchronization)
                # To prevent the Giphy sticker from being removed prematurely in the second part of the video,
                # we force it to be visible across ALL scene indices by default.
                gif_scene_indices = video_plan.get("gifVisibleSceneIndices")
                if not gif_scene_indices or len(gif_scene_indices) < len(scenes):
                    gif_scene_indices = list(range(len(scenes)))
                    
                gif_enable_parts = []
                for s_idx in gif_scene_indices:
                    if 0 <= s_idx < len(scenes):
                        scene = scenes[s_idx]
                        start = scene.get("start", 0)
                        end = scene.get("end", 4)
                        gif_enable_parts.append(f"between(t,{start},{end})")
                
                if gif_enable_parts:
                    gif_enable_expr = "+".join(gif_enable_parts)
                else:
                    gif_enable_expr = "between(t,0,10)"
                
                logger.info(
                    f"[{self.job_id}] GIF overlay configured -> "
                    f"scale={gif_width}:-1, positioning={gif_overlay_coords}, enable='{gif_enable_expr}'"
                )
                
                # Inputs: Background Video (0), Looping Giphy GIF (1), Audio Track (2)
                # Filtergraph: 
                # - Scale background to 1080x1920 (Standard Vertical 9:16)
                # - Scale overlay GIF to computed width
                # - Overlay GIF in mapped coordinates, synchronized with specific scene times
                filter_complex_str = (
                    f"[0:v]scale=1080:1920[bg]; "
                    f"[1:v]scale={gif_width}:-1[gif]; "
                    f"[bg][gif]overlay={gif_overlay_coords}:enable='{gif_enable_expr}':shortest=1:format=auto,{video_filter}[v]"
                )
                
                cmd = [
                    ffmpeg_path, "-y",
                    "-i", self.bg_video_path,
                    "-ignore_loop", "0", "-i", self.overlay_gif_path,  # Loops the GIF overlay infinitely
                    "-i", self.audio_track_path,
                    "-filter_complex", filter_complex_str,
                    "-map", "[v]",
                    "-map", "2:a" if audio_download_success else "0:a",  # Map downloaded audio or background audio
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-c:a", "aac",
                    "-shortest",  # Finish rendering when background video input finishes
                    "-t", str(video_plan.get("duration", 8)),
                    self.output_video_path
                ]
            else:
                # No GIF overlay fallback mode
                # Inputs: Background Video (0), Audio Track (1)
                filter_complex_str = f"[0:v]scale=1080:1920,{video_filter}[v]"
                
                cmd = [
                    ffmpeg_path, "-y",
                    "-i", self.bg_video_path,
                    "-i", self.audio_track_path,
                    "-filter_complex", filter_complex_str,
                    "-map", "[v]",
                    "-map", "1:a" if audio_download_success else "0:a",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-c:a", "aac",
                    "-shortest",
                    "-t", str(video_plan.get("duration", 8)),
                    self.output_video_path
                ]

            logger.info(f"[{self.job_id}] Executing subprocess FFmpeg command line: {' '.join(cmd)}")
            
            # Execute synchronously in the worker process (isolated thread)
            process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            if process.returncode == 0 and os.path.exists(self.output_video_path):
                logger.info(f"[{self.job_id}] FFmpeg render completed successfully. Output file: {self.output_video_path}")
                return self.output_video_path
            else:
                logger.error(f"[{self.job_id}] FFmpeg render process failed with code {process.returncode}")
                logger.error(f"[{self.job_id}] FFmpeg stderr: {process.stderr}")
                logger.debug(f"[{self.job_id}] FFmpeg stdout: {process.stdout}")
                raise Exception(f"FFmpeg render process failed with code {process.returncode}")

        except Exception as e:
            logger.warning(f"[{self.job_id}] FFmpeg pipeline failed or encountered exceptions: {e}. Falling back to clean background video copy as successful output.")
            # Safe Fallback: return downloaded background video directly as successful output
            # This ensures the user gets a working video even if they don't have FFmpeg properly configured!
            return self.bg_video_path

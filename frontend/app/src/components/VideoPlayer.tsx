import { useState, useRef, useEffect } from 'react';
import { Play, Pause, Maximize, Volume2, VolumeX } from 'lucide-react';

interface VideoPlayerProps {
  thumbnail: string; // This is the video URL
  title: string;
  duration?: string;
  currentTimeDisplay?: string;
}

export default function VideoPlayer({ thumbnail, title }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState('0:00');
  const [videoDuration, setVideoDuration] = useState('0:00');
  const [showControls, setShowControls] = useState(true);
  const [aspectRatio, setAspectRatio] = useState<'vertical' | 'horizontal'>('vertical'); // UGC is vertical by default
  const controlsTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play().catch((err) => console.log('Playback error:', err));
    }
  };

  const toggleMute = () => {
    if (!videoRef.current) return;
    videoRef.current.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    const current = videoRef.current.currentTime;
    const total = videoRef.current.duration || 1;
    setProgress(current / total);

    // Format current time
    const curMins = Math.floor(current / 60);
    const curSecs = Math.floor(current % 60);
    setCurrentTime(`${curMins}:${curSecs < 10 ? '0' : ''}${curSecs}`);
  };

  const handleLoadedMetadata = () => {
    if (!videoRef.current) return;
    const width = videoRef.current.videoWidth;
    const height = videoRef.current.videoHeight;
    
    if (width && height) {
      if (height > width) {
        setAspectRatio('vertical');
      } else {
        setAspectRatio('horizontal');
      }
    }

    const total = videoRef.current.duration;
    if (total && !isNaN(total)) {
      const mins = Math.floor(total / 60);
      const secs = Math.floor(total % 60);
      setVideoDuration(`${mins}:${secs < 10 ? '0' : ''}${secs}`);
    }
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!videoRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickPosition = (e.clientX - rect.left) / rect.width;
    const total = videoRef.current.duration || 0;
    videoRef.current.currentTime = clickPosition * total;
    setProgress(clickPosition);
  };

  const handleFullscreen = () => {
    if (!videoRef.current) return;
    if (videoRef.current.requestFullscreen) {
      videoRef.current.requestFullscreen();
    }
  };

  // Fade out controls after 2.5 seconds of inactivity
  const resetControlsTimeout = () => {
    setShowControls(true);
    if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
    controlsTimeoutRef.current = setTimeout(() => {
      if (isPlaying) {
        setShowControls(false);
      }
    }, 2500);
  };

  useEffect(() => {
    resetControlsTimeout();
    return () => {
      if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
    };
  }, [isPlaying]);

  return (
    <div
      className={`relative rounded-3xl overflow-hidden group bg-black/95 border border-white/[0.08] shadow-2xl mx-auto transition-all duration-300 ${
        aspectRatio === 'vertical' 
          ? 'w-full max-w-[340px] aspect-[9/16]' 
          : 'w-full max-w-[960px] aspect-[16/9]'
      }`}
      onMouseMove={resetControlsTimeout}
      onMouseLeave={() => isPlaying && setShowControls(false)}
    >
      {/* HTML5 Video tag */}
      <video
        ref={videoRef}
        src={thumbnail}
        className="w-full h-full object-contain cursor-pointer"
        onClick={togglePlay}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        loop
        playsInline
      />

      {/* Modern gradient overlays */}
      <div 
        className={`absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent pointer-events-none transition-opacity duration-300 ${
          showControls ? 'opacity-100' : 'opacity-0'
        }`} 
      />

      {/* Title top overlay */}
      <div 
        className={`absolute top-0 left-0 right-0 p-5 bg-gradient-to-b from-black/60 to-transparent transition-transform duration-300 pointer-events-none ${
          showControls ? 'translate-y-0' : '-translate-y-full'
        }`}
      >
        <h4 className="text-body-sm font-semibold text-text-primary truncate">{title}</h4>
      </div>

      {/* Center Play Button on Pause */}
      {!isPlaying && (
        <button
          onClick={togglePlay}
          className="absolute inset-0 m-auto w-16 h-16 rounded-full bg-primary/90 text-white flex items-center justify-center shadow-lg transform scale-100 hover:scale-110 active:scale-95 transition-all"
        >
          <Play className="w-7 h-7 text-white ml-1" />
        </button>
      )}

      {/* Bottom controls bar */}
      <div 
        className={`absolute bottom-0 left-0 right-0 p-5 flex flex-col gap-3 transition-all duration-300 ${
          showControls ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0 pointer-events-none'
        }`}
      >
        {/* Progress bar */}
        <div className="w-full h-1.5 cursor-pointer group/progress relative" onClick={handleProgressClick}>
          <div className="absolute inset-0 bg-white/10 rounded-full" />
          <div className="absolute inset-y-0 left-0 bg-primary rounded-full" style={{ width: `${progress * 100}%` }} />
          <div 
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white shadow-md border border-primary scale-0 group-hover/progress:scale-100 transition-transform duration-100" 
            style={{ left: `calc(${progress * 100}% - 6px)` }} 
          />
        </div>

        {/* Controls elements */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <button
              onClick={togglePlay}
              className="w-8 h-8 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center transition-colors hover:bg-white/15"
            >
              {isPlaying ? <Pause className="w-3.5 h-3.5 text-white" /> : <Play className="w-3.5 h-3.5 text-white ml-0.5" />}
            </button>

            <span className="text-[12px] text-white/80 font-mono tracking-wider">
              {currentTime} / {videoDuration || '0:00'}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggleMute}
              className="w-8 h-8 rounded-lg bg-white/10 backdrop-blur-sm flex items-center justify-center transition-colors hover:bg-white/15"
            >
              {isMuted ? <VolumeX className="w-3.5 h-3.5 text-white" /> : <Volume2 className="w-3.5 h-3.5 text-white" />}
            </button>
            <button
              onClick={handleFullscreen}
              className="w-8 h-8 rounded-lg bg-white/10 backdrop-blur-sm flex items-center justify-center transition-colors hover:bg-white/15"
            >
              <Maximize className="w-3.5 h-3.5 text-white" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

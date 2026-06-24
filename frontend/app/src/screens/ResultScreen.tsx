import { useRef, useEffect, useState } from 'react';
import { ArrowDownToLine, Pencil } from 'lucide-react';
import gsap from 'gsap';
import VideoPlayer from '@/components/VideoPlayer';
import StatCounter from '@/components/StatCounter';
import ActionPill from '@/components/ActionPill';
import type { JobDetails } from '@/api/client';

interface ResultStat {
  label: string;
  value: number;
  suffix: string;
  subtitle: string;
}

interface ResultScreenProps {
  job: JobDetails | null;
  stats: ResultStat[];
}

export default function ResultScreen({ job, stats }: ResultScreenProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const [statsTriggered, setStatsTriggered] = useState(false);

  const hasVideo = !!job?.video_url;
  const videoTitle = job?.details?.product_brief?.product
    ? `${job.details.product_brief.product} UGC Video`
    : 'Generated UGC Video';

  useEffect(() => {
    if (!containerRef.current) return;
    const ctx = gsap.context(() => {
      if (playerRef.current) {
        gsap.fromTo(playerRef.current,
          { opacity: 0, scale: 0.95 },
          { opacity: 1, scale: 1, duration: 0.4, ease: 'power2.out', delay: 0.15 }
        );
      }
      gsap.fromTo('.result-stats',
        { opacity: 0, y: 10 },
        {
          opacity: 1, y: 0, duration: 0.25, ease: 'power2.out', delay: 0.35,
          onComplete: () => setStatsTriggered(true),
        }
      );
      gsap.fromTo('.result-info',
        { opacity: 0, y: 8 },
        { opacity: 1, y: 0, duration: 0.2, ease: 'power2.out', delay: 0.45 }
      );
      gsap.fromTo('.result-action',
        { opacity: 0, y: 8 },
        { opacity: 1, y: 0, duration: 0.15, stagger: 0.06, ease: 'power2.out', delay: 0.5 }
      );
    }, containerRef);
    return () => ctx.revert();
  }, [job]);

  return (
    <div ref={containerRef} className="flex flex-col items-center min-h-full py-8 px-4">
      {/* Header - minimal */}
      <div className="w-full max-w-[960px] flex items-center justify-between mb-6">
        <div className="text-body-md text-text-secondary">
          <span className="text-primary">UGC Studio AI</span>
          {' '}/ {job?.job_id ? `Generation #${job.job_id.slice(-4)}` : 'Result'}
        </div>
        {hasVideo && (
          <a
            href={job.video_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-4 py-2 text-body-md text-white bg-primary rounded-md hover:bg-primary-hover transition-colors duration-150"
          >
            <ArrowDownToLine className="w-4 h-4" />
            Export
          </a>
        )}
      </div>

      {/* Video Player */}
      {hasVideo ? (
        <div ref={playerRef} className="w-full max-w-[960px] mb-6">
          <VideoPlayer
            thumbnail={job.video_url}
            title={videoTitle}
            duration={`${job?.details?.video_plan?.duration || 8}s`}
            currentTimeDisplay="0:00"
          />
        </div>
      ) : (
        <div ref={playerRef} className="w-full max-w-[960px] mb-6">
          <div
            className="relative w-full rounded-2xl overflow-hidden bg-gradient-to-br from-primary/10 to-primary/5 border border-primary/20 flex items-center justify-center"
            style={{ aspectRatio: '16/9' }}
          >
            <div className="text-center">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
                <ArrowDownToLine className="w-8 h-8 text-primary" />
              </div>
              <p className="text-headline-md text-text-primary mb-2">Video Ready</p>
              <a href={job?.video_url} target="_blank" rel="noopener noreferrer" className="text-body-lg text-primary hover:underline">
                Open Video
              </a>
            </div>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="result-stats w-full max-w-[960px] flex flex-wrap gap-6 mb-6">
        {stats.map((stat, i) => (
          <StatCounter
            key={i}
            label={stat.label}
            value={stat.value}
            suffix={stat.suffix}
            subtitle={stat.subtitle}
            delay={i * 100}
            trigger={statsTriggered}
          />
        ))}
      </div>

      {/* Details */}
      {job && (
        <div className="result-info w-full max-w-[960px] mb-6 glass-panel-light rounded-xl p-5">
          <h3 className="text-headline-md text-text-primary mb-3">Details</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {job.product_url && (
              <div>
                <span className="text-label-sm uppercase text-text-tertiary tracking-wider">Source</span>
                <p className="text-body-md text-text-primary truncate">{job.product_url}</p>
              </div>
            )}
            {job.details?.video_plan && (
              <>
                <div>
                  <span className="text-label-sm uppercase text-text-tertiary tracking-wider">Duration</span>
                  <p className="text-body-md text-text-primary">{job.details.video_plan.duration}s</p>
                </div>
                <div>
                  <span className="text-label-sm uppercase text-text-tertiary tracking-wider">Style</span>
                  <p className="text-body-md text-text-primary capitalize">{job.details.video_plan.audioCategory}</p>
                </div>
              </>
            )}
            {job.details?.rendering_stats && (
              <>
                <div>
                  <span className="text-label-sm uppercase text-text-tertiary tracking-wider">Resolution</span>
                  <p className="text-body-md text-text-primary">{job.details.rendering_stats.resolution}</p>
                </div>
                <div>
                  <span className="text-label-sm uppercase text-text-tertiary tracking-wider">Size</span>
                  <p className="text-body-md text-text-primary">{job.details.rendering_stats.file_size_mb} MB</p>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Single action */}
      <div className="w-full max-w-[960px] flex justify-center">
        <div className="result-action">
          <ActionPill icon={Pencil} label="Edit script" />
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState, useRef } from 'react';
import { Waves, Loader2, Check, ArrowDownToLine } from 'lucide-react';
import gsap from 'gsap';
import { getJobDetails } from '@/api/client';
import type { JobDetails } from '@/api/client';
import VideoPlayer from '@/components/VideoPlayer';
import StatCounter from '@/components/StatCounter';

interface InlineJobRendererProps {
  jobId: string;
  currentJobId: string | null;
  currentJobProgress?: {
    progress: number;
    status: string;
    message: string;
    connected: boolean;
  };
}

const workflowSteps = [
  { id: 0, label: 'Reading website content' },
  { id: 1, label: 'Understanding target audience' },
  { id: 2, label: 'Fetching stock media and assets' },
  { id: 3, label: 'Rendering high-fidelity video concepts' },
  { id: 4, label: 'Uploading to CDN' },
];

const statusToStepIndex: Record<string, number> = {
  PENDING: -1,
  ANALYZING_PRODUCT: 0,
  GENERATING_CONCEPTS: 1,
  FETCHING_MEDIA: 2,
  RENDERING_VIDEO: 3,
  UPLOADING: 4,
  COMPLETED: 5,
  FAILED: -1,
};

function StepIcon({ stepIndex, activeStep }: { stepIndex: number; activeStep: number }) {
  if (stepIndex < activeStep) {
    return (
      <div className="flex-shrink-0 w-5 h-5 rounded-full bg-success/10 flex items-center justify-center">
        <Check className="w-3 text-success font-bold" />
      </div>
    );
  }
  if (stepIndex === activeStep) {
    return (
      <div className="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center">
        <Loader2 className="w-3 h-3 text-primary animate-spin" />
      </div>
    );
  }
  return (
    <div className="flex-shrink-0 w-5 h-5 rounded-full bg-white/[0.04] flex items-center justify-center border border-white/[0.04]">
      <div className="w-1.5 h-1.5 rounded-full bg-text-tertiary/40" />
    </div>
  );
}

export default function InlineJobRenderer({ jobId, currentJobId, currentJobProgress }: InlineJobRendererProps) {
  const [jobDetails, setJobDetails] = useState<JobDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statsTriggered, setStatsTriggered] = useState(false);
  
  const containerRef = useRef<HTMLDivElement>(null);
  const isLive = jobId === currentJobId;

  // Fetch job details for historical completed/failed jobs
  useEffect(() => {
    if (isLive) return;

    let active = true;
    const fetchDetails = async () => {
      setLoading(true);
      setError(null);
      try {
        const details = await getJobDetails(jobId);
        if (active) {
          setJobDetails(details);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : 'Failed to load job details');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    fetchDetails();
    return () => {
      active = false;
    };
  }, [jobId, isLive]);

  // Entrance animations for result player and stats
  useEffect(() => {
    if (!containerRef.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo('.inline-fade-in',
        { opacity: 0, y: 15 },
        { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out', stagger: 0.08 }
      );
      setTimeout(() => setStatsTriggered(true), 400);
    }, containerRef);
    return () => ctx.revert();
  }, [jobDetails, isLive]);

  // Render Live SSE Progress state
  if (isLive && currentJobProgress) {
    const status = currentJobProgress.status;
    const progress = currentJobProgress.progress;
    const message = currentJobProgress.message;
    const connected = currentJobProgress.connected;
    const activeStep = statusToStepIndex[status] ?? -1;

    const stepLabel = (() => {
      const labels: Record<string, string> = {
        PENDING: 'Initializing video generation pipeline...',
        ANALYZING_PRODUCT: 'Reading website content',
        GENERATING_CONCEPTS: 'Understanding target audience',
        FETCHING_MEDIA: 'Fetching stock media and assets',
        RENDERING_VIDEO: 'Rendering high-fidelity video concepts',
        UPLOADING: 'Uploading to CDN',
        COMPLETED: 'Video generation complete',
        FAILED: 'Generation failed',
      };
      return labels[status] || 'Processing...';
    })();

    return (
      <div ref={containerRef} className="w-full inline-fade-in my-6">
        <div className="w-full rounded-2xl glass-panel-heavy p-6 border border-white/[0.06] shadow-xl relative overflow-hidden">
          {/* Subtle neon progress pulse */}
          <div className="absolute top-0 left-0 right-0 h-[1.5px] bg-gradient-to-r from-primary/10 via-primary to-primary/10 animate-pulse" />
          
          <div className="flex items-center gap-2.5 mb-4">
            <Waves className="w-5 h-5 text-primary" />
            <h4 className="text-body-lg font-semibold text-text-primary">Generation Pipeline</h4>
            <div className={`ml-auto w-1.5 h-1.5 rounded-full ${connected ? 'bg-success' : 'bg-warning'} animate-pulse`} />
          </div>

          <div className="mb-3 px-3 py-1.5 rounded bg-primary-light/10 border border-primary/10">
            <span className="text-body-sm text-primary font-medium">{stepLabel}</span>
          </div>

          {/* Chronological live steps */}
          <div className="space-y-1 mb-4">
            {workflowSteps.map((step) => (
              <div key={step.id} className="flex items-center gap-3 py-1 text-body-sm">
                <StepIcon stepIndex={step.id} activeStep={activeStep} />
                <span className={step.id === activeStep ? 'text-primary font-medium' : 'text-text-secondary'}>
                  {step.label}
                </span>
                {step.id < activeStep && (
                  <span className="ml-auto text-label-sm text-success uppercase font-semibold">Done</span>
                )}
              </div>
            ))}
          </div>

          {/* Progress Slider */}
          <div>
            <div className="w-full h-1 rounded-pill bg-white/[0.04] overflow-hidden">
              <div
                className="h-full rounded-pill bg-primary transition-all duration-500 ease-out shadow-[0_0_8px_rgba(37,99,235,0.6)]"
                style={{ width: `${Math.min(progress, 100)}%` }}
              />
            </div>
            <div className="flex items-center justify-between mt-2 text-label-sm">
              <p className="text-text-tertiary truncate max-w-[80%]">{message}</p>
              <p className="text-text-secondary font-semibold">{Math.round(Math.min(progress, 100))}%</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Render Loader for past jobs details fetch
  if (loading) {
    return (
      <div className="w-full flex items-center justify-center p-8 text-text-tertiary text-body-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-primary" />
        Loading video player details...
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full rounded-xl border border-warning/20 bg-warning/5 p-4 text-warning text-body-sm my-4">
        Error loading video metadata: {error}
      </div>
    );
  }

  // Render Completed / Failed Job Details
  if (jobDetails) {
    const isCompleted = jobDetails.status === 'COMPLETED';
    const videoUrl = jobDetails.video_url;
    const videoTitle = jobDetails.details?.product_brief?.product
      ? `${jobDetails.details.product_brief.product} UGC Video`
      : 'Generated UGC Video';

    if (!isCompleted) {
      return (
        <div className="w-full rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-text-tertiary text-body-sm my-4">
          Video generation was not completed (Status: <span className="text-warning capitalize font-medium">{jobDetails.status.toLowerCase()}</span>)
        </div>
      );
    }

    const stats = [
      {
        label: 'API Calls',
        value: jobDetails.api_calls_count || 0,
        suffix: '',
        subtitle: 'external requests',
      },
      {
        label: 'Tokens Burned',
        value: jobDetails.total_tokens_burned || 0,
        suffix: '',
        subtitle: 'Gemini IO',
      },
      {
        label: 'File Size',
        value: jobDetails.details?.rendering_stats?.file_size_mb || 0,
        suffix: ' MB',
        subtitle: `${jobDetails.details?.rendering_stats?.resolution || '1080p'} ${jobDetails.details?.rendering_stats?.codec || ''}`,
      },
    ];

    return (
      <div ref={containerRef} className="w-full flex flex-col gap-4 my-6">
        {/* Title and Export Header */}
        <div className="inline-fade-in w-full flex items-center justify-between border-b border-white/[0.04] pb-3">
          <div className="text-body-sm text-text-tertiary">
            <span className="text-primary font-medium">UGC Studio AI</span>
            {' '}/ {`Generation #${jobDetails.job_id.slice(-4)}`}
          </div>
          {videoUrl && (
            <a
              href={videoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-body-sm text-white bg-primary rounded-lg hover:bg-primary-hover active:scale-95 transition-all duration-150 shadow-inner-glow font-medium"
            >
              <ArrowDownToLine className="w-3.5 h-3.5" />
              Download
            </a>
          )}
        </div>

        {/* Video Player */}
        <div className="inline-fade-in w-full rounded-2xl overflow-hidden shadow-2xl border border-white/[0.06]">
          <VideoPlayer
            thumbnail={videoUrl}
            title={videoTitle}
            duration={`${jobDetails.details?.video_plan?.duration || 8}s`}
            currentTimeDisplay="0:00"
          />
        </div>

        {/* Stat Counters Grid */}
        <div className="inline-fade-in grid grid-cols-3 gap-3.5">
          {stats.map((stat, i) => (
            <StatCounter
              key={i}
              label={stat.label}
              value={stat.value}
              suffix={stat.suffix}
              subtitle={stat.subtitle}
              delay={i * 80}
              trigger={statsTriggered}
            />
          ))}
        </div>

        {/* Info Specifications Panel */}
        <div className="inline-fade-in w-full glass-panel-light rounded-xl p-4 border border-white/[0.04]">
          <span className="text-label-sm uppercase text-text-tertiary font-bold tracking-wider mb-2.5 block">Specifications</span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-body-sm">
            {jobDetails.product_url && (
              <div className="col-span-2 sm:col-span-1">
                <span className="text-label-xs uppercase text-text-tertiary/70 tracking-wider">Product Source</span>
                <p className="text-text-primary truncate font-medium mt-0.5" title={jobDetails.product_url}>{new URL(jobDetails.product_url).hostname}</p>
              </div>
            )}
            {jobDetails.details?.video_plan && (
              <>
                <div>
                  <span className="text-label-xs uppercase text-text-tertiary/70 tracking-wider">Video Duration</span>
                  <p className="text-text-primary font-medium mt-0.5">{jobDetails.details.video_plan.duration}s</p>
                </div>
                <div>
                  <span className="text-label-xs uppercase text-text-tertiary/70 tracking-wider">Style Category</span>
                  <p className="text-text-primary capitalize font-medium mt-0.5">{jobDetails.details.video_plan.audioCategory}</p>
                </div>
              </>
            )}
            {jobDetails.details?.rendering_stats && (
              <div>
                <span className="text-label-xs uppercase text-text-tertiary/70 tracking-wider">Resolution Size</span>
                <p className="text-text-primary font-medium mt-0.5">{jobDetails.details.rendering_stats.resolution}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return null;
}

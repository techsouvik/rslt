import { useRef, useEffect } from 'react';
import { Waves, Loader2, Check } from 'lucide-react';
import gsap from 'gsap';
import type { JobStatus } from '@/hooks/useJobSSE';

interface AgentCardData {
  type: 'product' | 'creative';
  quote: string;
}

interface GeneratingScreenProps {
  progress: number;
  status: JobStatus;
  message: string;
  stepLabel: string;
  agentCards: AgentCardData[];
  isConnected: boolean;
}

const workflowSteps = [
  { id: 0, label: 'Reading website content' },
  { id: 1, label: 'Understanding target audience' },
  { id: 2, label: 'Fetching stock media and assets' },
  { id: 3, label: 'Rendering high-fidelity video concepts' },
  { id: 4, label: 'Uploading to CDN' },
];

const statusToStepIndex: Record<JobStatus, number> = {
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
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-success/10 flex items-center justify-center">
        <Check className="w-3.5 h-3.5 text-success" />
      </div>
    );
  }
  if (stepIndex === activeStep) {
    return (
      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
        <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
      </div>
    );
  }
  return (
    <div className="flex-shrink-0 w-6 h-6 rounded-full bg-border-default flex items-center justify-center">
      <div className="w-2 h-2 rounded-full bg-text-tertiary" />
    </div>
  );
}

export default function GeneratingScreen({
  progress,
  status,
  message,
  stepLabel,
  agentCards,
  isConnected,
}: GeneratingScreenProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const activeStep = statusToStepIndex[status] ?? -1;

  useEffect(() => {
    if (!containerRef.current || !panelRef.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(panelRef.current,
        { opacity: 0, scale: 0.96, y: 20 },
        { opacity: 1, scale: 1, y: 0, duration: 0.35, ease: 'power2.out', delay: 0.1 }
      );
      gsap.fromTo('.gen-step',
        { opacity: 0, x: -10 },
        { opacity: 1, x: 0, duration: 0.15, stagger: 0.08, ease: 'power2.out', delay: 0.25 }
      );
      gsap.fromTo('.gen-agent-card',
        { opacity: 0, y: 10 },
        { opacity: 1, y: 0, duration: 0.2, stagger: 0.1, ease: 'power2.out', delay: 0.4 }
      );
    }, containerRef);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={containerRef} className="flex flex-col items-center justify-center w-full py-4 px-2">
      {/* Agent Workflow Panel */}
      <div ref={panelRef} className="w-full max-w-[640px] rounded-3xl glass-panel-heavy p-8 border border-glass-border shadow-2-xl mx-auto">
        {/* Title */}
        <div className="flex items-center gap-3 mb-6">
          <Waves className="w-6 h-6 text-primary" />
          <h2 className="text-headline-lg text-text-primary">Agent Workflow</h2>
          <div className={`ml-auto w-2 h-2 rounded-full ${isConnected ? 'bg-success' : 'bg-warning'} animate-pulse`} />
        </div>

        {/* Current Status */}
        <div className="mb-4 px-3 py-2 rounded-md bg-primary-light/30 border border-primary/10">
          <span className="text-body-md text-primary font-medium">{stepLabel}</span>
        </div>

        {/* Steps */}
        <div className="space-y-1 mb-5">
          {workflowSteps.map((step) => (
            <div key={step.id} className="gen-step flex items-center gap-3 py-2">
              <StepIcon stepIndex={step.id} activeStep={activeStep} />
              <span className={`text-body-lg ${step.id === activeStep ? 'text-primary font-medium' : 'text-text-primary'}`}>
                {step.label}
              </span>
              {step.id < activeStep && (
                <span className="ml-auto text-label-sm text-success uppercase tracking-wider">Done</span>
              )}
            </div>
          ))}
        </div>

        {/* Progress Bar */}
        <div className="mb-1">
          <div className="w-full h-1 rounded-pill bg-black/[0.06] overflow-hidden">
            <div
              className="h-full rounded-pill bg-primary transition-all duration-500 ease-out"
              style={{ width: `${Math.min(progress, 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between mt-2">
            <p className="text-label-sm text-text-secondary">{message}</p>
            <p className="text-label-sm text-text-secondary">{Math.round(Math.min(progress, 100))}%</p>
          </div>
        </div>

        {/* Agent Cards */}
        {agentCards.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-8">
            {agentCards.map((agent, i) => (
              <div key={i} className="gen-agent-card p-4 rounded-md bg-white/50 border border-border-subtle">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-label-sm uppercase text-text-secondary tracking-wider">
                    {agent.type === 'product' ? 'PRODUCT AGENT' : 'CREATIVE AGENT'}
                  </span>
                </div>
                <p className="text-body-md text-text-primary italic leading-relaxed">
                  &ldquo;{agent.quote}&rdquo;
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

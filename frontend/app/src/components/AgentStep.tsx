import { Check, Loader2 } from 'lucide-react';

interface AgentStepProps {
  label: string;
  status: 'completed' | 'active' | 'pending';
}

export default function AgentStep({ label, status }: AgentStepProps) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div
        className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
          status === 'completed'
            ? 'bg-success/10'
            : status === 'active'
            ? 'bg-primary/10'
            : 'bg-border-default'
        }`}
      >
        {status === 'completed' && <Check className="w-3.5 h-3.5 text-success" />}
        {status === 'active' && <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />}
        {status === 'pending' && <div className="w-2 h-2 rounded-full bg-text-tertiary" />}
      </div>
      <span
        className={`text-body-lg ${
          status === 'active' ? 'text-primary font-medium' : 'text-text-primary'
        }`}
      >
        {label}
      </span>
      {status === 'completed' && (
        <span className="ml-auto text-label-sm text-success uppercase tracking-wider">
          Completed
        </span>
      )}
    </div>
  );
}

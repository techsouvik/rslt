interface AgentCardProps {
  type: 'product' | 'creative';
  quote: string;
}

export default function AgentCard({ type, quote }: AgentCardProps) {
  return (
    <div className="p-4 rounded-md bg-white/[0.04] border border-white/[0.06]">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-label-sm uppercase text-text-tertiary tracking-wider">
          {type === 'product' ? 'PRODUCT AGENT' : 'CREATIVE AGENT'}
        </span>
      </div>
      <p className="text-body-md text-text-primary italic leading-relaxed">
        &ldquo;{quote}&rdquo;
      </p>
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import gsap from 'gsap';

interface StatCounterProps {
  label: string;
  value: number;
  suffix: string;
  subtitle: string;
  delay?: number;
  trigger: boolean;
}

export default function StatCounter({
  label,
  value,
  suffix,
  subtitle,
  delay = 0,
  trigger,
}: StatCounterProps) {
  const [display, setDisplay] = useState(0);
  const proxyRef = useRef({ val: 0 });
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (trigger && !hasAnimated.current) {
      hasAnimated.current = true;
      proxyRef.current.val = 0;
      gsap.to(proxyRef.current, {
        val: value,
        duration: 0.8,
        delay: delay / 1000,
        ease: 'power2.out',
        onUpdate: () => {
          setDisplay(proxyRef.current.val);
        },
      });
    }
  }, [trigger, value, delay]);

  const formatValue = () => {
    const trimmedSuffix = suffix.trim();
    if (trimmedSuffix === '%') {
      return `${Math.round(display)}%`;
    }
    if (trimmedSuffix === 'ms') {
      return `${Math.round(display)}ms`;
    }
    if (trimmedSuffix === 'GB/s') {
      return `${display.toFixed(1)} GB/s`;
    }
    if (trimmedSuffix === 'MB') {
      return `${display.toFixed(1)} MB`;
    }

    // For integer/general numbers (like API calls, total tokens burned),
    // round it during counting to avoid floating point loading noise,
    // format with commas, and append suffix if any.
    const rounded = Math.round(display);
    return `${rounded.toLocaleString()}${suffix}`;
  };

  return (
    <div className="flex-1 min-w-[160px]">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-label-sm uppercase text-text-secondary tracking-wider">
          {label}
        </span>
        <span className="text-headline-lg text-primary font-semibold">
          {formatValue()}
        </span>
      </div>
      <p className="text-body-md text-text-secondary">{subtitle}</p>
    </div>
  );
}

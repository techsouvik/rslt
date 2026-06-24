import { useEffect, useRef, useState } from 'react';
import gsap from 'gsap';

export function useAnimatedCounter(
  target: number,
  duration: number = 800,
  delay: number = 0,
  startOnMount: boolean = false
) {
  const [displayValue, setDisplayValue] = useState(0);
  const proxyRef = useRef({ value: 0 });
  const tweenRef = useRef<any>(null);

  const start = () => {
    if (tweenRef.current) tweenRef.current.kill();
    proxyRef.current.value = 0;
    tweenRef.current = gsap.to(proxyRef.current, {
      value: target,
      duration: duration / 1000,
      delay: delay / 1000,
      ease: 'power2.out',
      onUpdate: () => {
        setDisplayValue(proxyRef.current.value);
      },
    });
  };

  useEffect(() => {
    if (startOnMount) {
      start();
    }
    return () => {
      if (tweenRef.current) tweenRef.current.kill();
    };
  }, [target]);

  return { displayValue, start };
}

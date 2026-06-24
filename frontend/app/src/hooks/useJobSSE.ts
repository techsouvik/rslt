import { useState, useEffect, useRef, useCallback } from 'react';
import { connectJobSSE } from '@/api/client';
import type { SSEProgressEvent } from '@/api/client';

export type JobStatus =
  | 'PENDING'
  | 'ANALYZING_PRODUCT'
  | 'GENERATING_CONCEPTS'
  | 'FETCHING_MEDIA'
  | 'RENDERING_VIDEO'
  | 'UPLOADING'
  | 'COMPLETED'
  | 'FAILED';

export interface JobProgress {
  status: JobStatus;
  progress: number;
  message: string;
  videoUrl?: string;
  connected: boolean;
}

const initialProgress: JobProgress = {
  status: 'PENDING',
  progress: 0,
  message: 'Initializing...',
  connected: false,
};

/**
 * Maps SSE status to agent workflow steps
 */
export function getStepStatus(
  stepIndex: number,
  currentStatus: JobStatus
): 'completed' | 'active' | 'pending' {
  const stepMap: Record<number, JobStatus[]> = {
    0: ['ANALYZING_PRODUCT', 'GENERATING_CONCEPTS', 'FETCHING_MEDIA', 'RENDERING_VIDEO', 'UPLOADING', 'COMPLETED'],
    1: ['GENERATING_CONCEPTS', 'FETCHING_MEDIA', 'RENDERING_VIDEO', 'UPLOADING', 'COMPLETED'],
    2: ['FETCHING_MEDIA', 'RENDERING_VIDEO', 'UPLOADING', 'COMPLETED'],
    3: ['RENDERING_VIDEO', 'UPLOADING', 'COMPLETED'],
    4: ['UPLOADING', 'COMPLETED'],
  };

  const activeMap: Record<number, JobStatus> = {
    0: 'ANALYZING_PRODUCT',
    1: 'GENERATING_CONCEPTS',
    2: 'FETCHING_MEDIA',
    3: 'RENDERING_VIDEO',
    4: 'UPLOADING',
  };

  // Check if this step is completed
  const completedStatuses = stepMap[stepIndex] || [];
  const isCompleted = completedStatuses.includes(currentStatus);

  // Check if this step is currently active
  const isActive = activeMap[stepIndex] === currentStatus;

  if (isActive) return 'active';
  if (isCompleted && !isActive) return 'completed';

  // For COMPLETED status, all steps are completed
  if (currentStatus === 'COMPLETED') return 'completed';

  return 'pending';
}

export function useJobSSE(jobId: string | null) {
  const [progress, setProgress] = useState<JobProgress>(initialProgress);
  const cleanupRef = useRef<(() => void) | null>(null);

  const disconnect = useCallback(() => {
    if (cleanupRef.current) {
      cleanupRef.current();
      cleanupRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) return;

    // Reset progress when jobId changes
    setProgress(initialProgress);

    const cleanup = connectJobSSE(
      jobId,
      (event: SSEProgressEvent) => {
        setProgress({
          status: event.status as JobStatus,
          progress: event.progress,
          message: event.message,
          videoUrl: event.video_url,
          connected: true,
        });
      },
      () => {
        setProgress((prev) => ({ ...prev, connected: false }));
      },
      () => {
        setProgress((prev) => ({ ...prev, connected: true }));
      }
    );

    cleanupRef.current = cleanup;

    return () => {
      cleanup();
      cleanupRef.current = null;
    };
  }, [jobId]);

  return { progress, disconnect };
}

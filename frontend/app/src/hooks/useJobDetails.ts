import { useState, useCallback } from 'react';
import { getJobDetails } from '@/api/client';
import type { JobDetails } from '@/api/client';

export function useJobDetails() {
  const [job, setJob] = useState<JobDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async (jobId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getJobDetails(jobId);
      setJob(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load job details');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setJob(null);
    setError(null);
  }, []);

  return { job, loading, error, fetch, clear };
}

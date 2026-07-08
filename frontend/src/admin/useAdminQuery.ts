import { useEffect, useState } from "react";

import { AdminAuthError } from "./api";

export interface QueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Runs an admin fetch on mount (and when `deps` change). An AdminAuthError is
 * not surfaced as an error string — instead `onAuthError` is invoked so the app
 * can drop back to login.
 */
export function useAdminQuery<T>(
  run: () => Promise<T>,
  onAuthError: () => void,
  deps: unknown[],
): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let active = true;
    setState({ data: null, loading: true, error: null });
    run()
      .then((data) => {
        if (active) setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (!active) return;
        if (err instanceof AdminAuthError) {
          onAuthError();
          return;
        }
        setState({
          data: null,
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load.",
        });
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

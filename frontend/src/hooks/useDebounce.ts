import { useState, useEffect } from "react";

/**
 * Debounce a value — returns the value after it has stopped changing for `delay` ms.
 * Useful for search inputs that trigger API calls.
 */
export function useDebounce<T>(value: T, delay: number = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

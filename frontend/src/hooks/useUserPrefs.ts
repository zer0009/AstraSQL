import { useCallback, useEffect, useState } from "react";
import {
  type UserPrefs,
  userPrefs,
} from "../lib/userPrefs";

export function useUserPrefs() {
  const [prefs, setPrefs] = useState<UserPrefs>(() => userPrefs.load());

  const update = useCallback((patch: Partial<UserPrefs>) => {
    setPrefs(userPrefs.save(patch));
  }, []);

  const reset = useCallback(() => {
    setPrefs(userPrefs.load());
  }, []);

  useEffect(() => {
    document.documentElement.dataset.density = prefs.density;
  }, [prefs.density]);

  return { prefs, update, reset };
}

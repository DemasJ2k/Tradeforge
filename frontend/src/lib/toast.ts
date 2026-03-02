/**
 * FlowrexAlgo Toast Utility
 *
 * Usage:
 *   import { showToast } from "@/lib/toast";
 *   showToast.success("Strategy saved!");
 *   showToast.error("Failed to connect broker");
 *   showToast.info("Backtest started...");
 *   showToast.warning("API rate limit approaching");
 */
import { toast } from "sonner";

export const showToast = {
  success: (message: string, description?: string) =>
    toast.success(message, { description }),

  error: (message: string, description?: string) =>
    toast.error(message, { description }),

  info: (message: string, description?: string) =>
    toast.info(message, { description }),

  warning: (message: string, description?: string) =>
    toast.warning(message, { description }),

  loading: (message: string) =>
    toast.loading(message),

  dismiss: (id?: string | number) =>
    toast.dismiss(id),

  promise: <T,>(
    promise: Promise<T>,
    msgs: { loading: string; success: string; error: string }
  ) => toast.promise(promise, msgs),
};

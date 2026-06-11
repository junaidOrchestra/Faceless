import { create } from "zustand";

/**
 * Tiny shared store so any entry point (the floating widget, the nav menu, an
 * empty-state CTA, …) can open the feedback dialog without prop-drilling.
 */
type FeedbackState = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

export const useFeedbackStore = create<FeedbackState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));

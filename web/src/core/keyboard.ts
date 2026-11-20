import type { KeyboardEvent as ReactKeyboardEvent } from "react";

/** Enter during a Chinese/Japanese IME composition must not submit or choose. */
export function isImeEvent(event: ReactKeyboardEvent): boolean {
  return event.nativeEvent.isComposing || event.keyCode === 229;
}

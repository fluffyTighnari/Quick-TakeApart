import { useEffect, useRef } from "react";

/** Only the top-most dialog reacts to Escape, so nested dialogs close one at a time. */
const stack: symbol[] = [];

export function useEscape(onClose: () => void) {
  const id = useRef(Symbol("dialog"));
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const key = id.current;
    stack.push(key);
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (stack[stack.length - 1] !== key) return;
      event.preventDefault();
      event.stopPropagation();
      closeRef.current();
    };
    window.addEventListener("keydown", handler, true);
    return () => {
      window.removeEventListener("keydown", handler, true);
      const index = stack.lastIndexOf(key);
      if (index >= 0) stack.splice(index, 1);
    };
  }, []);
}

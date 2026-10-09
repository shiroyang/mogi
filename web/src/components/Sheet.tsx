// A bottom sheet on phones (drag down to dismiss), a centred dialog on desktop.
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, type ReactNode } from "react";
import { useIsMobile } from "../hooks";

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: string; children: ReactNode }) {
  const mobile = useIsMobile();
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [open, onClose]);
  const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 420, damping: 38 };
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div key="scrim" className="scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : .18 }} onClick={onClose} />
          {mobile ? (
            <motion.div key="sheet" className="sheet" role="dialog" aria-modal="true" aria-label={title}
              initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={spring}
              drag="y" dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: .6 }}
              onDragEnd={(_, info) => { if (info.offset.y > 90 || info.velocity.y > 600) onClose(); }}>
              <div className="grip" aria-hidden="true" />
              {title && <h3>{title}</h3>}
              {children}
            </motion.div>
          ) : (
            <motion.div key="dialog" className="sheet" role="dialog" aria-modal="true" aria-label={title}
              initial={{ opacity: 0, scale: .96, x: "-50%", y: "-48%" }} animate={{ opacity: 1, scale: 1, x: "-50%", y: "-50%" }}
              exit={{ opacity: 0, scale: .98, x: "-50%", y: "-50%" }} transition={spring}>
              {title && <h3>{title}</h3>}
              {children}
            </motion.div>
          )}
        </>
      )}
    </AnimatePresence>
  );
}

// The countdown of a mock round. It follows the server's clock, and calls onDone once when the time is up.
import { useEffect, useRef, useState } from "react";
import { clockText, mockLeft } from "../model";

export function MockClock({ endsAt, onDone }: { endsAt: number; onDone?: () => void }) {
  const [left, setLeft] = useState(() => mockLeft(endsAt));
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    let fired = false;
    const tick = () => {
      const now = mockLeft(endsAt);
      setLeft(now);
      if (now <= 0 && !fired) { fired = true; done.current?.(); }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [endsAt]);
  return <span className={`mockclock${left <= 300 ? " low" : ""}`}>{clockText(left)}</span>;
}

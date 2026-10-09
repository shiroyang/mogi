import { useReducedMotion } from "motion/react";
import { Water } from "../components/Water";

export function Login({ error }: { error?: string }) {
  const reduce = useReducedMotion();
  return (
    <>
      <Water still={!!reduce} />
      <main className="stage">
        <section className="glass card home">
          <div className="etch" aria-hidden="true">模擬</div>
          <header className="top"><span className="wordmark">mogi</span></header>
          <h1 className="headline">Your judge for the 真題 corpus.</h1>
          <p className="support">Real interview questions, each carrying its own tests. Sign in to pick up where you left off.</p>
          {error && <p className="support" style={{ color: "var(--bad)" }}>{error}</p>}
          <div className="tiles">
            <a className="tile primary" href="/api/auth/login"><span className="title">Sign in with GitHub</span></a>
          </div>
        </section>
      </main>
    </>
  );
}

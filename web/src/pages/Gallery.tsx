// Dev only (`npm run dev`, then /gallery): every look of the companion on one page, for working on the art.
import { Porthole, type EggKind } from "../components/Creature";

const KINDS: EggKind[] = ["jelly", "shell", "kelp"];

export function Gallery() {
  return (
    <main className="page" style={{ maxWidth: 1400 }}>
      {KINDS.map(egg => (
        <section key={egg} style={{ marginBottom: 26 }}>
          <h2 className="h2">{egg}</h2>
          <div className="row wrap" style={{ gap: 14 }}>
            {[0, 1, 2].map(c => <Porthole key={`e${c}`} size={150} look={{ egg, stage: 0, cracks: c, mood: "egg" }} />)}
            {[1, 2, 3, 4, 5].map(s => <Porthole key={`s${s}`} size={150} look={{ egg, stage: s, mood: "awake" }} />)}
          </div>
          <div className="row wrap" style={{ gap: 14, marginTop: 14 }}>
            <Porthole size={150} look={{ egg, stage: 3, mood: "hungry" }} />
            <Porthole size={150} look={{ egg, stage: 3, mood: "asleep" }} />
            <Porthole size={88} look={{ egg, stage: 0, cracks: 1, mood: "egg" }} />
            <Porthole size={88} look={{ egg, stage: 1, mood: "awake" }} />
            <Porthole size={88} look={{ egg, stage: 4, mood: "awake" }} />
          </div>
        </section>
      ))}
    </main>
  );
}
